#!/usr/bin/env python3
"""Сид демо-реферера «Теодор» — витрина реферального кабинета.

Зачем: показывать партнёру, как выглядит кабинет — сделки, начисления, история
выплат в USDT и в батах. Все сделки и клиенты помечены `is_test=True`, поэтому в
CRM (список сделок, клиенты, дашборд, конверсия), в Google Sheets и в
TG-уведомлениях их нет. Реферер тоже `is_test` → его заявки на вывод не будят
команду и не висят в списке выплат.

Идемпотентно: повторный запуск сносит прежние демо-данные этого реферера
(заявки/сделки/клиентов) и раскладывает заново. Токен кабинета сохраняется —
ссылка на витрину не протухает.

Две витрины — русская и английская (англоязычные застройщики видят кабинет
на английском, поле `lang` реферера). Это РАЗНЫЕ рефереры с разными кодами и
токенами, поэтому ссылки можно раздавать параллельно.

Запуск:
    DATABASE_URL=postgresql://... python3 scripts/seed_demo_referrer.py
    DATABASE_URL=... python3 scripts/seed_demo_referrer.py --lang en
    DATABASE_URL=... python3 scripts/seed_demo_referrer.py --wipe   # только снести
"""
import os
import sys
import json
import secrets
from datetime import datetime, timedelta

# Фоновые потоки при импорте app не нужны
os.environ.setdefault('TRONSCAN_WARM_ENABLED', '0')
os.environ.setdefault('REESTR_SYNC_ENABLED', '0')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (  # noqa: E402
    Base, engine, get_session,
    Referrer, Client, Deal, DealAgent, PayoutRequest,
    DealType, DealStatus, PayInMethod, PayOutMethod,
)

PERCENT = 30.0          # revshare: 30% от прибыли сделки
MANAGER = 'Валера'
BASE_URL = os.environ.get('CALCCRM_URL', 'https://grusha.up.railway.app')

# Клиенты витрины. Последние двое — без сделок: приведены, но пока не обменивали
# (иначе конверсия в кабинете была бы бутафорскими 100%).
CLIENTS_RU = [
    ('Александр Ковалёв', '@a_kovalev'),
    ('Мария Тихонова', '@m_tikhonova'),
    ('Дмитрий Соколов', '@dsokolov'),
    ('Ирина Белова', '@irina_b'),
    ('Сергей Ефимов', '@sefimov'),
    ('Наталья Гринёва', '@n_grineva'),
    ('Павел Дорохов', '@pdorokhov'),
    ('Ольга Ким', '@olga_kim'),
]

# Английская витрина: имена клиентов тоже английские — реферал видит их
# замаскированными в кабинете, кириллица там выдала бы подделку.
CLIENTS_EN = [
    ('Alexander Kovalev', '@a_kovalev'),
    ('Maria Tikhonova', '@m_tikhonova'),
    ('Dmitry Sokolov', '@dsokolov'),
    ('Irina Belova', '@irina_b'),
    ('Sergey Efimov', '@sefimov'),
    ('Natalia Grineva', '@n_grineva'),
    ('Pavel Dorokhov', '@pdorokhov'),
    ('Olga Kim', '@olga_kim'),
]

# Сделки: (дней назад, индекс клиента в CLIENTS, приход ₽, приход USDT, выдача ฿, прибыль $, выплачено ли)
DEALS = [
    (75, 0,   850_000,  10_470.0,   337_000.0,  210.50, True),
    (67, 1,      None,   4_200.0,   136_000.0,   88.60, True),
    (58, 2, 1_450_000,  17_900.0,   577_000.0,  372.40, True),
    (45, 3,      None,  25_000.0,   806_000.0,  494.00, True),
    (34, 0, 3_300_000,  39_544.0, 1_274_000.0, 1336.35, True),
    (23, 4,      None,   8_600.0,   277_000.0,  198.70, True),
    (12, 2,   620_000,   7_620.0,   245_000.0,  165.20, False),
    (7,  5,      None,  52_000.0, 1_675_000.0, 1004.00, False),
    (2,  4,   980_000,  12_050.0,   388_000.0,  265.40, False),
]

# Профили витрин: русская и английская — независимые рефереры
PROFILES = {
    'ru': {
        'code': 'GR-TEODOR',
        'name': 'Теодор',
        'clients': CLIENTS_RU,
        'contact': '@teodor_demo',
        'acc_name': 'THEODOR DEMO',
        'notes': 'Демо-витрина реферального кабинета. Сделки помечены is_test — в CRM их нет.',
    },
    'en': {
        'code': 'GR-THEODORE',
        'name': 'Theodore',
        'clients': CLIENTS_EN,
        'contact': '@theodore_demo',
        'acc_name': 'THEODORE DEMO',
        'notes': 'Demo dashboard in English (for English-speaking developers). '
                 'Deals flagged is_test — hidden from CRM.',
    },
}

