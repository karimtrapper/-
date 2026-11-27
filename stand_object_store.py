"""Приватные объекты: S3 в Railway, явный каталог только для локальной работы."""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


class StorageUnavailable(ValueError):
    pass


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)

    def path(self, key):
        if not re.fullmatch(r'stand-files/[0-9a-f]{32}', key):
            raise ValueError('Некорректный ключ объекта')
        return self.root / key

    def put(self, key, raw, mime):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Имена случайные, существующие объекты не перезаписываем.
        with path.open('xb') as stream:
            stream.write(raw)

    def open(self, key):
        return self.path(key).open('rb')

    def delete(self, key):
        try:
            self.path(key).unlink()
        except FileNotFoundError:
            # Объекта уже нет: повторное удаление безопасно.
            pass


class S3Store:
    def __init__(self, endpoint, bucket, access, secret):
        import boto3
        from botocore.config import Config
        parts = urlsplit(endpoint)
        if (parts.scheme != 'https' or not parts.hostname or parts.port not in (None, 443)
                or parts.username or parts.password or parts.path not in ('', '/')
                or parts.query or parts.fragment or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket)):
            raise StorageUnavailable('Некорректные настройки хранилища файлов')
        style = os.environ.get('STAND_FILES_S3_ADDRESSING', 'virtual-host').replace('virtual-host', 'virtual')
        if style not in ('virtual', 'path'):
            raise StorageUnavailable('STAND_FILES_S3_ADDRESSING: virtual или path')
        self.host = bucket + '.' + parts.hostname if style == 'virtual' else parts.hostname
        self.bucket = bucket
        self.client = boto3.client('s3', endpoint_url=endpoint,
            aws_access_key_id=access, aws_secret_access_key=secret,
            region_name=os.environ.get('STAND_FILES_S3_REGION', 'auto'),
            config=Config(signature_version='s3v4', s3={'addressing_style': style},
                          proxies={}, connect_timeout=5, read_timeout=30,
                          retries={'max_attempts': 2},
                          request_checksum_calculation='when_required',
                          response_checksum_validation='when_required'))

    def call(self, method, **kwargs):
        import stand_egress
        try:
            with stand_egress.storage_connection(self.host):
                return getattr(self.client, method)(Bucket=self.bucket, **kwargs)
        except Exception:
            # Ошибки SDK могут содержать подписанный URL: наружу и в лог не отдаём.
            raise StorageUnavailable('Хранилище файлов недоступно. Повторите загрузку позже.') from None

    def put(self, key, raw, mime):
        self.call('put_object', Key=key, Body=raw, ContentType=mime)

    def open(self, key):
        return self.call('get_object', Key=key)['Body']

    def delete(self, key):
        # delete_object идемпотентен: отсутствующий ключ не считается ошибкой.
        self.call('delete_object', Key=key)


def storage():
    local = os.environ.get('STAND_FILES_LOCAL_DIR')
    if local:
        if os.environ.get('RAILWAY_ENVIRONMENT_ID'):
            raise StorageUnavailable('В Railway файлы должны храниться в S3')
        return LocalStore(local)
    values = [os.environ.get(k) for k in ('STAND_FILES_S3_ENDPOINT', 'STAND_FILES_S3_BUCKET',
                                         'STAND_FILES_S3_ACCESS_KEY_ID', 'STAND_FILES_S3_SECRET_ACCESS_KEY')]
    if not all(values):
        raise StorageUnavailable('Хранилище файлов не настроено. Обратитесь к администратору.')
    return S3Store(*values)


def read_verified(key, size, sha):
    import hashlib
    with storage().open(key) as stream:
        raw = stream.read(size + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError('Не совпали размер или SHA256 объекта')
    return raw
