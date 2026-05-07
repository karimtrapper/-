"""
Скрипт импорта исторических сделок (дек 2025 / янв 2026 / фев 2026).
Использует skip_sync=true чтобы НЕ триггерить GSheet sync и Telegram.
"""

import requests
import json
import sys

BASE_URL = "https://proud-renewal-production-e9b8.up.railway.app"

# Февраль 2026 — из таблицы "общая сделка"
FEBRUARY_DEALS = [
    {"id": 68, "client_name": "Андрей (друг Теда)", "created_at": "2026-02-01", "payin_amount_usdt": 1910, "profit_usdt": 90},
    {"id": 70, "client_name": "Эдик", "created_at": "2026-02-01", "payin_amount_usdt": 1678, "profit_usdt": 89},
    {"id": 71, "client_name": "Егор", "created_at": "2026-02-02", "payin_amount_usdt": 8368, "profit_usdt": 419},
    {"id": 69, "client_name": "Андрей Зайцев", "created_at": "2026-02-04", "payin_amount_usdt": 501, "profit_usdt": 12},
    {"id": 83, "client_name": "Dynch Gagarin", "created_at": "2026-02-05", "payin_amount_usdt": 2334, "profit_usdt": 109},
    {"id": 73, "client_name": "Егор", "created_at": "2026-02-06", "payin_amount_usdt": 4099, "profit_usdt": 61},
    {"id": 74, "client_name": "Валера", "created_at": "2026-02-06", "payin_amount_usdt": 3213, "profit_usdt": 47},
    {"id": 75, "client_name": "Оля", "created_at": "2026-02-06", "payin_amount_usdt": 504, "profit_usdt": 25},
    {"id": 81, "client_name": "Artem Malanin", "created_at": "2026-02-09", "payin_amount_usdt": 1249, "profit_usdt": 49},
    {"id": 76, "client_name": "Андроник", "created_at": "2026-02-12", "payin_amount_usdt": 136, "profit_usdt": 7},
    {"id": 77, "client_name": "Даниил", "created_at": "2026-02-12", "payin_amount_usdt": 1210, "profit_usdt": 19},
    {"id": 78, "client_name": "Андроник (гидроскутер)", "created_at": "2026-02-12", "payin_amount_usdt": 10598, "profit_usdt": 596},
    {"id": 79, "client_name": "Андрей (друг теда)", "created_at": "2026-02-12", "payin_amount_usdt": 2261, "profit_usdt": 34},
    {"id": 87, "client_name": "Андрей Зайцев", "created_at": "2026-02-13", "payin_amount_usdt": 500, "profit_usdt": 8},
    {"id": 88, "client_name": "Лисианский", "created_at": "2026-02-14", "payin_amount_usdt": 9533, "profit_usdt": 490},
    {"id": 91, "client_name": "Андроник", "created_at": "2026-02-19", "payin_amount_usdt": 424, "profit_usdt": 22},
    {"id": 93, "client_name": "Валера ли", "created_at": "2026-02-19", "payin_amount_usdt": 524, "profit_usdt": 19},
    {"id": 96, "client_name": "Расход андронику", "created_at": "2026-02-19", "payin_amount_usdt": 0, "profit_usdt": -225},
    {"id": 98, "client_name": "Андроник", "created_at": "2026-02-20", "payin_amount_usdt": 841, "profit_usdt": 45},
    {"id": 97, "client_name": "Андроник", "created_at": "2026-02-21", "payin_amount_usdt": 822, "profit_usdt": 51},
]


def import_deals(session, deals, dry_run=False):
    """Импорт сделок с skip_sync=true"""
    success = 0
    errors = []

    for d in deals:
        payload = {
            "client_name": d["client_name"],
            "created_at": d["created_at"],
            "payin_amount_usdt": d["payin_amount_usdt"],
            "profit_usdt": d["profit_usdt"],
            "status": "completed",
            "manager_name": "Карим",
            "skip_sync": True,
            "notes": f"Импорт из таблицы (#{d['id']})"
        }

        if dry_run:
            print(f"  [DRY] #{d['id']} {d['client_name']} {d['created_at']} ${d['payin_amount_usdt']} → profit ${d['profit_usdt']}")
            success += 1
            continue

        resp = session.post(f"{BASE_URL}/api/deals", json=payload)
        if resp.status_code == 201:
            result = resp.json()
            new_id = result['deal']['id']
            print(f"  ✓ #{d['id']} → CRM #{new_id} | {d['client_name']} | ${d['profit_usdt']}")
            success += 1
        else:
            print(f"  ✗ #{d['id']} {d['client_name']}: {resp.status_code} {resp.text[:100]}")
            errors.append(d['id'])

    return success, errors


def main():
    dry_run = "--dry" in sys.argv

    # Авторизация
    s = requests.Session()
    login = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "test1234"})
    if login.status_code != 200 or not login.json().get('success'):
        print(f"Ошибка авторизации: {login.text}")
        return
    print("Авторизация ✓\n")

    # Февраль
    print(f"=== Февраль 2026 ({len(FEBRUARY_DEALS)} сделок) ===")
    ok, err = import_deals(s, FEBRUARY_DEALS, dry_run=dry_run)
    print(f"\nИтог: {ok} успешно, {len(err)} ошибок")
    if err:
        print(f"Ошибки: {err}")


if __name__ == "__main__":
    main()