# История выплат: (дней назад, способ, индексы покрытых сделок в DEALS).
# Сумма считается из фактических начислений — расхождения с балансом кабинета быть не может.
PAYOUTS = [
    (52, 'usdt', [0, 1, 2]),
    (28, 'thb',  [3, 4]),
    (5,  'usdt', [5]),          # свежая — в кабинете подсветится баннером «выплата пришла»
]

DEMO_WALLET = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
DEMO_HASHES = [
    'f3b1c9d2e47a58c06b1d9f3a2c85e740d6b93f18a7c25e09d4b613f8a92c705e',
    '8a41d70c25e9b3f16d0a84c7e29b53f4a1c86d20e5b79f3c14a0d68b27e95c3f',
]
BITAZZA_RATE = 32.41    # курс откупа на момент батовой заявки (снапшот, как на проде)


def _dt(days_ago, hour=13, minute=20):
    """Дата N дней назад с фиксированным временем — порядок сделок стабильный."""
    base = datetime.utcnow() - timedelta(days=days_ago)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _payin_method(rub):
    """Приход рублями — СБП, иначе крипта."""
    return PayInMethod.SPP_DOVERKA if rub else PayInMethod.CRYPTO_DIRECT


def wipe(db, referrer):
    """Снести прежнюю витрину: заявки, сделки (с агентами), демо-клиентов."""
    db.query(PayoutRequest).filter(
        PayoutRequest.referrer_id == referrer.id).delete(synchronize_session=False)
    deal_ids = [row.id for row in db.query(Deal.id).filter(
        Deal.is_test.is_(True), Deal.referrer_id == referrer.id).all()]
    if deal_ids:
        db.query(DealAgent).filter(
            DealAgent.deal_id.in_(deal_ids)).delete(synchronize_session=False)
        db.query(Deal).filter(Deal.id.in_(deal_ids)).delete(synchronize_session=False)
    db.query(Client).filter(
        Client.is_test.is_(True),
        Client.referrer_id == referrer.id).delete(synchronize_session=False)
    db.commit()
    return len(deal_ids)


def _arg_lang():
    """Язык витрины из --lang (ru по умолчанию)."""
    if '--lang' in sys.argv:
        val = sys.argv[sys.argv.index('--lang') + 1].strip().lower()
        if val not in PROFILES:
            sys.exit(f'Неизвестный язык: {val}. Доступно: {", ".join(PROFILES)}')
        return val
    return 'ru'


