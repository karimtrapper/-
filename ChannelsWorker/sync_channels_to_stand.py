#!/usr/bin/env python3
"""
Скрипт для синхронизации метаданных чатов (TG, WA, Bitrix) на тестовый стенд.
Не передаёт текст сообщений, только ID, Имя и Время активности.

Использование:
  export STAND_BASE_URL="https://grusha.up.railway.app"
  export STAND_CHANNEL_SYNC_KEY="..."

  # Для Карима:
  export SYNC_TG_API_ID_KARIM="..."
  export SYNC_TG_API_HASH_KARIM="..."

  # Для клиентского менеджера Елизаветы (ОБЯЗАТЕЛЬНО):
  # Телеграм и WhatsApp Елизаветы должны быть подключены, т.к. она общается с клиентами.
  export SYNC_TG_SESSION_FILE_ELIZAVETA="..."
  export SYNC_TG_API_ID_ELIZAVETA="..."
  export SYNC_TG_API_HASH_ELIZAVETA="..."
  export SYNC_WA_DB_PATH_ELIZAVETA="..."

  python3 sync_channels_to_stand.py
"""

import os
import time
import json
import sqlite3
import urllib.request
import asyncio
import tempfile
import shutil
from datetime import datetime

STAND_BASE_URL = os.environ.get("STAND_BASE_URL", "https://grusha-new.up.railway.app").rstrip('/')
STAND_CHANNEL_SYNC_KEY = os.environ.get("STAND_CHANNEL_SYNC_KEY", "")

ACCOUNTS = [
    {
        "name": "Карим",
        "tg_session_file": os.environ.get("SYNC_TG_SESSION_FILE_KARIM"),
        "tg_api_id": os.environ.get("SYNC_TG_API_ID_KARIM"),
        "tg_api_hash": os.environ.get("SYNC_TG_API_HASH_KARIM"),
        "wa_db_path": os.environ.get("SYNC_WA_DB_PATH_KARIM"),
        "wa_api_url": os.environ.get("SYNC_WA_API_URL_KARIM"),
        "required": False
    },
    {
        "name": "Елизавета",
        # Менеджер Елизавета обязательно должна быть подключена.
        # Шаг подключения: 
        # 1. Авторизовать Telethon session для номера Елизаветы и прописать путь в SYNC_TG_SESSION_FILE_ELIZAVETA
        # 2. Поднять WA Bridge для Елизаветы и прописать путь в SYNC_WA_DB_PATH_ELIZAVETA
        "tg_session_file": os.environ.get("SYNC_TG_SESSION_FILE_ELIZAVETA"),
        "tg_api_id": os.environ.get("SYNC_TG_API_ID_ELIZAVETA"),
        "tg_api_hash": os.environ.get("SYNC_TG_API_HASH_ELIZAVETA"),
        "wa_db_path": os.environ.get("SYNC_WA_DB_PATH_ELIZAVETA"),
        "wa_api_url": os.environ.get("SYNC_WA_API_URL_ELIZAVETA"),
        "required": True
    }
]

def push_to_stand(channel, account_name, chats):
    url = f"{STAND_BASE_URL}/api/stand/channels/sync"
    req = urllib.request.Request(url, method="POST")
    req.add_header("Authorization", f"Bearer {STAND_CHANNEL_SYNC_KEY}")
    req.add_header("Content-Type", "application/json")
    
    payload = {
        "channel": channel,
        "account": account_name,
        "chats": chats
    }
    
    try:
        with urllib.request.urlopen(req, data=json.dumps(payload).encode('utf-8')) as res:
            resp = json.loads(res.read().decode())
            print(f"[OK] Synced {len(chats)} {channel} chats for {account_name}.")
    except Exception as e:
        print(f"[ERROR] Failed to push {channel} to stand for {account_name}: {e}")
        raise

