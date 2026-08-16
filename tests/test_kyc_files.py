"""KYC: документы хранятся в БД, переживают решение менеджера и видео-заявление.

Что ловим:
- регрессию «одобрил → документы исчезли» (файлы удалялись в approve/reject);
- потерю файлов при деплое (лежали на эфемерном диске контейнера);
- обход шага видео-заявления запросом мимо страницы;
- заливку под видом видео чего угодно (проверка magic bytes);
- ретенцию: через год документы стираются, запись о проверке остаётся.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_kyc_files.py -v
"""
import io
import os
import sys
import zipfile
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'
os.environ['KYC_RETENTION_ENABLED'] = '0'

from app import (app, limiter, get_session, AdminUser, KycRequest, KycFile, KycStatus,
                 purge_expired_kyc_files)

# /api/kyc/submit ограничен 10 запросами в час на IP — в тестах IP один и тот же.
# Флаг на объекте, а не в config: limiter читает конфиг один раз при init_app.
limiter.enabled = False

# Минимальные валидные файлы: важны первые байты, дальше — любой мусор.
JPEG = b'\xff\xd8\xff\xe0' + b'\x00' * 64
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
WEBM = b'\x1a\x45\xdf\xa3' + b'\x00' * 64
MP4 = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 64


@pytest.fixture(autouse=True)
def clean_kyc():
    def _clean():
        s = get_session()
        try:
            s.query(KycFile).delete()
            s.query(KycRequest).delete()
            s.commit()
        finally:
            s.close()
    _clean()
    yield
    _clean()


@pytest.fixture
def tc():
    """Test client с сессией админа — CRM-эндпоинты требуют логина.

    Клиент отдаётся без `with`: в тесте одновременно живут менеджерский и
    анонимный клиенты, а вложенные контексты Flask роняют стек запросов.
    """
    app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='kyc_test_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    c = app.test_client()
    with c.session_transaction() as sess:
        sess['user_id'] = aid
    return c


@pytest.fixture
def anon():
    """Клиент без авторизации — так на страницу верификации ходит человек."""
    app.config['TESTING'] = True
    return app.test_client()


def make_token(tc, statement_required=False, statement_text=''):
    resp = tc.post('/api/kyc/generate', json={
        'client_name': 'Иван Тестовый',
        'statement_required': statement_required,
        'statement_text': statement_text,
    })
    assert resp.status_code == 200
    return resp.get_json()['token']


def submit(anon, token, doc=JPEG, selfie=JPEG, liveness=2, statement=None):
    data = {'token': token}
    if doc:
        data['document'] = (io.BytesIO(doc), 'doc.jpg', 'image/jpeg')
    if selfie:
        data['selfie'] = (io.BytesIO(selfie), 'selfie.jpg', 'image/jpeg')
    if liveness:
        data['liveness'] = [(io.BytesIO(JPEG), f'l{i}.jpg', 'image/jpeg')
                            for i in range(liveness)]
    if statement is not None:
        blob, mime, name = statement
        data['statement'] = (io.BytesIO(blob), name, mime)
    return anon.post('/api/kyc/submit', data=data, content_type='multipart/form-data')