def main():
    Base.metadata.create_all(engine)
    lang = _arg_lang()
    prof = PROFILES[lang]
    CODE, NAME, CLIENTS = prof['code'], prof['name'], prof['clients']
    db = get_session()
    try:
        referrer = db.query(Referrer).filter(Referrer.code == CODE).first()
        if not referrer:
            referrer = Referrer(
                name=NAME, code=CODE, token=secrets.token_hex(16),
                default_percent=PERCENT, payout_currency='USDT',
                comp_model='revshare', markup_percent=0.0,
                lang=lang,
                active=True, is_test=True, auth_mode='link',
                notes=prof['notes'],
                created_at=_dt(90),
            )
            db.add(referrer)
            db.commit()
            db.refresh(referrer)
            print(f'✅ Реферер создан: #{referrer.id} {NAME} ({CODE}, lang={lang})')
        else:
            referrer.is_test = True
            referrer.active = True
            referrer.default_percent = PERCENT
            referrer.comp_model = 'revshare'
            referrer.auth_mode = 'link'
            referrer.lang = lang
            db.commit()
            removed = wipe(db, referrer)
            print(f'♻️  Реферер #{referrer.id} уже был — снёс {removed} демо-сделок')

        if '--wipe' in sys.argv:
            referrer.total_deals = 0
            referrer.total_referred_clients = 0
            referrer.total_earned_usdt = 0
            referrer.total_paid_usdt = 0
            db.commit()
            print('🧹 Витрина очищена')
            return

        # ── Клиенты ──
        clients = {}
        for i, (name, tg) in enumerate(CLIENTS):
            # Растягиваем регистрации на ~80 дней: последние двое попадают
            # в окно 30 дней → в кабинете живой счётчик «новых клиентов»
            c = Client(name=name, telegram=tg, referrer_id=referrer.id, is_test=True,
                       created_at=_dt(80 - i * 10))
            db.add(c)
            clients[name] = c
        db.commit()

        # ── Сделки + начисления агенту ──
        deals = []
        for days, client_idx, rub, usdt, thb, profit, paid in DEALS:
            client = clients[CLIENTS[client_idx][0]]
            when = _dt(days)
            commission = round(profit * PERCENT / 100, 2)
            rate_thb = round(thb / usdt, 4) if thb and usdt else None
            deal = Deal(
                created_at=when, updated_at=when,
                manager_name=MANAGER,
                deal_type=DealType.PAY_IN,
                status=DealStatus.COMPLETED,
                is_test=True,
                client_id=client.id, client_name=client.name,
                payin_method=_payin_method(rub),
                payin_amount_rub=rub,
                payin_amount_usdt=usdt,
                payin_rate_rub_usdt=round(rub / usdt, 2) if rub else None,
                payin_rate_usdt_thb=rate_thb,
                payout_method=PayOutMethod.TRANSFER,
                payout_amount_thb=thb,
                exchange_rate=rate_thb,
                profit_usdt=profit,
                profit_percent=round(profit / usdt * 100, 2) if usdt else None,
                referrer_id=referrer.id,
                referrer_name=referrer.name,
                referrer_percent=PERCENT,
                referrer_comp_model='revshare',
                referrer_payout_usdt=commission,
                referrer_paid=paid,
                referrer_paid_at=when + timedelta(days=5) if paid else None,
                net_profit_usdt=round(profit - commission, 2),
                needs_reimbursement=False,
                source_channel=f'ref:{CODE}',
            )
            db.add(deal)
            db.flush()
            db.add(DealAgent(
                deal_id=deal.id, referrer_id=referrer.id, name=referrer.name,
                tier=1, comp_model='revshare', percent=PERCENT, fixed_usdt=0.0,
                payout_usdt=commission, base_usdt=profit,
                paid=paid, paid_at=when + timedelta(days=5) if paid else None,
                created_at=when,
            ))
            deals.append({'deal': deal, 'commission': commission, 'paid': paid})
            client.total_deals = (client.total_deals or 0) + 1
            client.total_volume_usdt = round((client.total_volume_usdt or 0) + usdt, 2)
        db.commit()

        # ── История выплат ──
        for days, method, idxs in PAYOUTS:
            amount = round(sum(deals[i]['commission'] for i in idxs), 2)
            when = _dt(days, hour=10, minute=5)
            req = PayoutRequest(
                referrer_id=referrer.id,
                amount_usdt=amount,
                wallet=DEMO_WALLET if method == 'usdt' else 'Kasikorn Bank',
                contact_method='telegram',
                contact_value=prof['contact'],
                status='paid',
                payout_method=method,
                deal_ids=json.dumps([deals[i]['deal'].id for i in idxs]),
                created_at=when,
                updated_at=when + timedelta(hours=3),
                processed_at=when + timedelta(hours=3),
            )
            if method == 'usdt':
                req.tx_hash = DEMO_HASHES[0] if days > 30 else DEMO_HASHES[1]
            else:
                client_rate = round(BITAZZA_RATE * (1 - 0.0025), 4)
                req.bitazza_rate = BITAZZA_RATE
                req.client_rate = client_rate
                req.thb_amount = round(amount * client_rate - 20, 2)
                req.bank_name = 'Kasikorn Bank'
                req.account_name = prof['acc_name']
                req.account_number = '123-4-56789-0'
                req.receipt_tg_file_id = 'demo-receipt'
            db.add(req)
        db.commit()

        # ── Счётчики карточки реферера в CRM ──
        total_earned = round(sum(d['commission'] for d in deals), 2)
        total_paid = round(sum(d['commission'] for d in deals if d['paid']), 2)
        referrer.total_deals = len(deals)
        referrer.total_referred_clients = len(CLIENTS)
        referrer.total_earned_usdt = total_earned
        referrer.total_paid_usdt = total_paid
        db.commit()

        clients_with_deals = len({d['deal'].client_name for d in deals})
        print(f'✅ Клиентов: {len(CLIENTS)} (со сделками: {clients_with_deals})')
        print(f'✅ Сделок: {len(deals)}, начислено ${total_earned}, '
              f'выплачено ${total_paid}, к выводу ${round(total_earned - total_paid, 2)}')
        print(f'✅ Заявок на выплату: {len(PAYOUTS)} '
              f'({sum(1 for p in PAYOUTS if p[1] == "usdt")} USDT + '
              f'{sum(1 for p in PAYOUTS if p[1] == "thb")} ฿)')
        print(f'\n🔗 Кабинет: {BASE_URL}/ref/{referrer.token}')
    finally:
        db.close()


if __name__ == '__main__':
    main()