async def sync_telegram(account_name, session_file, api_id, api_hash):
    if not session_file:
        raise ValueError(f"Telegram session file NOT CONFIGURED for {account_name}. This is a hard blocker. See script docs.")
        
    session_file = os.path.expanduser(session_file)
    if not os.path.exists(session_file):
        raise ValueError(f"Telegram session file NOT FOUND for {account_name} at {session_file}. This is a hard blocker.")

    if not api_id or not api_hash:
        raise ValueError(f"API_ID/API_HASH NOT CONFIGURED for {account_name}. This is a hard blocker.")

    try:
        from telethon import TelegramClient
    except ImportError:
        print("[ERROR] Telethon not installed. pip install telethon")
        return

    print(f"Fetching Telegram dialogs for {account_name}...")
    
    fd, tmp_path = tempfile.mkstemp(suffix=".session")
    os.close(fd)
    shutil.copy2(session_file, tmp_path)
    
    try:
        client = TelegramClient(tmp_path, int(api_id), api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            print(f"[ERROR] Telegram session is not authorized for {account_name}.")
            await client.disconnect()
            raise ValueError(f"Telegram session is not authorized for {account_name}.")
        
        chats = []
        async for dialog in client.iter_dialogs():
            chats.append({
                "id": str(dialog.id),
                "name": dialog.name or str(dialog.id),
                "last_active": int(dialog.date.timestamp()) if dialog.date else 0
            })
        await client.disconnect()
        push_to_stand("tg", account_name, chats)
    finally:
        os.unlink(tmp_path)

def sync_whatsapp(account_name, db_path, api_url=None):
    if not db_path and not api_url:
        raise ValueError(f"WhatsApp DB path or API URL NOT CONFIGURED for {account_name}. This is a hard blocker.")
        
    chats = []
    if api_url:
        print(f"Fetching WhatsApp chats from API for {account_name}...")
        try:
            req = urllib.request.Request(api_url)
            with urllib.request.urlopen(req) as res:
                data = json.loads(res.read().decode())
                for c in data.get("companies", []):
                    if c.get("channel") == "WhatsApp" or c.get("phone"):
                        ts = int(c.get("last_message_time")) if c.get("last_message_time") else 0
                        chats.append({
                            "id": c.get("phone") or str(c.get("id", "")),
                            "name": c.get("name") or c.get("phone") or str(c.get("id", "")),
                            "last_active": ts
                        })
        except Exception as e:
            print(f"[ERROR] WA API sync failed for {account_name}: {e}")
            raise ValueError(f"WhatsApp API Sync failed for {account_name}: {e}")
    else:
        db_path = os.path.expanduser(db_path)
        if not os.path.exists(db_path):
            raise ValueError(f"WhatsApp DB not found for {account_name} at {db_path}. This is a hard blocker.")
        
        print(f"Fetching WhatsApp chats from local DB for {account_name}...")
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("PRAGMA table_info(chats)")
            cols = [r[1] for r in c.fetchall()]
            if 'last_message_time' in cols:
                c.execute("SELECT jid, name, last_message_time FROM chats ORDER BY last_message_time DESC LIMIT 5000")
            else:
                c.execute("SELECT jid, name, 0 FROM chats LIMIT 5000")
                
            for row in c.fetchall():
                jid, name, last_message_time = row
                ts = 0
                if last_message_time:
                    try:
                        if isinstance(last_message_time, (int, float)):
                            ts = int(last_message_time)
                        elif str(last_message_time).isdigit():
                            ts = int(last_message_time)
                        else:
                            ts = int(datetime.fromisoformat(str(last_message_time).replace('Z', '+00:00')).timestamp())
                    except Exception:
                        ts = 0
                chats.append({
                    "id": str(jid),
                    "name": str(name) if name else str(jid),
                    "last_active": ts
                })
            conn.close()
        except Exception as e:
            print(f"[ERROR] WA DB sync failed for {account_name}")
            raise ValueError(f"WhatsApp Sync failed for {account_name}: {e}")
            
    push_to_stand("wa", account_name, chats)

def _parse_bitrix_date(date_str):
    if not date_str: return 0
    try:
        return int(datetime.fromisoformat(date_str.replace('Z', '+00:00')).timestamp())
    except:
        return 0

def _get_bitrix_webhook():
    webhook = os.environ.get("SYNC_BITRIX_WEBHOOK")
    if webhook:
        return webhook
    env_path = os.environ.get("SYNC_BITRIX_ENV_PATH", "~/Desktop/untitled folder/Dev/ArbOps/.env")
    env_path = os.path.expanduser(env_path)
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("BITRIX_WEBHOOK_URL="):
                    return line.strip().split("=", 1)[1].strip("'\"")
    return None

def sync_bitrix():
    webhook = _get_bitrix_webhook()
    if not webhook:
        print("[SKIP] Bitrix (no SYNC_BITRIX_WEBHOOK or Dev/ArbOps/.env value)")
        return
    
    print("Fetching Bitrix active deals...")
    url = f"{webhook.rstrip('/')}/crm.deal.list"
    deals = []
    start = 0
    
    try:
        while True:
            payload = {
                "select": ["ID", "TITLE", "DATE_MODIFY", "STAGE_ID", "COMPANY_ID", "CONTACT_ID"],
                "order": {"DATE_MODIFY": "DESC"},
                "filter": {"CATEGORY_ID": 0, "!=STAGE_ID": ["WON", "LOSE"]},
                "start": start
            }
            req = urllib.request.Request(url, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, data=json.dumps(payload).encode('utf-8')) as res:
                resp = json.loads(res.read().decode())
                for d in resp.get("result", []):
                    ts = _parse_bitrix_date(d.get("DATE_MODIFY"))
                    deals.append({
                        "id": str(d.get("ID")),
                        "name": d.get("TITLE") or f"Сделка {d.get('ID')}",
                        "last_active": ts
                    })
                
                if "next" in resp and start < resp["next"]:
                    start = resp["next"]
                else:
                    break
                    
        deals.sort(key=lambda x: x["last_active"] or -1, reverse=True)
        push_to_stand("bitrix", "Grusha", deals)
    except Exception as e:
        print(f"[ERROR] Bitrix sync failed: HTTP/Network error")

def main():
    if not STAND_CHANNEL_SYNC_KEY:
        print("ERROR: STAND_CHANNEL_SYNC_KEY is not set!")
        return
    
    print(f"Syncing channels to {STAND_BASE_URL}")
    
    
    loop_interval = os.environ.get("SYNC_LOOP_INTERVAL")
    
    while True:
        all_ready = True
        for acc in ACCOUNTS:
            # Check TG
            try:
                if acc["required"] and not acc.get("tg_session_file"):
                    print(f"[PENDING] Telegram session file NOT CONFIGURED for {acc['name']}")
                    all_ready = False
                elif acc.get("tg_session_file"):
                    asyncio.run(sync_telegram(acc["name"], acc.get("tg_session_file"), acc.get("tg_api_id"), acc.get("tg_api_hash")))
            except Exception as e:
                print(f"[ERROR] TG sync failed for {acc['name']}: {e}")
                if acc["required"]: all_ready = False
            
            # Check WA
            try:
                if acc["required"] and not acc.get("wa_db_path") and not acc.get("wa_api_url"):
                    print(f"[PENDING] WhatsApp DB/API NOT CONFIGURED for {acc['name']}")
                    all_ready = False
                elif acc.get("wa_db_path") or acc.get("wa_api_url"):
                    sync_whatsapp(acc["name"], acc.get("wa_db_path"), acc.get("wa_api_url"))
            except Exception as e:
                print(f"[ERROR] WA sync failed for {acc['name']}: {e}")
                if acc["required"]: all_ready = False

        if not all_ready:
            print("===========================================================")
            print("БЛОКЕР СИНХРОНИЗАЦИИ:")
            print("Функционал CRM не будет работать корректно, пока клиентский")
            print("менеджер Елизавета не подключит Telegram и WhatsApp.")
            print("Один или несколько каналов всё ещё ожидают авторизации.")
            print("===========================================================")

        # Bitrix
        try:
            sync_bitrix()
        except Exception as e:
            print(f"[ERROR] Bitrix sync failed: {e}")
            
        if not loop_interval:
            return all_ready
            
        print(f"Sleeping for {loop_interval} seconds...")
        time.sleep(int(loop_interval))
if __name__ == "__main__":
    main()