class TestFilesSurvive:
    def test_files_stored_in_db(self, tc, anon):
        token = make_token(tc)
        assert submit(anon, token).status_code == 200

        s = get_session()
        try:
            kyc = s.query(KycRequest).filter_by(token=token).one()
            kinds = sorted(f.kind for f in kyc.files)
            assert kinds == ['doc', 'liveness', 'liveness', 'selfie']
            assert all(f.size > 0 and f.data for f in kyc.files)
        finally:
            s.close()

    def test_approve_keeps_files(self, tc, anon):
        """Главная регрессия: раньше approve стирал документы с диска."""
        token = make_token(tc)
        submit(anon, token)

        assert tc.post(f'/api/kyc/approve/{token}', json={'manager': 'k'}).status_code == 200

        review = tc.get(f'/api/kyc/review/{token}').get_json()['kyc']
        assert review['status'] == 'approved'
        assert review['has_doc'] and review['has_selfie'] and review['has_liveness']
        assert tc.get(f'/api/kyc/photo/{token}/doc').status_code == 200

    def test_reject_keeps_files(self, tc, anon):
        token = make_token(tc)
        submit(anon, token)
        tc.post(f'/api/kyc/reject/{token}', json={'manager': 'k', 'reason': 'мутно'})
        assert tc.get(f'/api/kyc/photo/{token}/selfie').status_code == 200

    def test_cancel_removes_everything(self, tc, anon):
        token = make_token(tc)
        submit(anon, token)
        assert tc.delete(f'/api/kyc/{token}').status_code == 200

        s = get_session()
        try:
            assert s.query(KycRequest).filter_by(token=token).first() is None
            assert s.query(KycFile).count() == 0
        finally:
            s.close()

    def test_resubmit_replaces_old_files(self, tc, anon):
        token = make_token(tc)
        submit(anon, token, liveness=5)
        submit(anon, token, liveness=2)

        s = get_session()
        try:
            kyc = s.query(KycRequest).filter_by(token=token).one()
            assert sum(1 for f in kyc.files if f.kind == 'liveness') == 2
        finally:
            s.close()

    def test_failed_resubmit_keeps_previous_files(self, tc, anon):
        """Битый повторный сабмит не должен оставить менеджера без документов."""
        token = make_token(tc)
        submit(anon, token)

        bad = submit(anon, token, doc=b'not-an-image-at-all')
        assert bad.status_code == 400

        assert tc.get(f'/api/kyc/photo/{token}/doc').status_code == 200


class TestDownload:
    def test_photo_requires_auth(self, tc, anon):
        token = make_token(tc)
        submit(anon, token)
        assert anon.get(f'/api/kyc/photo/{token}/doc').status_code == 401

    def test_download_flag_sets_attachment(self, tc, anon):
        token = make_token(tc)
        submit(anon, token)

        inline = tc.get(f'/api/kyc/photo/{token}/doc')
        assert 'attachment' not in inline.headers.get('Content-Disposition', '')

        dl = tc.get(f'/api/kyc/photo/{token}/doc?download=1')
        assert 'attachment' in dl.headers['Content-Disposition']
        assert dl.data.startswith(b'\xff\xd8\xff')

    def test_archive_contains_all_files_and_readme(self, tc, anon):
        token = make_token(tc, True, 'Я, Иван, подтверждаю обмен')
        submit(anon, token, statement=(WEBM, 'video/webm', 's.webm'))

        resp = tc.get(f'/api/kyc/archive/{token}')
        assert resp.status_code == 200
        names = zipfile.ZipFile(io.BytesIO(resp.data)).namelist()
        assert any(n.endswith('doc.jpg') for n in names)
        assert any(n.endswith('statement.webm') for n in names)
        assert any(n.endswith('README.txt') for n in names)

        readme = next(n for n in names if n.endswith('README.txt'))
        body = zipfile.ZipFile(io.BytesIO(resp.data)).read(readme).decode()
        assert 'Я, Иван, подтверждаю обмен' in body

    def test_archive_requires_auth(self, tc, anon):
        token = make_token(tc)
        submit(anon, token)
        assert anon.get(f'/api/kyc/archive/{token}').status_code == 401

    def test_cyrillic_client_name_does_not_break_download(self, tc, anon):
        """secure_filename() съедает кириллицу целиком — имя не должно стать пустым."""
        token = make_token(tc)
        assert submit(anon, token).status_code == 200
        assert tc.get(f'/api/kyc/photo/{token}/doc?download=1').status_code == 200
        assert tc.get(f'/api/kyc/archive/{token}').status_code == 200


