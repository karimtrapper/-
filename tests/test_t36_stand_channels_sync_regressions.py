import os
import sys
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ChannelsWorker'))
import sync_channels_to_stand as s

def test_bitrix_invalid_credentials_error(monkeypatch):
    monkeypatch.setenv("SYNC_BITRIX_WEBHOOK", "https://test.bitrix")
    monkeypatch.setenv("STAND_CHANNEL_SYNC_KEY", "secret")
    
    with patch("sync_channels_to_stand.urllib.request.urlopen") as mock_urlopen:
        mock_res = MagicMock()
        mock_res.read.return_value = b'{"error": "INVALID_CREDENTIALS", "error_description": "Invalid request credentials"}'
        mock_urlopen.return_value.__enter__.return_value = mock_res
        
        # Calling bitrix sync shouldn't push an empty list, it should raise and handle the exception internally without pushing empty list to API.
        with patch("sync_channels_to_stand.push_to_stand") as mock_push:
            s.sync_bitrix()
            assert not mock_push.called

def test_app_sync_exception_handling(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod.os.environ['STAND_CHANNEL_SYNC_KEY'] = 'correct-key'

    with patch("app.get_session") as mock_get_session:
        # Cause an exception during db operation
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("Database failure")
        mock_get_session.return_value = mock_db

        with appmod.app.test_client() as c:
            res = c.post('/api/stand/channels/sync',
                         headers={"Authorization": "Bearer correct-key"},
                         json={
                             "channel": "tg",
                             "account": "Елизавета",
                             "chats": [
                                 {"id": "c1", "name": "Chat 1", "last_active": 1}
                             ]
                         })
            assert res.status_code == 500
            data = res.get_json()
            assert data['success'] is False
            assert data['error'] == 'server_error'
            assert 'Database failure' not in str(data)

def test_wa_chunking_sync(monkeypatch):
    monkeypatch.setenv("STAND_CHANNEL_SYNC_KEY", "secret")
    chats = [{"id": str(i), "name": f"Chat {i}", "last_active": 0} for i in range(5001)]
    
    with patch("sync_channels_to_stand.urllib.request.urlopen") as mock_urlopen:
        mock_res = MagicMock()
        mock_res.read.return_value = b'{"success": true}'
        mock_urlopen.return_value.__enter__.return_value = mock_res
        
        s.push_to_stand("wa", "Елизавета", chats)
        
        assert mock_urlopen.call_count == 2
        
        call1 = mock_urlopen.call_args_list[0]
        req1_data = json.loads(call1[1].get('data', call1[0][1] if len(call1[0]) > 1 else b'').decode('utf-8'))
        assert len(req1_data['chats']) == 4000
        assert req1_data['is_last'] is False
        assert req1_data['sync_tag'] is not None

        call2 = mock_urlopen.call_args_list[1]
        req2_data = json.loads(call2[1].get('data', call2[0][1] if len(call2[0]) > 1 else b'').decode('utf-8'))
        assert len(req2_data['chats']) == 1001
        assert req2_data['is_last'] is True
        assert req2_data['sync_tag'] == req1_data['sync_tag']

def test_sync_stale_deletion_null_tags(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod.Base.metadata.create_all(appmod.engine, tables=[appmod.StandChannel.__table__])
    appmod.os.environ['STAND_CHANNEL_SYNC_KEY'] = 'correct-key'

    db = appmod.get_session()
    try:
        # Create an old record with NULL sync_tag
        old_chat = appmod.StandChannel(
            channel="tg",
            account="Елизавета",
            chat_id="stale_chat",
            name="Stale Chat",
            last_active=0,
            sync_tag=None
        )
        db.add(old_chat)
        db.commit()
    finally:
        db.close()

    with appmod.app.test_client() as c:
        # Perform sync with a new tag
        res = c.post('/api/stand/channels/sync',
                     headers={"Authorization": "Bearer correct-key"},
                     json={
                         "channel": "tg",
                         "account": "Елизавета",
                         "chats": [
                             {"id": "new_chat", "name": "New Chat", "last_active": 1}
                         ],
                         "sync_tag": "new_tag",
                         "is_last": True
                     })
        assert res.status_code == 200

        # Verify old record with NULL tag was deleted
        db2 = appmod.get_session()
        try:
            records = db2.query(appmod.StandChannel).all()
            assert len(records) == 1
            assert records[0].chat_id == "new_chat"
        finally:
            db2.close()

def test_sync_rapid_sequential(monkeypatch):
    # Verify that two sequential syncs generate different tags using uuid instead of time.time
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod.Base.metadata.create_all(appmod.engine, tables=[appmod.StandChannel.__table__])
    monkeypatch.setenv("STAND_CHANNEL_SYNC_KEY", "secret")

    tags = []
    
    with patch("sync_channels_to_stand.urllib.request.urlopen") as mock_urlopen:
        mock_res = MagicMock()
        mock_res.read.return_value = b'{"success": true}'
        mock_urlopen.return_value.__enter__.return_value = mock_res
        
        # Simulate two rapid sequential syncs
        s.push_to_stand("wa", "Елизавета", [{"id": "c1"}])
        s.push_to_stand("wa", "Елизавета", [{"id": "c2"}])
        
        call1 = mock_urlopen.call_args_list[0]
        req1_data = json.loads(call1[1].get('data', call1[0][1] if len(call1[0]) > 1 else b'').decode('utf-8'))
        
        call2 = mock_urlopen.call_args_list[1]
        req2_data = json.loads(call2[1].get('data', call2[0][1] if len(call2[0]) > 1 else b'').decode('utf-8'))
        
        assert req1_data['sync_tag'] != req2_data['sync_tag']

def test_sync_overlapping_id_flush(monkeypatch):
    import app as appmod
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod.Base.metadata.create_all(appmod.engine, tables=[appmod.StandChannel.__table__])
    appmod.os.environ['STAND_CHANNEL_SYNC_KEY'] = 'correct-key'

    db = appmod.get_session()
    try:
        # Pre-seed other channel to make sure it's not affected
        other = appmod.StandChannel(
            channel="wa", account="Елизавета", chat_id="other_c1", name="Other", sync_tag="111"
        )
        db.add(other)
        db.commit()
    finally:
        db.close()

    with appmod.app.test_client() as c:
        # 1st sync
        res1 = c.post('/api/stand/channels/sync', headers={"Authorization": "Bearer correct-key"},
                      json={"channel": "tg", "account": "Елизавета", 
                            "chats": [{"id": "c1", "name": "Old Name", "last_active": 1},
                                      {"id": "c2", "name": "To be deleted", "last_active": 2}],
                            "sync_tag": "tag1", "is_last": True})
        assert res1.status_code == 200

        # 2nd sync: updates c1 (rename), c2 is absent (should be deleted), c3 is new
        res2 = c.post('/api/stand/channels/sync', headers={"Authorization": "Bearer correct-key"},
                      json={"channel": "tg", "account": "Елизавета", 
                            "chats": [{"id": "c1", "name": "New Name", "last_active": 1},
                                      {"id": "c3", "name": "New Chat", "last_active": 3}],
                            "sync_tag": "tag2", "is_last": True})
        assert res2.status_code == 200

        # 3rd sync: rapid sequential cycle
        res3 = c.post('/api/stand/channels/sync', headers={"Authorization": "Bearer correct-key"},
                      json={"channel": "tg", "account": "Елизавета", 
                            "chats": [{"id": "c1", "name": "Final Name", "last_active": 1}],
                            "sync_tag": "tag3", "is_last": True})
        assert res3.status_code == 200

        db = appmod.get_session()
        try:
            tg_records = db.query(appmod.StandChannel).filter_by(channel="tg").all()
            assert len(tg_records) == 1
            assert tg_records[0].chat_id == "c1"
            assert tg_records[0].name == "Final Name"
            assert tg_records[0].sync_tag == "tag3"

            wa_records = db.query(appmod.StandChannel).filter_by(channel="wa").all()
            assert len(wa_records) == 1
            assert wa_records[0].chat_id == "other_c1"
        finally:
            db.close()
