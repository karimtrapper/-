"""Аудит 06.09.2026: контракты ввода и сохранность финансовых данных.

Семь групп дефектов исправлены: проверки выполняются без xfail.
Основные сценарии используют отдельную SQLite в памяти и синтетические данные.
CALCCRM_TEST_POSTGRES=1 включает конкуренцию на временном PostgreSQL.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as appmod


@pytest.fixture
def audit_db(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    appmod.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(appmod, 'get_session', factory)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, '_notify_reimbursed', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    monkeypatch.setitem(appmod.app.config, 'TESTING', True)
    monkeypatch.setitem(appmod.app.config, 'PROPAGATE_EXCEPTIONS', False)
    yield factory
    engine.dispose()


@pytest.fixture
def cli(audit_db):
    with appmod.app.test_client() as client:
        yield client


def _count(factory, model):
    with factory() as db:
        return db.query(model).count()


def _income(factory):
    with factory() as db:
        row = appmod.SberIncome(uuid='audit-income', operation_date='2026-09-01',
                               amount_rub=1000, payer='Синтетический клиент')
        db.add(row)
        db.commit()
        return row.id


def _deals(factory, count=1):
    with factory() as db:
        rows = [appmod.Deal(client_name=f'Аудит {i}',
                            deal_type=appmod.DealType.PAY_IN,
                            payin_method=appmod.PayInMethod.CRYPTO_DIRECT,
                            payin_amount_usdt=120,
                            payout_amount_thb=3000,
                            payout_source=appmod.PayOutSource.FOUNDER_PERSONAL,
                            payout_founder_name='Аудит', needs_reimbursement=True,
                            status=appmod.DealStatus.PENDING)
                for i in range(count)]
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]


def _assert_rejected(response):
    assert response.status_code in (400, 409, 422), response.get_data(as_text=True)
    assert response.is_json
    assert response.get_json().get('success') is False


@pytest.mark.parametrize('path,payload', [
    ('/api/conversions', [1]),
    ('/api/conversions', {'broker': 1}),
    ('/api/conversions', {'sources': [1]}),
    ('/api/docs/agreements', [1]),
    ('/api/docs/agreements', {'deal_type': 'leasehold', 'fields': [1]}),
    ('/api/docs/agreements', {'deal_type': 'leasehold', 'fields': {'client_name_ru': 1}}),
])
def test_malformed_json_is_validation_error(cli, audit_db, path, payload):
    response = cli.post(path, json=payload)
    _assert_rejected(response)
    assert _count(audit_db, appmod.Conversion) == 0
    assert _count(audit_db, appmod.Agreement) == 0


@pytest.mark.parametrize('payload', [
    {'rate_rub_usdt': -80},
    {'rate_rub_usdt': 'Infinity'},
    {'held_percent': 'Infinity'},
    {'amount_rub_sent': -100},
])
def test_conversion_invalid_numbers_do_not_persist(cli, audit_db, payload):
    response = cli.post('/api/conversions', json=payload)
    _assert_rejected(response)
    assert _count(audit_db, appmod.Conversion) == 0


@pytest.mark.parametrize('value', ['2026-02-30', 'not-a-date'])
def test_conversion_invalid_date_is_not_replaced_with_today(cli, audit_db, value):
    response = cli.post('/api/conversions', json={'sent_at': value})
    _assert_rejected(response)
    assert _count(audit_db, appmod.Conversion) == 0


def test_conversion_negative_source_cannot_increase_free_balance(cli, audit_db):
    income_id = _income(audit_db)
    response = cli.post('/api/conversions', json={
        'rate_rub_usdt': 80,
        'sources': [{'sber_income_id': income_id, 'amount_rub': -100}]})
    with audit_db() as db:
        assert db.get(appmod.SberIncome, income_id).free_rub() == 1000

    _assert_rejected(response)
    assert _count(audit_db, appmod.Conversion) == 0


def test_conversion_unknown_second_source_rolls_back_first(cli, audit_db):
    income_id = _income(audit_db)
    response = cli.post('/api/conversions', json={
        'rate_rub_usdt': 80, 'sources': [
            {'sber_income_id': income_id, 'amount_rub': 100},
            {'sber_income_id': 99999999, 'amount_rub': 100}]})
    _assert_rejected(response)
    assert _count(audit_db, appmod.Conversion) == 0
    assert _count(audit_db, appmod.ConversionSource) == 0
    with audit_db() as db:
        assert db.get(appmod.SberIncome, income_id).free_rub() == 1000


@pytest.mark.parametrize('payload', [
    {'rate_rub_usdt': 'wrong'},
    {'sources': [{'sber_income_id': 'wrong'}]},
    {'sources': [{'sber_income_id': 99999999}]},
])
def test_conversion_invalid_id_or_rate_rolls_back(cli, audit_db, payload):
    _assert_rejected(cli.post('/api/conversions', json=payload))
    assert _count(audit_db, appmod.Conversion) == 0


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/conversions/99999999'),
    ('PUT', '/api/conversions/99999999'),
    ('DELETE', '/api/conversions/99999999'),
    ('POST', '/api/docs/agreements/99999999/payment'),
])
def test_missing_entity_returns_404(cli, method, path):
    response = cli.open(path, method=method, json={})
    assert response.status_code == 404
    assert response.get_json()['success'] is False


def test_reimbursement_unknown_deal_does_not_create_orphan(cli, audit_db):
    response = cli.post('/api/reimbursements', json={
        'founder_name': 'Аудит', 'deal_ids': [99999999], 'amount_usdt': 100})
    assert _count(audit_db, appmod.Reimbursement) == 0
    assert response.status_code in (400, 404, 409, 422)


def test_reimbursement_negative_amount_does_not_change_deal(cli, audit_db):
    deal_id, = _deals(audit_db)
    response = cli.post('/api/reimbursements', json={
        'founder_name': 'Аудит', 'deal_ids': [deal_id], 'amount_usdt': -100})
    with audit_db() as db:
        deal = db.get(appmod.Deal, deal_id)
        assert deal.reimbursement_id is None
        assert deal.status == appmod.DealStatus.PENDING
    _assert_rejected(response)


def test_reimbursement_partial_allocations_cannot_exceed_total(cli, audit_db):
    deal_ids = _deals(audit_db, 2)
    response = cli.post('/api/reimbursements', json={
        'founder_name': 'Аудит', 'deal_ids': deal_ids, 'amount_usdt': 100,
        'deal_allocations': [{'deal_id': deal_ids[0], 'amount_usdt': 80}]})
    if response.status_code in (400, 409, 422):
        assert _count(audit_db, appmod.Reimbursement) == 0
    else:
        assert response.status_code == 200
        with audit_db() as db:
            deals = db.query(appmod.Deal).filter(appmod.Deal.id.in_(deal_ids)).all()
            assert sum(d.payout_amount_usdt for d in deals) == pytest.approx(100)


def test_reimbursement_repeat_cannot_reassign_settled_deal(cli, audit_db):
    deal_id, = _deals(audit_db)
    payload = {'founder_name': 'Аудит', 'deal_ids': [deal_id], 'amount_usdt': 100}
    first = cli.post('/api/reimbursements', json=payload)
    assert first.status_code == 200
    reimbursement_id = first.get_json()['reimbursement']['id']
    second = cli.post('/api/reimbursements', json=payload)
    with audit_db() as db:
        assert db.get(appmod.Deal, deal_id).reimbursement_id == reimbursement_id
        assert db.query(appmod.Reimbursement).count() == 1
    assert second.status_code in (200, 400, 409, 422)


def test_docs_generation_failure_rolls_back_entire_package(cli, audit_db, monkeypatch):
    """Ошибка при втором PDF не оставляет договор и первый файл в БД."""
    import docgen
    monkeypatch.setattr(docgen, 'build_agreement', lambda *a, **kw: (b'doc', 'number'))
    monkeypatch.setattr(docgen, 'build_addendum', lambda *a, **kw: b'doc')
    monkeypatch.setattr(docgen, 'build_commercial_invoice', lambda *a, **kw: b'doc')
    monkeypatch.setattr(docgen, 'check', lambda *a, **kw: [])
    attempts = []

    def convert(raw, name):
        attempts.append(name)
        if len(attempts) == 2:
            raise RuntimeError('Синтетический отказ PDF-конвертера')
        return b'%PDF-synthetic', name + '.pdf', 'application/pdf'

    monkeypatch.setattr(docgen, 'as_pdf', convert)
    response = cli.post('/api/docs/agreements', json={
        'deal_type': 'leasehold',
        'fields': {'client_name_ru': 'Аудит', 'client_passport_no': '990001234'},
        'money': {'total_payin': '100', 'transfer_amount': '100', 'rate': '1',
                  'payin_currency': 'RUB', 'pair': 'RUB_THB', 'payin_method': 'bank'}})
    assert len(attempts) == 2
    assert response.status_code == 500
    assert response.get_json()['error'] == 'server_error'
    assert _count(audit_db, appmod.Agreement) == 0
    assert _count(audit_db, appmod.AgreementDoc) == 0


@pytest.mark.parametrize('explicit', [False, True])
def test_reimbursement_full_distribution_preserves_total(cli, audit_db, explicit):
    """Контрпример DATA-05: полностью авто и полностью ручной разнос сходятся."""
    deal_ids = _deals(audit_db, 2)
    payload = {'founder_name': 'Аудит', 'deal_ids': deal_ids, 'amount_usdt': 100}
    if explicit:
        payload['deal_allocations'] = [
            {'deal_id': deal_ids[0], 'amount_usdt': 80},
            {'deal_id': deal_ids[1], 'amount_usdt': 20}]
    response = cli.post('/api/reimbursements', json=payload)
    assert response.status_code == 200
    with audit_db() as db:
        deals = db.query(appmod.Deal).filter(appmod.Deal.id.in_(deal_ids)).all()
        assert sum(d.payout_amount_usdt for d in deals) == pytest.approx(100)
        assert all(d.status == appmod.DealStatus.COMPLETED for d in deals)


def test_conversion_positive_source_reserves_exact_amount(cli, audit_db):
    income_id = _income(audit_db)
    response = cli.post('/api/conversions', json={
        'rate_rub_usdt': 80, 'sent_at': '2026-09-01',
        'sources': [{'sber_income_id': income_id, 'amount_rub': 100}]})
    assert response.status_code == 200
    assert response.get_json()['conversion']['sent_at'] == '2026-09-01T00:00:00'
    with audit_db() as db:
        assert db.get(appmod.SberIncome, income_id).free_rub() == 900
    conversion_id = response.get_json()['conversion']['id']
    assert cli.delete(f'/api/conversions/{conversion_id}').status_code == 200
    with audit_db() as db:
        assert db.get(appmod.SberIncome, income_id).free_rub() == 1000


@pytest.fixture(scope='module')
def postgres_audit_engine():
    """Одноразовый кластер: CALCCRM_TEST_POSTGRES=1, только Unix socket.

    DATABASE_URL не читается. initdb/pg_ctl ищутся в PATH или Homebrew 16;
    существующие серверы и базы никогда не используются.
    """
    import os
    from pathlib import Path
    import shutil
    import subprocess
    import tempfile
    from sqlalchemy.engine import URL

    if os.environ.get('CALCCRM_TEST_POSTGRES') != '1':
        pytest.skip('PostgreSQL concurrency: CALCCRM_TEST_POSTGRES=1')
    binaries = {}
    for name in ('initdb', 'pg_ctl'):
        binary = shutil.which(name)
        fallback = Path('/opt/homebrew/opt/postgresql@16/bin') / name
        if not binary and fallback.is_file():
            binary = str(fallback)
        if not binary:
            pytest.fail(f'Для PostgreSQL-проверки нужен {name} в PATH')
        binaries[name] = binary

    with tempfile.TemporaryDirectory(prefix='calccrm-pg-', dir='/tmp') as root:
        data = str(Path(root) / 'data')
        log = str(Path(root) / 'postgres.log')
        started = False
        engine = None
        try:
            subprocess.run([binaries['initdb'], '-D', data, '-A', 'trust',
                            '-U', 'calccrm_test', '--no-locale', '-E', 'UTF8'],
                           check=True, capture_output=True, text=True, timeout=30)
            subprocess.run([binaries['pg_ctl'], '-D', data, '-l', log,
                            '-o', f"-k {root} -h '' -p 55432", '-w', 'start'],
                           check=True, capture_output=True, text=True, timeout=30)
            started = True
            engine = create_engine(URL.create(
                'postgresql+psycopg2', username='calccrm_test', database='postgres',
                query={'host': root, 'port': '55432',
                       'application_name': 'calccrm_concurrency_audit',
                       'options': '-c statement_timeout=15000 -c lock_timeout=10000'}))
            appmod.Base.metadata.create_all(engine)
            yield engine
        finally:
            if engine is not None:
                engine.dispose()
            if started:
                subprocess.run([binaries['pg_ctl'], '-D', data, '-m', 'immediate',
                                '-w', 'stop'], check=True, capture_output=True,
                               text=True, timeout=30)


@pytest.fixture
def postgres_audit_db(postgres_audit_engine, monkeypatch):
    """Синтетические данные и новые независимые сессии для HTTP-потоков."""
    from sqlalchemy import text

    engine = postgres_audit_engine
    with engine.begin() as conn:
        tables = ', '.join(engine.dialect.identifier_preparer.quote(table.name)
                           for table in appmod.Base.metadata.tables.values())
        conn.execute(text(f'TRUNCATE {tables} RESTART IDENTITY CASCADE'))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(appmod, 'get_session', factory)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, '_notify_reimbursed', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, 'sync_deals_to_gsheet', lambda *a, **kw: None)
    monkeypatch.setattr(appmod, '_send_deal_telegram', lambda *a, **kw: None)
    monkeypatch.setitem(appmod.app.config, 'TESTING', True)
    monkeypatch.setitem(appmod.app.config, 'PROPAGATE_EXCEPTIONS', False)
    return factory


def _concurrent_posts_behind_row_lock(factory, model, row_id, path, payload):
    """Оба HTTP-запроса обязаны одновременно ждать настоящую блокировку PG."""
    from concurrent.futures import ThreadPoolExecutor
    import time
    from sqlalchemy import text

    def send(body):
        with appmod.app.test_client() as client:
            response = client.post(path, json=body)
            return response.status_code, response.get_json()

    with factory() as blocker, ThreadPoolExecutor(max_workers=2) as workers:
        blocker.query(model).filter(model.id == row_id).with_for_update().one()
        bodies = payload if isinstance(payload, list) else [payload, payload]
        futures = [workers.submit(send, body) for body in bodies]
        try:
            deadline = time.monotonic() + 5
            waiting = 0
            while time.monotonic() < deadline:
                with factory() as observer:
                    waiting = observer.execute(text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name = 'calccrm_concurrency_audit' "
                        "AND wait_event_type = 'Lock' AND state = 'active'"
                    )).scalar_one()
                if waiting == 2:
                    break
                if any(future.done() for future in futures):
                    break
                time.sleep(0.02)
            assert waiting == 2, 'Оба запроса должны ждать блокировку одной строки'
        finally:
            blocker.rollback()
        return [future.result(timeout=15) for future in futures]


def test_postgres_concurrent_reimbursement_preserves_single_settlement(postgres_audit_db):
    deal_id, = _deals(postgres_audit_db)
    results = _concurrent_posts_behind_row_lock(
        postgres_audit_db, appmod.Deal, deal_id, '/api/reimbursements',
        {'founder_name': 'Аудит', 'deal_ids': [deal_id], 'amount_usdt': 100})
    assert sorted(status for status, _ in results) == [200, 409], results
    winner = next(body for status, body in results if status == 200)
    with postgres_audit_db() as db:
        assert db.query(appmod.Reimbursement).count() == 1
        deal = db.get(appmod.Deal, deal_id)
        assert deal.reimbursement_id == winner['reimbursement']['id']
        assert deal.payout_amount_usdt == 100
        assert deal.status == appmod.DealStatus.COMPLETED


def test_postgres_concurrent_conversion_cannot_overdraw_income(postgres_audit_db):
    income_id = _income(postgres_audit_db)
    results = _concurrent_posts_behind_row_lock(
        postgres_audit_db, appmod.SberIncome, income_id, '/api/conversions',
        {'rate_rub_usdt': 80,
         'sources': [{'sber_income_id': income_id, 'amount_rub': 800}]})
    assert sum(status == 200 for status, _ in results) == 1, results
    rejected = [(status, body) for status, body in results if status != 200]
    assert rejected[0][0] in (400, 409, 422), results
    assert rejected[0][1]['success'] is False
    with postgres_audit_db() as db:
        assert db.query(appmod.Conversion).count() == 1
        assert db.query(appmod.ConversionSource).count() == 1
        assert db.get(appmod.SberIncome, income_id).free_rub() == 200


def test_postgres_different_deals_cannot_overdraw_shared_reimbursement_tx(postgres_audit_db):
    deal_ids = _deals(postgres_audit_db, 2)
    tx_hash = 'a' * 64
    with postgres_audit_db() as db:
        tx = appmod.ReimbursementTx(tx_hash=tx_hash, founder_name='Аудит',
                                   amount_usdt=100, source='manual')
        db.add(tx)
        db.commit()
        tx_id = tx.id
    payloads = [{'founder_name': 'Аудит', 'deal_ids': [deal_id], 'amount_usdt': 80,
                 'tx_uses': [{'tx_hash': tx_hash, 'amount_usdt': 80}]}
                for deal_id in deal_ids]
    results = _concurrent_posts_behind_row_lock(
        postgres_audit_db, appmod.ReimbursementTx, tx_id, '/api/reimbursements', payloads)
    assert sorted(status for status, _ in results) == [200, 409], results
    with postgres_audit_db() as db:
        assert db.query(appmod.Reimbursement).count() == 1
        assert db.query(appmod.ReimbursementTxUse).count() == 1
        assert db.get(appmod.ReimbursementTx, tx_id).free_usdt() == 20
        assert db.query(appmod.Deal).filter(appmod.Deal.reimbursement_id.isnot(None)).count() == 1
