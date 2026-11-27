"""Байты вложений стенда. Транзакцией и правами владеет вызывающий обработчик."""
import base64
import hashlib
from io import BytesIO
import posixpath
import re
import secrets
import zipfile
import zlib
from xml.etree import ElementTree
from xml.parsers import expat
from stand_object_store import storage, read_verified
from datetime import datetime

FILE_LIMIT = 20 * 1024 * 1024
DEAL_LIMIT = 200 * 1024 * 1024
DOCUMENT_MIMES = {'application/pdf': ({'pdf'}, b'%PDF-'),
         'image/png': ({'png'}, b'\x89PNG\r\n\x1a\n'),
         'image/jpeg': ({'jpg', 'jpeg'}, b'\xff\xd8\xff'),
         'image/webp': ({'webp'}, b'RIFF')}
EXCEL_MIMES = {
    'application/vnd.ms-excel': ({'xls'}, b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'),
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ({'xlsx'}, b'PK\x03\x04'),
}
MIMES = {**DOCUMENT_MIMES, **EXCEL_MIMES}


def _xls_content_valid(raw):
    """Прочитать поток Workbook через FAT/miniFAT OLE и проверить BIFF BOF."""
    end = 0xFFFFFFFE
    free = 0xFFFFFFFF
    if len(raw) < 1536 or raw[:8] != EXCEL_MIMES['application/vnd.ms-excel'][1]:
        return False
    major = int.from_bytes(raw[26:28], 'little')
    shift = int.from_bytes(raw[30:32], 'little')
    if (major, shift) not in ((3, 9), (4, 12)) or raw[28:30] != b'\xfe\xff':
        return False
    sector_size = 1 << shift
    if len(raw) % sector_size or len(raw) < sector_size * 3:
        return False
    sector_count = len(raw) // sector_size - 1

    def u32(data, offset):
        return int.from_bytes(data[offset:offset + 4], 'little')

    def sector(sid):
        if sid >= sector_count:
            raise ValueError('OLE sector outside file')
        offset = (sid + 1) * sector_size
        return raw[offset:offset + sector_size]

    try:
        fat_count = u32(raw, 44)
        difat_count = u32(raw, 72)
        if not 0 < fat_count <= sector_count or difat_count > sector_count:
            return False
        fat_sectors = [sid for sid in (u32(raw, 76 + i * 4) for i in range(109)) if sid != free]
        difat_sid = u32(raw, 68)
        seen_difat = set()
        for _ in range(difat_count):
            if difat_sid in seen_difat:
                return False
            seen_difat.add(difat_sid)
            block = sector(difat_sid)
            fat_sectors.extend(sid for sid in
                               (u32(block, i * 4) for i in range(sector_size // 4 - 1))
                               if sid != free)
            difat_sid = u32(block, sector_size - 4)
        if difat_sid != end or len(fat_sectors) != fat_count or len(set(fat_sectors)) != fat_count:
            return False
        fat = b''.join(sector(sid) for sid in fat_sectors)

        def fat_next(sid):
            if sid >= sector_count or (sid + 1) * 4 > len(fat):
                raise ValueError('OLE FAT outside file')
            return u32(fat, sid * 4)

        def read_chain(start, next_sid, block_size, get_block, size=None):
            chunks, seen, sid = [], set(), start
            while sid != end:
                if sid in seen or len(seen) >= sector_count * (sector_size // block_size):
                    raise ValueError('OLE cyclic chain')
                seen.add(sid)
                chunks.append(get_block(sid))
                sid = next_sid(sid)
            data = b''.join(chunks)
            if size is not None and len(data) < size:
                raise ValueError('OLE truncated stream')
            return data if size is None else data[:size]

        directory = read_chain(u32(raw, 48), fat_next, sector_size, sector)
        root = directory[:128]
        if len(root) != 128 or root[66] != 5:
            return False
        workbook = None
        for offset in range(128, len(directory) - 127, 128):
            entry = directory[offset:offset + 128]
            length = int.from_bytes(entry[64:66], 'little')
            if entry[66] == 2 and 2 <= length <= 64 and length % 2 == 0:
                name = entry[:length - 2].decode('utf-16le', errors='ignore')
                if name in ('Workbook', 'Book'):
                    workbook = entry
                    break
        if workbook is None:
            return False
        size = int.from_bytes(workbook[120:128], 'little')
        if not 16 <= size <= FILE_LIMIT:
            return False
        start = u32(workbook, 116)
        cutoff = u32(raw, 56)
        if cutoff != 4096:
            return False
        if size >= cutoff:
            data = read_chain(start, fat_next, sector_size, sector, size)
        else:
            mini_count = u32(raw, 64)
            if not 0 < mini_count <= sector_count:
                return False
            mini_fat = read_chain(u32(raw, 60), fat_next, sector_size, sector)
            if len(mini_fat) < mini_count * sector_size:
                return False
            mini_stream = read_chain(u32(root, 116), fat_next, sector_size, sector,
                                     int.from_bytes(root[120:128], 'little'))

            def mini_sector(sid):
                offset = sid * 64
                if offset + 64 > len(mini_stream):
                    raise ValueError('OLE mini sector outside stream')
                return mini_stream[offset:offset + 64]

            def mini_next(sid):
                if (sid + 1) * 4 > len(mini_fat):
                    raise ValueError('OLE mini FAT outside file')
                return u32(mini_fat, sid * 4)

            data = read_chain(start, mini_next, 64, mini_sector, size)
        # BIFF: обязательны глобальный поток, EOF и хотя бы один лист,
        # указанный BOUNDSHEET, со своим BOF/EOF. Одного BOF недостаточно.
        def record(offset):
            if offset < 0 or offset + 4 > len(data):
                raise ValueError('BIFF record header outside stream')
            record_type = int.from_bytes(data[offset:offset + 2], 'little')
            length = int.from_bytes(data[offset + 2:offset + 4], 'little')
            stop = offset + 4 + length
            if stop > len(data):
                raise ValueError('BIFF record outside stream')
            return record_type, data[offset + 4:stop], stop

        def bof(offset, types):
            record_type, payload, stop = record(offset)
            return (record_type == 0x0809 and len(payload) >= 16
                    and int.from_bytes(payload[:2], 'little') in (0x0500, 0x0600)
                    and int.from_bytes(payload[2:4], 'little') in types), stop

        valid, position = bof(0, {0x0005})
        if not valid:
            return False
        sheet_offsets = []
        while position < len(data):
            record_type, payload, position = record(position)
            if record_type == 0x0085 and len(payload) >= 8:
                sheet_offsets.append(int.from_bytes(payload[:4], 'little'))
            if record_type == 0x000A:
                if payload:
                    return False
                break
        else:
            return False
        globals_end = position
        if not sheet_offsets:
            return False
        for sheet_offset in sheet_offsets:
            if sheet_offset < globals_end or sheet_offset >= len(data):
                return False
            valid, position = bof(sheet_offset, {0x0010, 0x0020, 0x0040})
            if not valid:
                return False
            while position < len(data):
                record_type, payload, position = record(position)
                if record_type == 0x000A:
                    if payload:
                        return False
                    break
            else:
                return False
        return True
    except (ValueError, IndexError, OverflowError):
        return False


def _xlsx_content_valid(raw):
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            listed = archive.namelist()
            names = set(listed)
            required = {'[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml',
                        'xl/_rels/workbook.xml.rels'}
            if len(listed) > 2000 or len(names) != len(listed) or not required <= names:
                return False
            # Проверяем и второстепенные части: повреждённая строковая таблица
            # оставляла внешне корректные workbook.xml и relationships.
            if sum(info.file_size for info in archive.infolist()) > 128 * 1024 * 1024:
                return False
            if archive.testzip() is not None:
                return False
            def preflight_xml(content):
                probe = expat.ParserCreate()
                def reject_declaration(*_):
                    raise ValueError('OOXML DTD is forbidden')
                probe.StartDoctypeDeclHandler = reject_declaration
                probe.EntityDeclHandler = reject_declaration
                probe.ExternalEntityRefHandler = reject_declaration
                probe.Parse(content, True)

            # Необязательные части (например, sharedStrings) тоже должны быть
            # корректным XML без DTD; проверка CRC не замечает их XML-поломку.
            for info in archive.infolist():
                if info.filename.lower().endswith(('.xml', '.rels')):
                    preflight_xml(archive.read(info))

            def xml(name, limit):
                info = archive.getinfo(name)
                if not 0 < info.file_size <= limit:
                    raise ValueError('OOXML part size')
                content = archive.read(info)
                return ElementTree.fromstring(content)

            pkg = 'http://schemas.openxmlformats.org/package/2006/'
            office = 'http://schemas.openxmlformats.org/officeDocument/2006/'
            sheet_ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
            types = xml('[Content_Types].xml', 1024 * 1024)
            root_rels = xml('_rels/.rels', 1024 * 1024)
            book = xml('xl/workbook.xml', 2 * 1024 * 1024)
            book_rels = xml('xl/_rels/workbook.xml.rels', 1024 * 1024)
            if (types.tag != '{' + pkg + 'content-types}Types'
                    or root_rels.tag != '{' + pkg + 'relationships}Relationships'
                    or book_rels.tag != root_rels.tag
                    or book.tag != '{' + sheet_ns + '}workbook'):
                return False
            overrides = {item.get('PartName'): item.get('ContentType')
                         for item in types.findall('{' + pkg + 'content-types}Override')}
            if overrides.get('/xl/workbook.xml') != (
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'):
                return False
            if not any(rel.get('Type') == office + 'relationships/officeDocument'
                       and rel.get('Target', '').lstrip('/') == 'xl/workbook.xml'
                       for rel in root_rels):
                return False
            relationships = {rel.get('Id'): rel for rel in book_rels
                             if rel.get('Type') == office + 'relationships/worksheet'
                             and rel.get('TargetMode') != 'External'}
            sheets = book.find('{' + sheet_ns + '}sheets')
            if sheets is None:
                return False
            found_sheet = False
            for sheet in sheets.findall('{' + sheet_ns + '}sheet'):
                rel = relationships.get(sheet.get('{' + office + 'relationships}id'))
                if rel is None:
                    return False
                target = rel.get('Target', '')
                part = posixpath.normpath(target.lstrip('/') if target.startswith('/')
                                         else posixpath.join('xl', target))
                if (not part.startswith('xl/worksheets/') or part not in names
                        or overrides.get('/' + part) !=
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'
                        or xml(part, 32 * 1024 * 1024).tag != '{' + sheet_ns + '}worksheet'):
                    return False
                found_sheet = True
            return found_sheet
    except (ValueError, OSError, EOFError, KeyError, NotImplementedError, RuntimeError,
            zipfile.BadZipFile, zlib.error, ElementTree.ParseError, expat.ExpatError):
        return False


def _excel_content_valid(raw, mime):
    return (_xls_content_valid(raw) if mime == 'application/vnd.ms-excel'
            else _xlsx_content_valid(raw))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(item):
    data = item.get('data') or ''
    try:
        header, content = data.split(',', 1)
        if header != 'data:' + item['mime'] + ';base64':
            raise ValueError()
        return base64.b64decode(content, validate=True)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('Не удалось прочитать вложение: ' + str(item.get('file', ''))) from exc


def validate(raw, mime, name, kind=None):
    if not raw:
        raise ValueError('Файл пустой')
    if len(raw) > FILE_LIMIT:
        raise ValueError('Файл больше 20 МБ')
    ext = str(name).rsplit('.', 1)[-1].lower()
    if mime in EXCEL_MIMES:
        if (kind == 'bankCreditEvidence' and ext in EXCEL_MIMES[mime][0]
                and raw.startswith(EXCEL_MIMES[mime][1]) and _excel_content_valid(raw, mime)):
            return
        raise ValueError('Для выписки разрешены только настоящие XLS или XLSX')
    if (mime not in MIMES or ext not in MIMES[mime][0]
            or not raw.startswith(MIMES[mime][1])
            or (mime == 'image/webp' and raw[8:12] != b'WEBP')):
        raise ValueError('Разрешены только настоящие PDF, PNG, JPEG или WEBP')


def entries(state):
    for deal in state.get('deals') or []:
        for target in (deal, deal.get('_managerDraft') or {}):
            for kind, files in (target.get('files') or {}).items():
                if isinstance(files, list):
                    for item in files:
                        if isinstance(item, dict):
                            yield deal, kind, item


def store(db, model, deal_id, kind, item, raw, actor=None):
    sha = digest(raw)
    row = db.query(model).filter_by(deal_id=deal_id, kind=kind, sha256=sha).first()
    if row is None:
        try:
            validate(raw, item.get('mime'), item.get('file'), kind)
            valid = True
        except ValueError:
            valid = False
        file_id = secrets.token_hex(16)
        key = 'stand-files/' + file_id
        storage().put(key, raw, item.get('mime') or '')
        row = model(id=file_id, object_key=key, content_valid=valid, deal_id=deal_id, kind=kind,
                    filename=item.get('file') or 'file', mime=item.get('mime') or '',
                    size=len(raw), sha256=sha,
                    uploaded_by=str(actor if actor is not None else item.get('uploadedById') or 'legacy'),
                    uploaded_at=datetime.utcnow(), legacy_at=str(item.get('at') or ''))
        db.add(row)
        db.flush()
    # Проверка именно сохранённых байтов; несовпадение никогда не затирает JSON.
    if row.size != len(raw) or read_verified(row.object_key, row.size, sha) != raw:
        raise ValueError('Не совпали размер или SHA256 сохранённого файла')
    row.deleted_at = None
    return dict(item, storageId=row.id, sha256=sha, bytes=row.size, data='__detached__')


def resolve(db, model, item, deal_id=None, kind=None):
    row = db.get(model, item.get('storageId')) if item.get('storageId') else None
    if (not row or row.deleted_at is not None or (deal_id is not None and row.deal_id != deal_id)
            or (kind is not None and row.kind != kind)
            or row.sha256 != item.get('sha256') or row.size != item.get('bytes')
            or row.mime != item.get('mime')):
        raise ValueError('Недействительная ссылка на файл')
    return row


def externalize(db, model, state, *, migration=False, actor=None, previous=None):
    old_data = {(d.get('id'), kind, f.get('data')) for d, kind, f in entries(previous or {})
                if str(f.get('data') or '').startswith('data:')}
    # Проверяем потолок до записи объектов: отказ не оставляет лишний объект.
    if not migration:
        planned, unique = {}, set()
        for deal, kind, item in entries(state):
            if item.get('storageId'):
                row = resolve(db, model, item, deal['id'], kind)
                sha, size = row.sha256, row.size
            elif str(item.get('data') or '').startswith('data:'):
                raw = decode(item)
                sha, size = digest(raw), len(raw)
            else:
                continue
            identity = (deal['id'], kind, sha)
            if identity not in unique:
                planned[deal['id']] = planned.get(deal['id'], 0) + size
                unique.add(identity)
        if any(size > DEAL_LIMIT for size in planned.values()):
            raise ValueError('Вложения сделки превышают 200 МБ. Удалите ненужные файлы.')
    changed = False
    totals = {}
    seen = set()
    for deal, kind, item in entries(state):
        if item.get('storageId'):
            row = resolve(db, model, item, deal['id'], kind)
        elif str(item.get('data') or '').startswith('data:'):
            raw = decode(item)
            if not migration and (deal['id'], kind, item.get('data')) not in old_data:
                validate(raw, item.get('mime'), item.get('file'), kind)
            author = None if migration or (deal['id'], kind, item.get('data')) in old_data else actor
            ref = store(db, model, deal['id'], kind, item, raw, author)
            item.clear()
            item.update(ref)
            row = db.get(model, item['storageId'])
            changed = True
        elif item.get('data') == '__detached__':
            raise ValueError('Не найдены байты вложения')
        else:
            continue  # Старые записи только с именем не выдаём за настоящий файл.
        if row.id not in seen:
            totals[deal['id']] = totals.get(deal['id'], 0) + row.size
            seen.add(row.id)
    if not migration and any(size > DEAL_LIMIT for size in totals.values()):
        raise ValueError('Вложения сделки превышают 200 МБ. Удалите ненужные файлы.')
    return changed


def normalize_incoming(previous, incoming, modern=False):
    """Старая вкладка не может стереть новые ссылки или вернуть base64 назад."""
    old = {d['id']: d for d in previous.get('deals') or []}
    for deal in incoming.get('deals') or []:
        before = old.get(deal.get('id'), {})
        refs = {(kind, f.get('storageId')): f for _, kind, f in entries({'deals': [before]})
                if f.get('storageId')}
        for target, prior in ((deal, before),
                              (deal.get('_managerDraft'), before.get('_managerDraft') or {})):
            if not isinstance(target, dict):
                continue
            for kind, files in (target.get('files') or {}).items():
                if not isinstance(files, list):
                    raise ValueError('Некорректный список файлов')
                for index, item in enumerate(files):
                    if not isinstance(item, dict):
                        continue
                    if item.get('storageId'):
                        ref = refs.get((kind, item['storageId']))
                        if not ref or any(item.get(k) != ref.get(k) for k in
                                          ('sha256', 'bytes', 'mime', 'file', 'data')):
                            raise ValueError('Недействительная ссылка на файл')
                    elif str(item.get('data') or '').startswith('data:'):
                        sha = digest(decode(item))
                        match = next((f for (k, _), f in refs.items()
                                      if k == kind and f['sha256'] == sha), None)
                        if match:
                            files[index] = dict(match)
            if not modern:
                # У старых клиентов фильтр 2 МБ удаляет большие файлы из памяти.
                # Удаление таких ссылок допускаем лишь новым протоколом сохранения.
                for kind, files in (prior.get('files') or {}).items():
                    for item in files:
                        if not isinstance(item, dict) or not item.get('storageId'):
                            continue
                        dest = target.setdefault('files', {}).setdefault(kind, [])
                        if not any(f.get('storageId') == item['storageId'] for f in dest if isinstance(f, dict)):
                            dest.append(dict(item))
                            for field in ('docs', 'docMeta'):
                                if kind in (prior.get(field) or {}):
                                    target.setdefault(field, {})[kind] = prior[field][kind]


def safe_name(name):
    return re.sub(r'[<>"\x27`&\x00-\x1f/\\]', '_', str(name or 'file'))[:200]


def purge(db, model, row):
    """Удалить объект и строку насовсем. Транзакцию ведёт вызывающий; при ошибке хранилища строка остаётся."""
    storage().delete(row.object_key)
    db.delete(row)


def mark_deleted(db, model, previous, current):
    old = {f['storageId'] for _, _, f in entries(previous) if f.get('storageId')}
    new = {f['storageId'] for _, _, f in entries(current) if f.get('storageId')}
    for file_id in old - new:
        row = db.get(model, file_id)
        if row:
            row.deleted_at = datetime.utcnow()
