import os
import sys
import sqlite3
import json
import tempfile
import urllib.request
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ChannelsWorker'))
import sync_channels_to_stand as s

def test_wa_sqlite_sync(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        c = conn.cursor()
        c.execute("CREATE TABLE chats (jid TEXT, name TEXT, last_message_time INTEGER)")
        c.execute("INSERT INTO chats VALUES ('123@s.whatsapp.net', 'Test Chat', '2023-11-14T22:13:20Z')")
        c.execute("INSERT INTO chats VALUES ('456@s.whatsapp.net', NULL, NULL)")
        conn.commit()
        conn.close()

        monkeypatch.setenv("STAND_CHANNEL_SYNC_KEY", "secret")

        with patch("sync_channels_to_stand.urllib.request.urlopen") as mock_urlopen:
            mock_res = MagicMock()
            mock_res.read.return_value = b'{"success": true}'
            mock_urlopen.return_value.__enter__.return_value = mock_res
            
            s.sync_whatsapp("Елизавета", path, None)
            
            assert mock_urlopen.called
            req = mock_urlopen.call_args[0][0]
            payload = json.loads(mock_urlopen.call_args[1].get('data', mock_urlopen.call_args[0][1] if len(mock_urlopen.call_args[0]) > 1 else b'').decode('utf-8'))
            
            assert payload["channel"] == "wa"
            assert payload["account"] == "Елизавета"
            assert len(payload["chats"]) == 2
            assert payload["chats"][0]["id"] == "123@s.whatsapp.net"
            assert payload["chats"][0]["name"] == "Test Chat"
            assert payload["chats"][0]["last_active"] == 1700000000
            
            # Nulls fallback
            assert payload["chats"][1]["id"] == "456@s.whatsapp.net"
            assert payload["chats"][1]["name"] == "456@s.whatsapp.net"
            assert payload["chats"][1]["last_active"] == 0
    finally:
        os.unlink(path)

def test_bitrix_sync_pagination_and_date(monkeypatch):
    monkeypatch.setenv("SYNC_BITRIX_WEBHOOK", "https://test.bitrix")
    monkeypatch.setenv("STAND_CHANNEL_SYNC_KEY", "secret")
    
    responses = [
        # Page 1
        json.dumps({
            "result": [
                {"ID": "100", "TITLE": "Deal 1", "DATE_MODIFY": "2026-09-30T10:00:00Z"},
                {"ID": "101", "TITLE": "", "DATE_MODIFY": None}
            ],
            "next": 2
        }).encode('utf-8'),
        # Page 2
        json.dumps({
            "result": [
                {"ID": "102", "TITLE": "Deal 2", "DATE_MODIFY": "2026-09-29T10:00:00Z"}
            ]
        }).encode('utf-8')
    ]
    
    with patch("sync_channels_to_stand.urllib.request.urlopen") as mock_urlopen:
        mock_res1 = MagicMock()
        mock_res1.read.return_value = responses[0]
        mock_res2 = MagicMock()
        mock_res2.read.return_value = responses[1]
        
        # Third call is to the sync endpoint
        mock_res3 = MagicMock()
        mock_res3.read.return_value = b'{"success": true}'
        
        mock_urlopen.side_effect = [
            MagicMock(__enter__=lambda _: mock_res1),
            MagicMock(__enter__=lambda _: mock_res2),
            MagicMock(__enter__=lambda _: mock_res3)
        ]
        
        s.sync_bitrix()
        
        assert mock_urlopen.call_count == 3
        # First call Bitrix page 1
        req1 = mock_urlopen.call_args_list[0][0][0]
        req1_data = json.loads(mock_urlopen.call_args_list[0][1].get('data', mock_urlopen.call_args_list[0][0][1] if len(mock_urlopen.call_args_list[0][0]) > 1 else b'').decode('utf-8'))
        assert req1_data["filter"] == {"CATEGORY_ID": 0, "!=STAGE_ID": ["WON", "LOSE"]}
        assert req1_data["start"] == 0
        
        # Second call Bitrix page 2
        req2 = mock_urlopen.call_args_list[1][0][0]
        req2_data = json.loads(mock_urlopen.call_args_list[1][1].get('data', mock_urlopen.call_args_list[1][0][1] if len(mock_urlopen.call_args_list[1][0]) > 1 else b'').decode('utf-8'))
        assert req2_data["start"] == 2
        
        # Third call Stand Sync
        req3 = mock_urlopen.call_args_list[2][0][0]
        payload = json.loads(mock_urlopen.call_args_list[2][1].get('data', mock_urlopen.call_args_list[2][0][1] if len(mock_urlopen.call_args_list[2][0]) > 1 else b'').decode('utf-8'))
        assert len(payload["chats"]) == 3
        assert payload["chats"][0]["id"] == "100"
        assert payload["chats"][0]["last_active"] > 0
        
        # Unknown dates should be at the bottom
        assert payload["chats"][2]["id"] == "101"
        assert payload["chats"][2]["last_active"] == 0
        assert payload["chats"][2]["name"] == "Сделка 101"

import pytest

def test_elizaveta_blocker(monkeypatch, capsys):
    s.STAND_CHANNEL_SYNC_KEY = "secret"
    monkeypatch.setenv("STAND_CHANNEL_SYNC_KEY", "secret")
    monkeypatch.delenv("SYNC_TG_SESSION_FILE_ELIZAVETA", raising=False)
    monkeypatch.delenv("SYNC_WA_DB_PATH_ELIZAVETA", raising=False)
    monkeypatch.delenv("SYNC_WA_API_URL_ELIZAVETA", raising=False)
    monkeypatch.setenv("SYNC_BITRIX_WEBHOOK", "https://test.bitrix")
    
    from unittest.mock import patch
    with patch("sync_channels_to_stand.sync_bitrix") as mock_bitrix:
        ready = s.main()
        assert not ready
        assert mock_bitrix.called
        
        captured = capsys.readouterr().out
        assert "[PENDING] Telegram session file NOT CONFIGURED for Елизавета" in captured
        assert "[PENDING] WhatsApp DB/API NOT CONFIGURED for Елизавета" in captured
        assert "БЛОКЕР СИНХРОНИЗАЦИИ:" in captured

def test_independent_channels_sync(monkeypatch, capsys):
    # Test that one unconfigured channel does not block the other from syncing
    import tempfile
    s.STAND_CHANNEL_SYNC_KEY = "secret"
    monkeypatch.setenv("STAND_CHANNEL_SYNC_KEY", "secret")
    
    # Missing TG
    monkeypatch.delenv("SYNC_TG_SESSION_FILE_ELIZAVETA", raising=False)
    
    # Valid WA
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import sqlite3
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute("CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP)")
    conn.commit()
    conn.close()
    
    monkeypatch.setenv("SYNC_WA_DB_PATH_ELIZAVETA", path)
    s.ACCOUNTS[1]['wa_db_path'] = path
    s.ACCOUNTS[1]['tg_session_file'] = None
    
    # Valid Bitrix
    monkeypatch.setenv("SYNC_BITRIX_WEBHOOK", "https://test.bitrix")
    
    from unittest.mock import patch, MagicMock
    with patch("sync_channels_to_stand.urllib.request.urlopen") as mock_urlopen:
        mock_res = MagicMock()
        mock_res.read.return_value = b'{"success": True, "result": []}'
        mock_urlopen.return_value.__enter__.return_value = mock_res
        
        ready = s.main()
        
        assert not ready # Overall readiness is still False because TG is missing
        
        captured = capsys.readouterr().out
        assert "[PENDING] Telegram session file NOT CONFIGURED for Елизавета" in captured
        # It should have successfully fetched WA and Bitrix despite TG missing
        assert "Fetching WhatsApp chats from local DB for Елизавета..." in captured
        assert "Fetching Bitrix active deals..." in captured
    os.unlink(path)

def test_channels_sync_auth_stand(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod.Base.metadata.create_all(appmod.engine, tables=[appmod.StandChannel.__table__])
    monkeypatch.setenv('STAND_CHANNEL_SYNC_KEY', 'correct-key')
    
    with appmod.app.test_client() as c:
        # 1. No Bearer -> 401
        res = c.post('/api/stand/channels/sync', json={"channel": "tg", "account": "Елизавета", "chats": []})
        assert res.status_code == 401
        
        # 2. Bad Bearer -> 401
        res = c.post('/api/stand/channels/sync', 
                     headers={"Authorization": "Bearer bad-key"},
                     json={"channel": "tg", "account": "Елизавета", "chats": []})
        assert res.status_code == 401
        
        # 3. Valid Bearer -> 200
        res = c.post('/api/stand/channels/sync', 
                     headers={"Authorization": "Bearer correct-key"},
                     json={"channel": "tg", "account": "Елизавета", "chats": []})
        assert res.status_code == 200
        assert res.get_json()['success'] is True


def test_channels_sync_prod_404(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', False)
    
    with appmod.app.test_client() as c:
        monkeypatch.setenv('SERVICE_API_KEY', 'my-service-key')
        res = c.post('/api/stand/channels/sync', 
                     headers={'X-Api-Key': 'my-service-key'},
                     json={})
        assert res.status_code == 404
        assert res.get_json()['error'] == 'stand_only'


def test_sync_deletion(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod.Base.metadata.create_all(appmod.engine, tables=[appmod.StandChannel.__table__])
    appmod.os.environ['STAND_CHANNEL_SYNC_KEY'] = 'correct-key'

    db = appmod.get_session()
    try:
        u = db.query(appmod.AdminUser).first()
        if not u:
            u = appmod.AdminUser(username='tester', display_name='Tester', role='manager', password_hash='dummy')
            db.add(u)
            db.commit()
        uid = u.id
    finally:
        db.close()

    with appmod.app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = uid

        res = c.post('/api/stand/channels/sync',
                     headers={"Authorization": "Bearer correct-key"},
                     json={
                         "channel": "tg",
                         "account": "Елизавета",
                         "chats": [
                             {"id": "c1", "name": "Chat 1", "last_active": 1},
                             {"id": "c2", "name": "Chat 2", "last_active": 2}
                         ]
                     })
        assert res.status_code == 200

        res_get = c.get('/api/stand/channels')
        assert res_get.status_code == 200, res_get.get_json()
        assert len(res_get.get_json()['data']['tg']) == 2

        res2 = c.post('/api/stand/channels/sync',
                      headers={"Authorization": "Bearer correct-key"},
                      json={
                          "channel": "tg",
                          "account": "Елизавета",
                          "chats": [
                              {"id": "c2", "name": "Chat 2 (updated)", "last_active": 3}
                          ]
                      })
        assert res2.status_code == 200

        res_get2 = c.get('/api/stand/channels')
        tg_chats = res_get2.get_json()['data']['tg']
        assert len(tg_chats) == 1
        assert tg_chats[0]['id'] == "c2"

        # Third sync: 0 chats
        res3 = c.post('/api/stand/channels/sync',
                      headers={"Authorization": "Bearer correct-key"},
                      json={
                          "channel": "tg",
                          "account": "Елизавета",
                          "chats": []
                      })
        assert res3.status_code == 200

        # Verify 0 chats exist
        res_get3 = c.get('/api/stand/channels')
        # "tg" might be missing completely or be an empty list depending on the endpoint logic
        tg_data = res_get3.get_json()['data'].get('tg', [])
        assert len(tg_data) == 0
