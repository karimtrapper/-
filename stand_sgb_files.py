"""Prepare task attachments for the SGB per-file limit."""
from io import BytesIO
import re
from threading import Lock
import unicodedata
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
import pymupdf


FILE_LIMIT = 999_999
EXTENSIONS = {'application/pdf': 'pdf', 'image/png': 'png'}
# MuPDF operations share a process, including document recognition requests.
PDF_LOCK = Lock()
_RUSSIAN = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                    'a b v g d e yo zh z i y k l m n o p r s t u f kh ts ch sh shch - y - e yu ya'.split()))
_TRANSLITERATION = str.maketrans({**_RUSSIAN, **{c.upper(): value.capitalize()
                                                for c, value in _RUSSIAN.items()}})


def filename(name, mime):
    if mime not in EXTENSIONS:
        return name
    name = str(name or '').replace('\\', '/').rsplit('/', 1)[-1]
    stem = name.rsplit('.', 1)[0] if '.' in name else name
    stem = unicodedata.normalize('NFKD', stem.translate(_TRANSLITERATION))
    stem = ''.join(char for char in stem if not unicodedata.combining(char))
    stem = re.sub(r'[^A-Za-z0-9_-]+', '_', stem).strip('_-')[:100].rstrip('_-')
    return f"{stem or 'document'}.{EXTENSIONS[mime]}"


def _protected_pdf(doc, raw):
    return (doc.is_encrypted or doc.needs_pass or doc.get_sigflags() > 0
            or doc.xref_get_key(-1, 'Encrypt')[0] != 'null'
            or b'/ByteRange' in raw
            or any(widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE
                   for page in doc for widget in page.widgets()))


def _pdf_bytes(doc):
    return doc.tobytes(garbage=4, deflate=True, no_new_id=True)


def _page_layout(doc):
    return [(tuple(page.rect), page.rotation, page.get_text()) for page in doc]


def _scan_pdf(raw, best_size):
    with pymupdf.open(stream=raw, filetype='pdf') as original:
        if (original.embfile_count() or original.is_form_pdf
                or any(page.get_text().strip() or not page.get_images() or page.first_annot
                       or page.first_link for page in original)):
            return None
        best = best_parts = None
        for dpi, quality, max_side in ((180, 83, 2600), (165, 80, 2300), (155, 78, 2100), (145, 75, 1900)):
            largest_image = 0
            with pymupdf.open() as result:
                for page in original:
                    ratio = min(dpi / 72, max_side / max(1, page.rect.width, page.rect.height))
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(ratio, ratio), alpha=False)
                    jpg = pix.tobytes('jpeg', jpg_quality=quality)
                    largest_image = max(largest_image, len(jpg))
                    copied = result.new_page(width=page.rect.width, height=page.rect.height)
                    copied.insert_image(copied.rect, stream=jpg)
                candidate = _pdf_bytes(result)
            if len(candidate) <= FILE_LIMIT:
                return candidate
            if len(candidate) <= best_size * 0.7:
                if best is None:
                    best = candidate
                if largest_image <= FILE_LIMIT - 32 * 1024 and best_parts is None:
                    if original.page_count > 2:
                        return candidate
                    best_parts = candidate
        return best_parts or best


def _pdf(raw):
    with pymupdf.open(stream=raw, filetype='pdf') as original:
        if _protected_pdf(original, raw) or not 0 < original.page_count <= 150:
            return raw
        layout = _page_layout(original)
        lossless = _pdf_bytes(original)
    best = min((raw, lossless), key=len)
    if len(lossless) <= FILE_LIMIT:
        with pymupdf.open(stream=lossless, filetype='pdf') as result:
            return lossless if _page_layout(result) == layout else raw
    for dpi, quality in ((180, 85), (155, 82), (140, 78)):
        with pymupdf.open(stream=lossless, filetype='pdf') as result:
            result.rewrite_images(dpi_threshold=dpi + 15, dpi_target=dpi, quality=quality,
                                  bitonal=False)
            candidate = _pdf_bytes(result)
        if len(candidate) < len(best):
            best = candidate
        if len(best) <= FILE_LIMIT:
            break
    if best is not raw:
        with pymupdf.open(stream=best, filetype='pdf') as result:
            if _page_layout(result) != layout:
                best = raw
    if len(best) > FILE_LIMIT and all(not page[2].strip() for page in layout):
        scan = _scan_pdf(raw, len(best))
        if scan is not None and len(scan) < len(best):
            return scan
    return best