class TestStatement:
    def test_status_exposes_statement_to_client(self, tc, anon):
        token = make_token(tc, True, 'Читаю вслух')
        data = anon.get(f'/api/kyc/status/{token}').get_json()
        assert data['statement_required'] is True
        assert data['statement_text'] == 'Читаю вслух'

    def test_default_text_generated_when_manager_left_it_empty(self, tc, anon):
        token = make_token(tc, True, '')
        data = anon.get(f'/api/kyc/status/{token}').get_json()
        assert 'Иван Тестовый' in data['statement_text']
        assert 'добровольно' in data['statement_text']

    def test_submit_without_video_rejected(self, tc, anon):
        """Шаг нельзя пропустить, отправив форму мимо страницы."""
        token = make_token(tc, True, 'Читаю вслух')
        resp = submit(anon, token)
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'statement_required'

    def test_webm_and_mp4_accepted(self, tc, anon):
        for blob, mime, name in ((WEBM, 'video/webm', 's.webm'), (MP4, 'video/mp4', 's.mp4')):
            token = make_token(tc, True, 'Читаю вслух')
            assert submit(anon, token, statement=(blob, mime, name)).status_code == 200
            assert tc.get(f'/api/kyc/photo/{token}/statement').status_code == 200

    def test_fake_video_rejected_by_magic_bytes(self, tc, anon):
        """Заявленный MIME подделать легко, содержимое — нет."""
        token = make_token(tc, True, 'Читаю вслух')
        resp = submit(anon, token, statement=(JPEG, 'video/webm', 'fake.webm'))
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'statement_invalid_video_magic'

    def test_oversized_video_rejected(self, tc, anon):
        token = make_token(tc, True, 'Читаю вслух')
        huge = WEBM + b'\x00' * (16 * 1024 * 1024)
        resp = submit(anon, token, statement=(huge, 'video/webm', 'big.webm'))
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'statement_too_large'

    def test_statement_optional_when_not_required(self, tc, anon):
        token = make_token(tc, False)
        assert submit(anon, token).status_code == 200

    def test_regenerate_updates_statement_on_live_link(self, tc):
        """Повторная выдача ссылки живому запросу переносит новые условия."""
        s = get_session()
        try:
            kyc = KycRequest(token='tok-existing', client_id=424242,
                             client_name='Иван', status=KycStatus.PENDING)
            s.add(kyc); s.commit()
        finally:
            s.close()

        resp = tc.post('/api/kyc/generate', json={
            'client_id': 424242, 'client_name': 'Иван',
            'statement_required': True, 'statement_text': 'Новый текст',
        })
        assert resp.get_json()['existing'] is True

        s = get_session()
        try:
            kyc = s.query(KycRequest).filter_by(token='tok-existing').one()
            assert kyc.statement_required is True
            assert kyc.statement_text == 'Новый текст'
        finally:
            s.close()


class TestRetention:
    def test_old_files_purged_record_kept(self, tc, anon):
        token = make_token(tc)
        submit(anon, token)
        tc.post(f'/api/kyc/approve/{token}', json={'manager': 'k'})

        s = get_session()
        try:
            kyc = s.query(KycRequest).filter_by(token=token).one()
            kyc.reviewed_at = datetime.utcnow() - timedelta(days=400)
            s.commit()
        finally:
            s.close()

        assert purge_expired_kyc_files() == 1

        review = tc.get(f'/api/kyc/review/{token}').get_json()['kyc']
        assert review['status'] == 'approved'          # факт проверки остался
        assert review['has_doc'] is False              # документы стёрты
        assert review['files_purged_at']
        assert tc.get(f'/api/kyc/photo/{token}/doc').status_code == 404

    def test_fresh_files_survive_purge(self, tc, anon):
        token = make_token(tc)
        submit(anon, token)
        tc.post(f'/api/kyc/approve/{token}', json={'manager': 'k'})

        assert purge_expired_kyc_files() == 0
        assert tc.get(f'/api/kyc/photo/{token}/doc').status_code == 200

    def test_abandoned_request_purged_by_creation_date(self, tc, anon):
        """Клиент залил документы и пропал — они тоже не должны лежать вечно."""
        token = make_token(tc)
        submit(anon, token)

        s = get_session()
        try:
            kyc = s.query(KycRequest).filter_by(token=token).one()
            kyc.created_at = datetime.utcnow() - timedelta(days=400)
            s.commit()
        finally:
            s.close()

        assert purge_expired_kyc_files() == 1

    def test_manual_purge_endpoint(self, tc, anon):
        """Клиент попросил удалить персональные данные — стираем досрочно."""
        token = make_token(tc)
        submit(anon, token)

        resp = tc.delete(f'/api/kyc/files/{token}')
        assert resp.status_code == 200
        assert resp.get_json()['removed'] == 4

        review = tc.get(f'/api/kyc/review/{token}').get_json()['kyc']
        assert review['has_doc'] is False
        assert review['files_purged_at']
