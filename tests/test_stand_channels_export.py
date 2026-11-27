"""Разовый экспорт текста переписки менеджера: воркер + эндпоинты стенда."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ChannelsWorker'))
import sync_channels_to_stand as s

KEY = 'export-key'


def _row(i, direction='in', chat_id='-100', text='привет'):
    return {'msg_id': i, 'chat_id': chat_id, 'chat_name': 'Клиент', 'chat_username': 'cl',
            'chat_type': 'private', 'direction': direction, 'sender_id': '5',
            'sender_name': 'Иван', 'date': '2026-09-01T10:00:00Z', 'text': text,
            'media_type': None, 'media_name': None, 'reply_to_id': None}


@pytest.fixture
def stand(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('STAND_CHANNEL_SYNC_KEY', KEY)
    appmod.Base.metadata.create_all(appmod.engine, tables=[appmod.ChannelExportMessage.__table__,
                                                            appmod.StandChannel.__table__])
    db = appmod.get_session()
    try:
        db.query(appmod.ChannelExportMessage).delete()
        db.commit()
    finally:
        db.close()
    return appmod


def _user(appmod, role):
    db = appmod.get_session()
    try:
        u = db.query(appmod.AdminUser).filter_by(username=f'exp_{role}').first()
        if not u:
            u = appmod.AdminUser(username=f'exp_{role}', display_name=role, role=role,
                                 password_hash='x')
            db.add(u)
            db.commit()
        return u.id
    finally:
        db.close()


def _post(c, rows, key=KEY, account='Елизавета'):
    headers = {'Authorization': f'Bearer {key}'} if key else {}
    return c.post('/api/stand/channels/export', headers=headers,
                  json={'account': account, 'messages': rows})


# ---------- стенд ----------

def test_export_post_requires_bearer(stand):
    with stand.app.test_client() as c:
        assert _post(c, [_row(1)], key=None).status_code == 401
        assert _post(c, [_row(1)], key='bad').status_code == 401
        assert _post(c, [_row(1)]).status_code == 200


def test_export_post_prod_404(stand, monkeypatch):
    monkeypatch.setattr(stand, 'STAND_MODE', False)
    with stand.app.test_client() as c:
        res = c.post('/api/stand/channels/export', json={})
        assert res.status_code in (401, 404)
        if res.status_code == 404:
            assert res.get_json()['error'] == 'stand_only'


def test_export_upsert_idempotent(stand):
    with stand.app.test_client() as c:
        assert _post(c, [_row(1), _row(2, 'out')]).get_json()['count'] == 2
        assert _post(c, [_row(2, 'out', text='правка'), _row(3)]).get_json()['count'] == 2
        data = c.get('/api/stand/channels/export',
                     headers={'Authorization': f'Bearer {KEY}'}).get_json()
    assert data['count'] == 3
    by_id = {m['msg_id']: m for m in data['messages']}
    assert by_id[2]['text'] == 'правка' and by_id[2]['direction'] == 'out'


def test_export_post_skips_bad_rows_and_validates(stand):
    with stand.app.test_client() as c:
        res = _post(c, [_row(1), {'msg_id': 'x'}, 'junk', dict(_row(2), direction='zzz')])
        assert res.get_json()['count'] == 1
        assert c.post('/api/stand/channels/export', headers={'Authorization': f'Bearer {KEY}'},
                      json={'account': 'A', 'messages': 'nope'}).status_code == 400
        assert _post(c, [_row(i) for i in range(2001)]).status_code == 400


def test_export_get_access(stand):
    admin_id = _user(stand, 'admin')
    mgr_id = _user(stand, 'manager')
    with stand.app.test_client() as c:
        _post(c, [_row(1)])
    # без сессии и без ключа
    with stand.app.test_client() as c:
        assert c.get('/api/stand/channels/export').status_code == 401
        assert c.get('/api/stand/channels/export',
                     headers={'Authorization': 'Bearer bad'}).status_code == 401
    # менеджер — нельзя
    with stand.app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = mgr_id
        assert c.get('/api/stand/channels/export').status_code == 403
    # админ по сессии — можно
    with stand.app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = admin_id
        res = c.get('/api/stand/channels/export')
        assert res.status_code == 200 and res.get_json()['count'] == 1
        assert res.headers['Cache-Control'] == 'no-store'


def test_export_get_pagination_and_account_filter(stand):
    with stand.app.test_client() as c:
        _post(c, [_row(i) for i in range(1, 6)])
        _post(c, [_row(1, chat_id='-200')], account='Карим')
        h = {'Authorization': f'Bearer {KEY}'}
        p1 = c.get('/api/stand/channels/export?account=Елизавета&limit=2', headers=h).get_json()
        assert p1['count'] == 2
        p2 = c.get(f"/api/stand/channels/export?account=Елизавета&after_id={p1['next_after_id']}",
                   headers=h).get_json()
        assert p2['count'] == 3
        assert c.get('/api/stand/channels/export?limit=abc', headers=h).status_code == 400


def test_export_text_not_in_general_channels_get(stand):
    uid = _user(stand, 'admin')
    with stand.app.test_client() as c:
        _post(c, [_row(1, text='СЕКРЕТНЫЙ ТЕКСТ')])
        with c.session_transaction() as sess:
            sess['user_id'] = uid
        body = c.get('/api/stand/channels').get_data(as_text=True)
        assert 'СЕКРЕТНЫЙ' not in body
        state = c.get('/api/stand/state')
        assert 'СЕКРЕТНЫЙ' not in state.get_data(as_text=True)


def test_export_table_is_stand_only(stand):
    assert 'channel_export_messages' in stand.STAND_ONLY_TABLES


# ---------- воркер ----------

class FakeMsg:
    def __init__(self, i, date, out=False, text='секрет', action=None, **kw):
        self.id = i
        self.date = date
        self.out = out
        self.message = text
        self.sender_id = 777 if not out else 1
        self.sender = SimpleNamespace(first_name='Пётр', last_name='К', username='pk')
        self.reply_to = SimpleNamespace(reply_to_msg_id=kw.get('reply'))if kw.get('reply') else None
        self.action = action
        self.media = kw.get('media')
        self.file = kw.get('file')
        for a in ('photo', 'voice', 'video_note', 'sticker', 'gif', 'video', 'audio',
                  'document', 'contact', 'geo', 'poll', 'web_preview'):
            setattr(self, a, kw.get(a))


def dt(day, hour=12):
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


class FakeDialog:
    def __init__(self, did, name, *, user=False, group=False, bot=False, megagroup=False,
                 is_self=False):
        self.id = did
        self.name = name
        self.date = None
        self.is_user = user
        self.is_group = group
        self.is_channel = not user and not group
        self.entity = SimpleNamespace(bot=bot, megagroup=megagroup, is_self=is_self,
                                      deleted=False, support=False, username=f'u{did}')


class FakeClient:
    def __init__(self, messages, flood_first=0):
        self.messages = messages  # chat id -> list[FakeMsg] (новые первыми)
        self.flood_first = flood_first
        self.calls = []

    async def get_me(self):
        return SimpleNamespace(id=1, first_name='Елизавета', last_name=None, username='liza')

    async def iter_messages(self, entity, **kw):
        # entity — FakeDialog.entity; ищем чат по username
        self.calls.append(entity.username)
        if self.flood_first:
            self.flood_first -= 1
            from telethon.errors import FloodWaitError
            raise FloodWaitError(request=None, capture=7)
        for m in self.messages.get(entity.username, []):
            yield m


async def _nosleep(_):
    return None


def test_export_chat_kind_filters():
    assert s.export_chat_kind(FakeDialog(1, 'a', user=True)) == 'private'
    assert s.export_chat_kind(FakeDialog(2, 'g', group=True)) == 'group'
    assert s.export_chat_kind(FakeDialog(3, 'sg', group=True, megagroup=True)) == 'supergroup'
    assert s.export_chat_kind(FakeDialog(4, 'bot', user=True, bot=True)) is None
    assert s.export_chat_kind(FakeDialog(5, 'me', user=True, is_self=True)) is None
    assert s.export_chat_kind(FakeDialog(777000, 'Telegram', user=True)) is None
    assert s.export_chat_kind(FakeDialog(6, 'channel')) is None  # broadcast


def test_export_message_row_and_media():
    me = dict(me_id=1, me_name='Лиза')
    doc = FakeMsg(5, dt(2), text='', media=True, document=True, file=SimpleNamespace(name='a.pdf'))
    row = s.export_message_row(doc, 10, 'Чат', 'cu', 'private', **me)
    assert (row['media_type'], row['media_name'], row['direction']) == ('document', 'a.pdf', 'in')
    assert row['sender_id'] == '777' and row['sender_name'] == 'Пётр К'
    assert row['date'] == '2026-09-02T12:00:00Z'
    out = s.export_message_row(FakeMsg(6, dt(2), out=True, reply=5), 10, 'Чат', None, 'group', **me)
    assert (out['direction'], out['sender_id'], out['sender_name'], out['reply_to_id']) == \
        ('out', '1', 'Лиза', 5)
    svc = FakeMsg(7, dt(2), text='', action=SimpleNamespace())
    assert s.export_message_row(svc, 10, 'Чат', None, 'group', **me)['media_type'].startswith('service:')
    voice = FakeMsg(8, dt(2), text='', media=True, voice=True)
    assert s.export_message_row(voice, 10, 'Чат', None, 'private', **me)['media_type'] == 'voice'


def test_parse_since():
    assert s.parse_export_since('2026-08-12') == datetime(2026, 8, 12, tzinfo=timezone.utc)
    assert s.parse_export_since('') is None
    assert s.parse_export_since('мусор') is None


def _run_export(client, dialogs, monkeypatch, batch=500):
    pushed = []
    monkeypatch.setattr(s, 'push_export_batch', lambda acc, msgs: pushed.append((acc, list(msgs))))
    monkeypatch.setattr(s, 'EXPORT_BATCH_SIZE', batch)
    stats = asyncio.run(s.export_telegram_history(
        client, dialogs, 'Елизавета', datetime(2026, 9, 1, tzinfo=timezone.utc), sleep=_nosleep))
    return stats, pushed


def test_export_history_counts_filters_and_no_text_in_logs(monkeypatch, capsys):
    dialogs = [FakeDialog(10, 'Клиент Иванов', user=True), FakeDialog(11, 'Бот', user=True, bot=True),
               FakeDialog(12, 'Канал'), FakeDialog(13, 'Группа', group=True)]
    client = FakeClient({
        'u10': [FakeMsg(3, dt(5), out=True), FakeMsg(2, dt(4)), FakeMsg(1, dt(3)),
                FakeMsg(0, datetime(2026, 8, 20, tzinfo=timezone.utc))],  # старее since
        'u13': [FakeMsg(9, dt(6))],
    })
    stats, pushed = _run_export(client, dialogs, monkeypatch)
    assert client.calls == ['u10', 'u13']  # бот и канал не трогали
    assert stats['chats'] == 2 and stats['messages'] == 4
    assert stats['in'] == 3 and stats['out'] == 1
    assert sum(len(m) for _, m in pushed) == 4
    out = capsys.readouterr().out
    assert 'секрет' not in out and 'Иванов' not in out and 'Группа' not in out


def test_export_history_batches(monkeypatch):
    dialogs = [FakeDialog(10, 'X', user=True)]
    client = FakeClient({'u10': [FakeMsg(i, dt(5)) for i in range(25, 0, -1)]})
    stats, pushed = _run_export(client, dialogs, monkeypatch, batch=10)
    assert [len(m) for _, m in pushed] == [10, 10, 5]
    assert stats['messages'] == 25


def test_export_history_flood_wait_retries(monkeypatch):
    pytest.importorskip('telethon')
    dialogs = [FakeDialog(10, 'X', user=True)]
    client = FakeClient({'u10': [FakeMsg(1, dt(5))]}, flood_first=2)
    stats, pushed = _run_export(client, dialogs, monkeypatch)
    assert stats['flood_waits'] == 2 and stats['messages'] == 1
    assert client.calls == ['u10'] * 3


def test_maybe_export_flag_and_marker(monkeypatch, tmp_path):
    session = str(tmp_path / 'elizaveta.session')
    calls = []

    async def fake_export(client, dialogs, account, since):
        calls.append(since)
        return {'chats': 1, 'messages': 2, 'in': 1, 'out': 1}

    monkeypatch.setattr(s, 'export_telegram_history', fake_export)
    run = lambda acc='Елизавета': asyncio.run(s.maybe_export_telegram(None, [], acc, session))

    monkeypatch.delenv('TG_EXPORT_SINCE', raising=False)
    assert run() is None and not calls  # флага нет

    monkeypatch.setenv('TG_EXPORT_SINCE', '2026-08-12')
    assert run('Карим') is None and not calls  # чужой аккаунт

    assert run()['messages'] == 2 and len(calls) == 1
    marker = tmp_path / 'tg_export_done_2026-08-12'
    assert marker.exists()
    assert run() is None and len(calls) == 1  # повторно не выполняется

    monkeypatch.setenv('TG_EXPORT_SINCE', '2026-08-13')  # новая дата = новый маркер
    assert run() is not None and len(calls) == 2


def test_maybe_export_failure_keeps_sync_alive_and_no_marker(monkeypatch, tmp_path, capsys):
    session = str(tmp_path / 'elizaveta.session')

    async def boom(*a, **k):
        raise RuntimeError('содержит секрет Иванов')

    monkeypatch.setattr(s, 'export_telegram_history', boom)
    monkeypatch.setenv('TG_EXPORT_SINCE', '2026-08-12')
    assert asyncio.run(s.maybe_export_telegram(None, [], 'Елизавета', session)) is None
    assert not (tmp_path / 'tg_export_done_2026-08-12').exists()
    assert 'Иванов' not in capsys.readouterr().out


def test_sync_telegram_runs_export_after_regular_sync(monkeypatch, tmp_path):
    """Обычный sync уходит первым, экспорт — тем же клиентом, disconnect в конце."""
    session = tmp_path / 'e.session'
    session.write_bytes(b'x')
    order = []

    class Client:
        def __init__(self, *a, **k):
            pass

        async def connect(self):
            order.append('connect')

        async def is_user_authorized(self):
            return True

        async def iter_dialogs(self):
            yield FakeDialog(10, 'X', user=True)

        async def disconnect(self):
            order.append('disconnect')

    async def fake_maybe(client, dialogs, account, session_file):
        order.append('export')

    monkeypatch.setattr(s, 'maybe_export_telegram', fake_maybe)
    monkeypatch.setattr(s, 'push_to_stand', lambda *a: order.append('push'))
    monkeypatch.setattr(s.shutil, 'copy2', lambda src, dst: None)
    import telethon
    monkeypatch.setattr(telethon, 'TelegramClient', Client)
    asyncio.run(s.sync_telegram('Елизавета', str(session), '1', 'h'))
    assert order == ['connect', 'push', 'export', 'disconnect']
