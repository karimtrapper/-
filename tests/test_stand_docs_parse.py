# -*- coding: utf-8 -*-
"""/api/docs/parse на стенде (STAND_MODE=1): включено ключом STAND_DOCPARSE_KEY,
идёт только через stand_egress.docparse_post, ошибки — стабильные коды без
имени файла и текста исключения. Сетевой уровень канала (host/path/key/
редиректы/размер ответа) проверен отдельно, в субпроцессах, в
tests/test_stand_egress.py — здесь docparse_post подменяется мок-функцией,
как и tg_call в tests/test_stand_dm.py.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_stand_docs_parse.py -v
"""
import io
import json

import pytest

import app as appmod
import docparse
import stand_egress


@pytest.fixture
def stand(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('STAND_DOCPARSE_KEY', 'fake-stand-docparse-key')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fake-prod-key-never-used-on-stand')
    with appmod.app.test_client() as client:
        db = appmod.get_session()
        try:
            user = db.query(appmod.AdminUser).filter_by(username='stand_docparse_test').first()
            if not user:
                user = appmod.AdminUser(username='stand_docparse_test', role='operator',
                                        password_hash=appmod.AdminUser.hash_password('test'))
                db.add(user); db.commit()
            uid = user.id
        finally:
            db.close()
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        yield client


PASSPORT_PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
INVOICE_PNG = b'\x89PNG\r\n\x1a\n' + b'1' * 32

FAKE_FIELDS = {'client_name_ru': 'Тестов Иван', 'client_passport_no': '77 1234567'}


def _fake_choice(fields):
    payload = dict({k: None for k in docparse.FIELD_DEFS}, **fields)
    payload['doc_kind'] = None
    payload['masked_fields'] = []
    return {'choices': [{'message': {'content': json.dumps(payload, ensure_ascii=False)}}]}


def test_parse_disabled_without_stand_key(stand, monkeypatch):
    monkeypatch.delenv('STAND_DOCPARSE_KEY', raising=False)
    r = stand.post('/api/docs/parse', data={
        'passport': (io.BytesIO(PASSPORT_PNG), 'p.png')}, content_type='multipart/form-data')
    assert r.status_code == 403
    assert r.get_json()['error'] == 'stand_blocked'


def test_parse_requires_session(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('STAND_DOCPARSE_KEY', 'fake-stand-docparse-key')
    with appmod.app.test_client() as client:
        r = client.post('/api/docs/parse', data={
            'passport': (io.BytesIO(PASSPORT_PNG), 'p.png')}, content_type='multipart/form-data')
    assert r.status_code == 401


def test_successful_parse_goes_through_docparse_post_only(stand, monkeypatch):
    calls = []

    def fake_post(payload, timeout=60):
        calls.append(payload)
        assert payload['model'] in [docparse.DEFAULT_MODEL] + docparse.FALLBACK_MODELS
        assert set(payload.keys()) <= {'model', 'messages', 'response_format', 'max_tokens', 'temperature'}
        return 200, _fake_choice(FAKE_FIELDS), None

    monkeypatch.setattr(stand_egress, 'docparse_post', fake_post)
    r = stand.post('/api/docs/parse', data={
        'passport': (io.BytesIO(PASSPORT_PNG), 'passport.png')}, content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body['fields']['client_passport_no'] == '77 1234567'
    assert body['fields']['client_name_ru'] == 'Тестов Иван'
    assert len(calls) == 1


def test_openai_sdk_never_imported_on_stand_path(stand, monkeypatch):
    """Прод-путь использует OpenAI SDK; на стенде это исключено — только канал."""
    def boom(*a, **k):
        raise AssertionError('OpenAI SDK не должен вызываться на стенде')
    monkeypatch.setattr(stand_egress, 'docparse_post', lambda payload, timeout=60: (200, _fake_choice(FAKE_FIELDS), None))
    import sys
    monkeypatch.setitem(sys.modules, 'openai', None)  # импорт openai уронит тест, если код туда полезет
    r = stand.post('/api/docs/parse', data={
        'passport': (io.BytesIO(PASSPORT_PNG), 'passport.png')}, content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()


@pytest.mark.parametrize('err_code', ['no_key', 'network_error', 'timeout', 'too_large',
                                      'bad_json', 'invalid_payload', 'http_error'])
def test_errors_are_stable_codes_without_filename_or_exception_text(stand, monkeypatch, err_code, caplog):
    def fake_post(payload, timeout=60):
        if err_code == 'http_error':
            return 503, {'error': 'upstream secret detail should never leak'}, None
        return None, None, err_code

    caplog.set_level('WARNING')
    monkeypatch.setattr(stand_egress, 'docparse_post', fake_post)
    filename = 'super-secret-client-passport-ivanov.png'
    r = stand.post('/api/docs/parse', data={
        'passport': (io.BytesIO(PASSPORT_PNG), filename)}, content_type='multipart/form-data')
    assert r.status_code == 502, r.get_json()
    body = r.get_json()
    assert len(body['failed']) == 1
    entry = body['failed'][0]
    assert 'file' not in entry
    assert entry['slot'] == 'passport'
    assert entry['error'] == err_code
    dumped = json.dumps(body)
    assert filename not in dumped
    assert 'fake-stand-docparse-key' not in dumped
    for record in caplog.records:
        assert filename not in record.getMessage()
        assert 'fake-stand-docparse-key' not in record.getMessage()


def test_too_many_files_rejected_before_network(stand, monkeypatch):
    def unexpected(*a, **k):
        pytest.fail('Сеть не должна вызываться при превышении лимита файлов')
    monkeypatch.setattr(stand_egress, 'docparse_post', unexpected)
    # Больше одного файла в слоте — так же считается сверх бюджета: лимит на
    # ВСЕ загруженные файлы стенда, а не на количество слотов.
    r = stand.post('/api/docs/parse', data={
        'passport': [(io.BytesIO(PASSPORT_PNG), 'p1.png'), (io.BytesIO(PASSPORT_PNG), 'p2.png')],
        'invoice': (io.BytesIO(INVOICE_PNG), 'i1.png'),
        'spa': (io.BytesIO(PASSPORT_PNG), 's1.png'),
    }, content_type='multipart/form-data')
    assert r.status_code == 400
    assert r.get_json()['error'] == 'too_many_files'


def test_generic_files_field_ignored_on_stand(stand, monkeypatch):
    """На стенде принимаются только именованные слоты — общее поле files не идёт в парсер."""
    calls = []
    monkeypatch.setattr(stand_egress, 'docparse_post',
                        lambda payload, timeout=60: (calls.append(1), (200, _fake_choice(FAKE_FIELDS), None))[1])
    r = stand.post('/api/docs/parse', data={
        'files': (io.BytesIO(PASSPORT_PNG), 'anonymous.png'),
    }, content_type='multipart/form-data')
    assert r.status_code == 400
    assert r.get_json()['error'] == 'no_files'
    assert not calls


def test_oversized_raster_rejected_before_network(stand, monkeypatch):
    def unexpected(*a, **k):
        pytest.fail('Сеть не должна вызываться при превышении растрового бюджета')
    monkeypatch.setattr(stand_egress, 'docparse_post', unexpected)
    huge = b'\x89PNG\r\n\x1a\n' + b'x' * (docparse.STAND_MAX_RASTER_BYTES + 1)
    monkeypatch.setattr(docparse, 'pages_to_png', lambda data, mime, **k: [huge])
    r = stand.post('/api/docs/parse', data={
        'passport': (io.BytesIO(b'fake'), 'p.png')}, content_type='multipart/form-data')
    assert r.status_code == 502, r.get_json()
    assert r.get_json()['failed'][0]['error'] == 'too_large'


def test_prod_path_unchanged_when_stand_mode_off(monkeypatch):
    """STAND_MODE=0 — тот же SDK-путь, что в origin/main: docparse_post не трогается."""
    monkeypatch.setattr(appmod, 'STAND_MODE', False)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setenv('OPENROUTER_API_KEY', 'fake-prod-key')

    def unexpected(*a, **k):
        pytest.fail('Прод-путь не должен использовать stand_egress.docparse_post')
    monkeypatch.setattr(stand_egress, 'docparse_post', unexpected)

    calls = []
    content = _fake_choice(FAKE_FIELDS)['choices'][0]['message']['content']

    class FakeMessage:
        content_ = content

        def __init__(self):
            self.content = content

    class FakeChoice:
        def __init__(self):
            self.message = FakeMessage()

    class FakeResp:
        def __init__(self):
            self.choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    import openai
    monkeypatch.setattr(openai, 'OpenAI', FakeOpenAI)

    with appmod.app.test_client() as client:
        r = client.post('/api/docs/parse', data={
            'passport': (io.BytesIO(PASSPORT_PNG), 'passport.png')}, content_type='multipart/form-data')
    assert r.status_code == 200, r.get_json()
    assert calls, 'прод-путь должен был вызвать OpenAI SDK'
