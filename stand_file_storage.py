"""Байты вложений стенда. Транзакцией и правами владеет вызывающий обработчик."""
import base64
import hashlib
import re
import secrets
from stand_object_store import storage, read_verified
from datetime import datetime

FILE_LIMIT = 20 * 1024 * 1024
DEAL_LIMIT = 200 * 1024 * 1024
MIMES = {'application/pdf': ({'pdf'}, b'%PDF-'),
         'image/png': ({'png'}, b'\x89PNG\r\n\x1a\n'),
         'image/jpeg': ({'jpg', 'jpeg'}, b'\xff\xd8\xff'),
         'image/webp': ({'webp'}, b'RIFF')}


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


def validate(raw, mime, name):
    if not raw:
        raise ValueError('Файл пустой')
    if len(raw) > FILE_LIMIT:
        raise ValueError('Файл больше 20 МБ')
    ext = str(name).rsplit('.', 1)[-1].lower()
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
            validate(raw, item.get('mime'), item.get('file'))
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
                validate(raw, item.get('mime'), item.get('file'))
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


def mark_deleted(db, model, previous, current):
    old = {f['storageId'] for _, _, f in entries(previous) if f.get('storageId')}
    new = {f['storageId'] for _, _, f in entries(current) if f.get('storageId')}
    for file_id in old - new:
        row = db.get(model, file_id)
        if row:
            row.deleted_at = datetime.utcnow()