def _png_bytes(image):
    out = BytesIO()
    image.save(out, format='PNG', optimize=True)
    return out.getvalue()


def _png(raw):
    with Image.open(BytesIO(raw), formats=['PNG']) as original:
        width, height = original.size
        if width * height > 25_000_000 or original.is_animated:
            return raw
        best = min((raw, _png_bytes(original)), key=len)
        if len(best) <= FILE_LIMIT:
            return best
        mode = 'RGBA' if 'A' in original.getbands() or 'transparency' in original.info else 'RGB'
        image = original.convert(mode)
        if width * height <= 2_000_000:
            # Try an indexed PNG at full resolution before discarding pixels.
            indexed = image.quantize(colors=256)
            best = min((best, _png_bytes(indexed)), key=len)
        for side in (2200, 1900, 1600, 1450):
            if len(best) <= FILE_LIMIT:
                break
            ratio = side / max(width, height)
            if ratio < 1:
                scaled = image.resize((max(1, round(width * ratio)), max(1, round(height * ratio))),
                                      Image.Resampling.LANCZOS)
                best = min((best, _png_bytes(scaled)), key=len)
                if len(best) > FILE_LIMIT and scaled.width * scaled.height <= 2_000_000:
                    best = min((best, _png_bytes(scaled.quantize(colors=256))), key=len)
        return best


def prepare(raw, mime, name):
    """Return a smaller file when possible, preserving digitally signed PDFs."""
    safe = filename(name, mime)
    if mime not in EXTENSIONS or len(raw) <= FILE_LIMIT:
        return raw, safe
    try:
        if mime == 'image/png':
            return _png(raw), safe
        with PDF_LOCK:
            return _pdf(raw), safe
    except (pymupdf.mupdf.FzErrorBase, Image.DecompressionBombError, OSError, RuntimeError, ValueError):
        # Keep the uploaded bytes when a codec cannot safely process the document.
        return raw, safe


def _pdf_parts(raw):
    with pymupdf.open(stream=raw, filetype='pdf') as original:
        if _protected_pdf(original, raw):
            raise ValueError('PDF подписан электронной подписью или защищён. Запросите у отправителя файл для СГБ меньше 1 МБ.')
        if original.embfile_count():
            raise ValueError('PDF содержит вложенные файлы. Запросите у отправителя отдельные файлы для СГБ.')
        if not 0 < original.page_count <= 150:
            raise ValueError('Разделите PDF по страницам и загрузите части меньше 1 МБ.')
        parts = []
        position = 0
        while position < original.page_count:
            remaining = original.page_count - position
            best, best_count = None, 0
            count, first_oversized = 1, remaining + 1
            # Grow from the first page so long scanned PDFs do not get copied in half
            # for each part. Once a range exceeds the limit, search the remaining gap.
            while best_count < count < first_oversized:
                with pymupdf.open() as part:
                    part.insert_pdf(original, from_page=position, to_page=position + count - 1)
                    candidate = _pdf_bytes(part)
                if len(candidate) <= FILE_LIMIT:
                    best, best_count = candidate, count
                else:
                    first_oversized = count
                count = (min(remaining, count * 2) if first_oversized == remaining + 1
                         else (best_count + first_oversized) // 2)
            if best is None:
                raise ValueError(f'Страница {position + 1} занимает больше 1 МБ. Загрузите скан меньшего размера.')
            parts.append(best)
            position += best_count
        return parts


def bank_download(raw, mime, name):
    if mime not in EXTENSIONS:
        raise ValueError('Для СГБ доступны PDF и PNG.')
    raw, safe = prepare(raw, mime, name)
    if len(raw) <= FILE_LIMIT:
        return raw, mime, safe
    if mime == 'image/png':
        raise ValueError('Изображение больше 1 МБ. Загрузите PNG меньшего размера.')
    try:
        with PDF_LOCK:
            parts = _pdf_parts(raw)
    except (pymupdf.mupdf.FzErrorBase, RuntimeError) as exc:
        raise ValueError('Не удалось подготовить PDF. Загрузите части меньше 1 МБ.') from exc
    if len(parts) == 1:
        return parts[0], mime, safe
    stem = safe[:-4]
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for index, part in enumerate(parts, 1):
            archive.writestr(f'{stem}_part_{index:03d}.pdf', part)
    return buffer.getvalue(), 'application/zip', f'{stem}_sgb.zip'
