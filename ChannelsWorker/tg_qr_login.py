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

async def _check_account_phone(client, expected_digits):
    me = await client.get_me()
    
    if not me or not me.phone:
        print("Phone mismatch: no phone number returned. Logging out.")
        await client.log_out()
        write_status("wrong_account")
        return False
        
    actual_digits = ''.join(filter(str.isdigit, me.phone))
    if actual_digits != expected_digits:
        print("Phone mismatch. Logging out.")
        await client.log_out()
        write_status("wrong_account")
        return False
        
    return True

async def main():
    os.umask(0o077)
    session_file = os.environ.get("SYNC_TG_SESSION_FILE_ELIZAVETA", "/data/elizaveta.session")
    client = None

    try:
        api_id_raw = os.environ.get("SYNC_TG_API_ID_ELIZAVETA")
        api_hash = os.environ.get("SYNC_TG_API_HASH_ELIZAVETA")

        if not api_id_raw or not api_hash:
            write_status("error: SYNC_TG_API_ID_ELIZAVETA or SYNC_TG_API_HASH_ELIZAVETA missing")
            return

        expected_phone = os.environ.get("SYNC_TG_EXPECTED_PHONE_ELIZAVETA")
        if not expected_phone:
            write_status("error: SYNC_TG_EXPECTED_PHONE_ELIZAVETA missing")
            return
            
        expected_digits = ''.join(filter(str.isdigit, expected_phone))
        if len(expected_digits) < 5:
            write_status("error: SYNC_TG_EXPECTED_PHONE_ELIZAVETA is invalid")
            return

        write_status("waiting")

        api_id = int(api_id_raw)
        client = TelegramClient(session_file, api_id, api_hash)
        
        await client.connect()

        if await client.is_user_authorized():
            if await _check_account_phone(client, expected_digits):
                write_status("authorized")
            return

        qr = await client.qr_login()
        
        while True:
            write_atomic(URL_FILE, qr.url, 0o600)
            
            now = datetime.now(timezone.utc)
            timeout = (qr.expires - now).total_seconds()
            timeout = max(1.0, timeout - 2.0)
            
            try:
                user = await qr.wait(timeout=timeout)
                if await _check_account_phone(client, expected_digits):
                    write_status("authorized")
                break
                
            except asyncio.TimeoutError:
                try:
                    await qr.recreate()
                except Exception as e:
                    print(f"QR recreate failed: {type(e).__name__}")
                    write_status("error")
                    break
                
            except SessionPasswordNeededError:
                pwd = os.environ.get("SYNC_TG_2FA_PASSWORD_ELIZAVETA")
                if pwd:
                    try:
                        await client.sign_in(password=pwd)
                        if await _check_account_phone(client, expected_digits):
                            write_status("authorized")
                        break
                    except Exception as e:
                        print(f"2FA sign in failed: {type(e).__name__}")
                        write_status("error")
                        break
                else:
                    write_status("2fa_required")
                    break
            except Exception as e:
                print(f"Error during QR wait: {type(e).__name__}")
                write_status("error")
                break
    except Exception as e:
        print(f"Fatal error: {type(e).__name__}")
        write_status("error")
    finally:
        if os.path.exists(URL_FILE):
            try:
                os.remove(URL_FILE)
            except Exception:
                pass
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        for ext in ['', '-journal', '-wal', '-shm']:
            p = session_file + ext
            if os.path.exists(p):
                try:
                    os.chmod(p, 0o600)
                except Exception:
                    pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
