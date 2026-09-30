import os
import sys
import asyncio
import tempfile
import time
from datetime import datetime, timezone

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
except ImportError:
    pass

URL_FILE = "/data/tg_qr_url.txt"
STATUS_FILE = "/data/tg_qr_status.txt"

def write_atomic(filepath, content, mode=0o600):
    dir_path = os.path.dirname(filepath)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=dir_path)
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    os.chmod(temp_path, mode)
    os.replace(temp_path, filepath)

def write_status(status):
    write_atomic(STATUS_FILE, status, 0o644)
    print(f"Status updated: {status}")

async def _check_account_phone(client):
    expected_phone = os.environ.get("SYNC_TG_EXPECTED_PHONE_ELIZAVETA")
    if expected_phone:
        expected_digits = ''.join(filter(str.isdigit, expected_phone))
        if expected_digits:
            me = await client.get_me()
            if me and me.phone:
                actual_digits = ''.join(filter(str.isdigit, me.phone))
                if actual_digits != expected_digits:
                    print("Phone mismatch. Logging out.")
                    await client.log_out()
                    write_status("wrong_account")
                    return False
    return True

async def main():
    api_id = os.environ.get("SYNC_TG_API_ID_ELIZAVETA")
    api_hash = os.environ.get("SYNC_TG_API_HASH_ELIZAVETA")
    session_file = os.environ.get("SYNC_TG_SESSION_FILE_ELIZAVETA", "/data/elizaveta.session")

    if not api_id or not api_hash:
        write_status("error: SYNC_TG_API_ID_ELIZAVETA or SYNC_TG_API_HASH_ELIZAVETA missing")
        return

    write_status("waiting")

    client = TelegramClient(session_file, int(api_id), api_hash)
    await client.connect()

    try:
        if await client.is_user_authorized():
            if await _check_account_phone(client):
                write_status("authorized")
            if os.path.exists(URL_FILE):
                os.remove(URL_FILE)
            return

        qr = await client.qr_login()
        
        while True:
            write_atomic(URL_FILE, qr.url, 0o600)
            
            # Use qr.expires to calculate timeout with a 2-second buffer before expiry
            # Telethon qr.expires is a timezone-aware datetime in UTC
            now = datetime.now(timezone.utc)
            timeout = (qr.expires - now).total_seconds()
            timeout = max(1.0, timeout - 2.0)
            
            try:
                user = await qr.wait(timeout=timeout)
                if await _check_account_phone(client):
                    write_status("authorized")
                if os.path.exists(URL_FILE):
                    os.remove(URL_FILE)
                break
                
            except asyncio.TimeoutError:
                # Token is about to expire, recreate it
                await qr.recreate()
                
            except SessionPasswordNeededError:
                # If 2FA is needed, check if password is provided via env
                pwd = os.environ.get("SYNC_TG_2FA_PASSWORD_ELIZAVETA")
                if pwd:
                    await client.sign_in(password=pwd)
                    if await _check_account_phone(client):
                        write_status("authorized")
                    if os.path.exists(URL_FILE):
                        os.remove(URL_FILE)
                    break
                else:
                    write_status("2fa_required")
                    if os.path.exists(URL_FILE):
                        os.remove(URL_FILE)
                    break
            except Exception as e:
                import traceback
                traceback.print_exc()
                write_status("error")
                if os.path.exists(URL_FILE):
                    os.remove(URL_FILE)
                break

    finally:
        await client.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
