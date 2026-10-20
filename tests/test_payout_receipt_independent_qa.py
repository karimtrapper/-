"""Независимая QA-проверка: чек выплаты от manager/operator/admin подтверждает выплату сам.

СД-1489-like аренда: приход наличными, расход THB банком 455000 KBank→BBL, чек грузит менеджер.
Загрузка идёт через настоящий /api/stand/files (не правкой доски)."""
import io
import json
import sys
import secrets

import pytest
import app as m
from tests.test_stand_single_confirm import setup_verified, change_board
from tests.test_stand_crm_close_atomic import _setup, _client, _counts

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


def _pk_rows(db):
    """Снимок первичных ключей всех таблиц (кроме stand_state, которую восстанавливаем целиком)."""
    from sqlalchemy import inspect, select
    existing = set(inspect(m.engine).get_table_names())  # метаданные ≠ реально созданные таблицы
    snap = {}
    for table in m.Base.metadata.sorted_tables:
        pk = list(table.primary_key.columns)
        if pk and table.name in existing and table.name != 'stand_state':
            snap[table] = {tuple(r) for r in db.execute(select(*pk))}
    return snap


@pytest.fixture(autouse=True)
def _qa_cleanup_created_rows():
    """Тесты этого файла делают настоящие crm-close; общая SQLite-БД живёт весь прогон.
    После каждого теста удаляем ТОЛЬКО созданные им строки (StandCrmLink, Deal, ledger и т.д.)
    и возвращаем stand_state, иначе старые фикстуры (чистят Deal и переиспользуют id) ловят
    UNIQUE stand_crm_links.crm_deal_id и чужие хеши в ledger."""
    from sqlalchemy import delete, select
    m._stand_migrate()  # таблицы стенда должны существовать до снимка (как делают _setup старых тестов)
    db = m.get_session()
    try:
        before = _pk_rows(db)
        states = [dict(r._mapping) for r in db.execute(select(m.StandState.__table__))]
        db.commit()
    finally:
        db.close()
    yield
    m.Session.remove()
    db = m.get_session()
    try:
        for table in reversed(m.Base.metadata.sorted_tables):
            if table not in before:
                continue
            pk = list(table.primary_key.columns)
            now = {tuple(r) for r in db.execute(select(*pk))}
            for key in now - before[table]:
                db.execute(delete(table).where(*[c == v for c, v in zip(pk, key)]))
        state_table = m.StandState.__table__
        db.execute(delete(state_table))
        for row in states:
            db.execute(state_table.insert().values(**row))
        db.commit()
    finally:
        db.close()
        m.Session.remove()

H_C, H_D, H_F, H_P, H_X = (secrets.token_hex(32) for _ in range(5))  # уникальные хеши, не a/b/d/f*64
PDF = b'%PDF-1.4\n' + secrets.token_bytes(24)
REASON = 'Выплата подтверждена чеком, перенос вручную'


def upload(client, *, extra=False, name='kbank-slip.pdf', raw=None, mime='application/pdf', deal=1474):
    form = {'dealId': str(deal), 'kind': 'additional' if extra else 'receipt',
            'file': (io.BytesIO(PDF if raw is None else raw), name, mime)}
    if extra:
        form.update(extra='1', documentType='receipt')
    return client.post('/api/stand/files', data=form, content_type='multipart/form-data')


def bank_board(monkeypatch, **patch):
    """Обычный путь: приход верифицирован, выплата получателю банком (без блокчейна)."""
    client, uid, crm = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    monkeypatch.setattr(m, '_send_deal_telegram', lambda deal, sender=None: None)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])

    def edit(d):
        d['files'] = {}
        d['docs'] = dict(d.get('docs') or {}, receipt=False)
        d['log'] = []
        d.update(postConv='', paySrc='cash', mfPayout=[], transfer={}, serverTransferComplete=False,
                 payTo={'bank': 'BBL', 'acc': '123-4-56789-0', 'dev': 'Villa Co',
                        'purpose': 'Rent', 'amount': 455000},
                 amountThb=455000, sentToClient=True, step='s27')
        d['payinHashes'][0]['amount'] = 13800
        d['pay'] = {'invoicePaid': True}
        d.update(patch)
    change_board(edit)
    crm = {**crm, 'invoice_amount_thb': 455000, 'payin_amount_usdt': 13800, 'payout_tx_hashes': [],
           'payin_tx_hashes': [{'hash': 'a' * 64, 'network': 'trc20', 'amount_usdt': 13800}]}
    crm.pop('payout_source', None)
    crm['realty_purpose'] = 'Rent'
    return client, uid, crm


def ordinary_close(client, crm):
    version = facts(client)[1]['version']
    return client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})


def facts(client):
    status = client.get('/api/stand/deals/1474/close-evidence').json
    return {f['kind']: f for f in status['facts']}, status


@pytest.mark.parametrize('extra', [False, True], ids=['receipt-slot', 'additional-receipt'])
def test_ordinary_upload_confirms_payout_with_author_and_date(monkeypatch, extra):
    client, uid, crm = bank_board(monkeypatch)
    f, _ = facts(client)
    assert not f['payout']['ready']
    r = upload(client, extra=extra)
    assert r.status_code == 200, r.json
    f, status = facts(client)
    assert f['payout']['ready'], f['payout']
    assert f['payout']['confirmed_role'] == 'manager' and f['payout']['confirmed_by'] == 'T24 Manager'
    assert f['payout']['checked_at']


def test_no_receipt_blocks(monkeypatch):
    client, _, _ = bank_board(monkeypatch)
    f, status = facts(client)
    assert not f['payout']['ready'] and 'payout' in status['missing']


def test_crypto_route_without_hash_still_blocks_even_with_receipt(monkeypatch):
    client, _, _ = bank_board(monkeypatch, postConv='coins', transfer={'amount': 0, 'sends': []})
    assert upload(client).status_code == 200
    f, _ = facts(client)
    assert not f['payout']['ready']
    client2, _, _ = bank_board(monkeypatch, paySrc='client')
    assert upload(client2, extra=True).status_code == 200
    assert not facts(client2)[0]['payout']['ready']


def _put_forged(client, files, **deal_patch):
    state = client.get('/api/stand/state').json
    deal = state['data']['deals'][0]
    deal.update(payoutFact={'route': 'bank', 'amountThb': 455000, 'receiptBy': 'Лиза',
                            'receiptRole': 'admin', 'receiptAt': 1760000000000})
    deal['files'] = files
    deal['log'] = [{'text': 'Приложен документ x.pdf · Лиза', 'role': 'admin', 'at': 1760000000000}]
    deal.update(deal_patch)
    return client.put('/api/stand/state', json={'version': state.get('version'), 'data': state['data']})


_PDF_URL = 'data:application/pdf;base64,JVBERi0xLjQK'


def _forged_item(**kw):
    return {'id': 'sf_fake', 'file': 'x.pdf', 'mime': 'application/pdf', 'documentType': 'receipt',
            'uploadedById': 999999, 'uploadedBy': 'Лиза', 'demo': False, **kw}


def test_spoof_a_no_bytes_foreign_id_blocks(monkeypatch):
    """(а) вложение без байтов, чужой uploadedById и поддельный payoutFact выплату не подтверждают."""
    client, _, _ = bank_board(monkeypatch)
    _put_forged(client, {'additional': [_forged_item()]})
    f, _ = facts(client)
    assert not f['payout']['ready'], f['payout']


def test_spoof_b_valid_bytes_foreign_id_never_gives_fake_author(monkeypatch):
    """(б) валидные байты, но заявленный uploadedById чужой: подложного автора не получаем.
    Блок допустим (helper сверяет id с хранилищем); если принято — автор только из сессии."""
    client, _, _ = bank_board(monkeypatch)
    _put_forged(client, {'additional': [_forged_item(data=_PDF_URL)]})
    f, _ = facts(client)
    if f['payout']['ready']:
        assert f['payout']['confirmed_by'] == 'T24 Manager' and f['payout']['confirmed_role'] == 'manager'
    assert f['payout'].get('confirmed_by') not in ('Лиза', '999999')
    assert f['payout'].get('confirmed_role') != 'admin'


def test_spoof_c_real_uid_fake_name_role_in_json_uses_real_name_role(monkeypatch):
    """(в) настоящий uid, но поддельные имя/роль в metadata и журнале: принят чек есть,
    имя и роль берутся с сервера (T24 Manager / manager), не из JSON."""
    client, uid, _ = bank_board(monkeypatch)
    r = _put_forged(client, {'additional': [_forged_item(
        data=_PDF_URL, uploadedById=uid, uploadedBy='Лиза-Подделка')]})
    assert r.status_code == 200, r.json
    f, _ = facts(client)
    assert f['payout']['ready'], f['payout']
    assert f['payout']['confirmed_by'] == 'T24 Manager' and f['payout']['confirmed_role'] == 'manager', f['payout']
    assert 'Подделка' not in str(f['payout'])


def test_invalid_files_rejected_and_not_accepted(monkeypatch):
    client, _, _ = bank_board(monkeypatch)
    assert upload(client, raw=b'hello', name='slip.pdf').status_code == 400
    assert upload(client, raw=b'MZ\x90\x00' + b'0' * 50, name='slip.pdf').status_code == 400
    assert upload(client, extra=True, raw=b'<html>', name='slip.png', mime='image/png').status_code == 400
    assert upload(client, raw=PDF, name='slip.exe', mime='application/x-msdownload').status_code == 400
    assert not facts(client)[0]['payout']['ready']


def test_non_receipt_additional_does_not_confirm(monkeypatch):
    client, _, _ = bank_board(monkeypatch)
    form = {'dealId': '1474', 'kind': 'additional', 'extra': '1', 'documentType': 'other',
            'file': (io.BytesIO(PDF), 'other.pdf', 'application/pdf')}
    assert client.post('/api/stand/files', data=form, content_type='multipart/form-data').status_code == 200
    assert not facts(client)[0]['payout']['ready']


def test_newer_upload_author_beats_old_s26_completion(monkeypatch):
    client, uid, _ = bank_board(monkeypatch)
    old = 1700000000000

    def old_s26(d):
        d['log'] = [{'at': old, 'ts': '01.01, 00:00', 'role': 'operator', 'kind': 's26_completed',
                     'byId': 999, 'by': 'Старый Оператор', 'receipts': [], 'text': 'x'}]
    change_board(old_s26)
    assert upload(client).status_code == 200
    f, _ = facts(client)
    assert f['payout']['ready'] and f['payout']['confirmed_by'] == 'T24 Manager'


@pytest.mark.parametrize('extra', [False, True], ids=['receipt-slot', 'additional-receipt'])
def test_closing_via_crm_close_ordinary_real_201(monkeypatch, extra):
    client, uid, crm = bank_board(monkeypatch)
    assert upload(client, extra=extra).status_code == 200
    before = _counts()
    r = ordinary_close(client, crm)
    assert r.status_code == 201, r.json
    assert r.json['data']['deals'][0]['closed'] is True and r.json['deal']['invoice_amount_thb'] == 455000
    assert _counts() == (before[0] + 1, before[1] + 1)


def test_ordinary_blocked_close_creates_no_crm_deal(monkeypatch):
    client, uid, crm = bank_board(monkeypatch)
    before = _counts()
    r = ordinary_close(client, crm)               # нет чека
    assert r.status_code == 409 and 'payout' in (r.json.get('missing') or []) or r.json.get('error') in (
        'receipt_missing', 'close_evidence_missing'), r.json
    assert _counts() == before
    for patch in ({'postConv': 'coins'}, {'paySrc': 'client'}):  # crypto без hash и перевода
        client, uid, crm = bank_board(monkeypatch, **patch)
        before = _counts()
        assert upload(client).status_code == 200
        r = ordinary_close(client, crm)
        assert r.status_code == 409, (patch, r.json)
        assert _counts() == before


# ---------- manualOverride: СД-1489-like аренда, приход наличными, расход THB банком ----------
VERIFY_CALLS = []  # вызовы verify_transfer (доказательство автоматической сетевой сверки)


def rental_board(monkeypatch, **patch):
    uid = _setup(monkeypatch)
    deal = {'id': 1474, 'code': 'СД-1489', 'client': 'Synthetic rental', 'type': 'Оплата недвижимости',
            'kind': 'Аренда', 'step': 's14', 'payType': 'Наличные', 'amountRub': 1217600,
            'amountThb': 455000, 'rates': {'client': '2,676', 'usdtThb': '33.42'},
            'object': 'Synthetic villa', 'docs': {'inv': True, 'receipt': False},
            'payTo': {'bank': 'BBL', 'acc': '123-4-56789-0', 'dev': 'Villa Co'},
            'mfPayout': [], 'payinHashes': [], 'agents': [], 'files': {},
            'closed': False, 'crmDealId': None, 'log': []}
    deal.update(patch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        row.data = json.dumps({'deals': [deal], 'notes': []})
        db.commit()
    finally:
        db.close()
    VERIFY_CALLS.clear()

    def spy_verify(ref, network, sender, receiver, amount):
        VERIFY_CALLS.append({'ref': ref, 'network': network, 'receiver': receiver, 'amount': amount})
        return {'status': 'confirmed', 'verifiedAmount': amount, 'verifiedAt': '2026-10-20T00:00:00Z', 'from': 'S'}

    monkeypatch.setattr(m, 'verify_transfer', spy_verify)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    monkeypatch.setattr(m, '_stand_notify_deal_closed', lambda *_a: None)
    # нижний транспорт: никаких DNS/сети (stand_egress), как в test_stand_manual_close_realty.py
    monkeypatch.setattr(m, '_tx_info_by_network', lambda tx_hash, network: None)
    monkeypatch.setattr(m, '_send_deal_telegram', lambda deal, sender=None: None)
    return _client(uid)


CRM = {'deal_kind': 'mf_realty', 'client_name': 'Synthetic rental', 'manager_name': 'Елизавета',
       'payin_method': 'partners_cash', 'payin_amount_rub': 1217600, 'payin_amount_usdt': 14500,
       'payin_tx_hashes': [{'hash': H_P, 'network': 'trc20', 'amount_usdt': 14500}],
       'payin_parts': [], 'payin_extra': [], 'realty_purpose': 'Synthetic villa',
       'invoice_amount_thb': 455000, 'buy_rate_thb_usdt': 33.42, 'sell_rate_thb_usdt': None,
       'company_percent': 2, 'agents': [], 'payout_tx_hashes': []}


def payin_hash(h=None, amount=14500):
    return {'hash': h or H_P, 'network': 'trc20', 'receiver': 'TReceiverWallet111111111111', 'amount': amount}


def override(*, hashes=True, **payout):
    p = {'route': 'bank', 'amountThb': 455000,
         'recipient': {'name': 'Villa Co', 'bank': 'BBL', 'acc': '123-4-56789-0'}}
    p.update(payout)
    return {'reason': REASON,
            'payin': {'method': 'Наличные', 'amountRub': 1217600, 'amountUsdt': 14500,
                      'hashes': [payin_hash()] if hashes else []},
            'realty': {'invoiceThb': 455000, 'buyRate': 33.42, 'sellRate': None, 'companyPercent': 2},
            'payout': p, 'agents': []}


def close(client, ov, version=None):
    version = version or client.get('/api/stand/state').json['version']
    before = _counts()
    r = _close(client, ov, version)
    if r.status_code >= 400:
        assert _counts() == before, 'отказ создал CRM-сделку'
    return r


def _close(client, ov, version):
    return client.post('/api/stand/deals/1474/crm-close',
                       json={'version': version, 'crm': CRM, 'manualOverride': ov})


@pytest.mark.parametrize('extra', [False, True], ids=['receipt-slot', 'additional-receipt'])
@pytest.mark.parametrize('route', ['bank', 'founder', 'cash'])
def test_override_noncrypto_payout_closes_with_receipt_no_hash(monkeypatch, route, extra):
    client = rental_board(monkeypatch, step='s27' if not extra else 's14')
    assert upload(client, extra=extra).status_code == 200
    r = close(client, override(route=route))
    assert r.status_code == 201, r.json
    deal = r.json['data']['deals'][0]
    assert deal['closed'] and r.json['deal']['deal_kind'] == 'mf_realty'
    assert deal['payoutFact']['amountThb'] == 455000 and deal['payoutFact']['receiptBy'] == 'T24 Manager'
    assert deal['payoutFact']['receiptRole'] == 'manager'


def test_override_blocks_without_receipt(monkeypatch):
    client = rental_board(monkeypatch)
    r = close(client, override())
    assert r.status_code >= 400, r.json


def test_override_docs_receipt_boolean_without_file_is_not_a_receipt(monkeypatch):
    client = rental_board(monkeypatch, docs={'inv': True, 'receipt': True})
    r = close(client, override())
    assert r.status_code >= 400, r.json
    # и с mfPayout: булев docs.receipt без настоящего файла тоже не чек
    client = rental_board(monkeypatch, docs={'inv': True, 'receipt': True},
                          mfPayout=[{'hash': H_F, 'net': 'TRC20', 'amount': 1388.89}])
    r = close(client, {**override(), 'payout': {'amountUsdt': 1388.89}})
    assert r.status_code >= 400, r.json


def test_override_with_mfpayout_and_real_receipt_closes(monkeypatch):
    client = rental_board(monkeypatch, mfPayout=[{'hash': H_F, 'net': 'TRC20', 'amount': 1388.89}])
    assert upload(client, extra=True).status_code == 200
    ov = override()
    ov['payout'] = {}
    global CRM
    saved = CRM
    CRM = {**CRM, 'payout_tx_hashes': [{'hash': H_F, 'network': 'trc20', 'amount_usdt': 1388.89}]}
    try:
        r = close(client, ov)
    finally:
        CRM = saved
    assert r.status_code == 201, r.json


def test_override_underpayment_vs_invoice_blocks(monkeypatch):
    client = rental_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200
    r = close(client, override(amountThb=454000))
    assert r.status_code == 400 and r.json['error'] == 'payout_amount_below_invoice', r.json
    assert close(client, override(amountThb=454999.5)).status_code == 201  # допуск 1 ฿


@pytest.mark.parametrize('patch', [{'postConv': 'coins'}, {'postConv': 'ipps_swift'}, {'postConv': 'client'},
                                   {'paySrc': 'coins'}, {'paySrc': 'client'},
                                   {'transfer': {'sends': [{'hash': H_C}]}}])
def test_override_bank_route_cannot_mask_crypto_board_route(monkeypatch, patch):
    client = rental_board(monkeypatch, **patch)
    assert upload(client, extra=True).status_code == 200
    r = close(client, override())
    assert r.status_code >= 400 and r.json['error'] == 'payout_route_conflict', r.json


def test_override_crypto_route_without_hash_blocks_even_with_receipt(monkeypatch):
    client = rental_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200
    ov = {**override(), 'payout': {'route': 'crypto', 'amountUsdt': 13800, 'hashes': []}}
    assert close(client, ov).status_code >= 400
    ov['payout'] = {'amountUsdt': 13800}  # маршрут по умолчанию — crypto
    assert close(client, ov).status_code >= 400
    ov['payout'] = {'route': 'wire'}
    assert close(client, ov).json['error'] == 'payout_route_invalid'


def test_override_recipient_required(monkeypatch):
    client = rental_board(monkeypatch, payTo={'dev': 'x'})
    assert upload(client, extra=True).status_code == 200
    r = close(client, override(recipient={}))
    assert r.json['error'] == 'payout_recipient_required', r.json


def test_override_spoofed_client_payoutfact_ignored(monkeypatch):
    """Клиент шлёт payoutFact/receiptBy в override: итог берётся только с сервера."""
    client = rental_board(monkeypatch)
    ov = override()
    ov['payoutFact'] = {'receiptBy': 'Fake', 'receiptRole': 'admin', 'receiptAt': 1}
    ov['payout']['receiptBy'] = 'Fake'
    assert close(client, ov).status_code >= 400  # без реального чека закрыть нельзя


def test_override_receipt_from_other_deal_or_forged_log_not_accepted(monkeypatch):
    client = rental_board(monkeypatch, files={'receipt': [{
        'id': 'sf_x', 'file': 'f.pdf', 'mime': 'application/pdf', 'uploadedById': 1,
        'uploadedBy': 'Лиза', 'demo': False, 'data': 'data:application/pdf;base64,JVBERi0xLjQK'}]},
        log=[{'text': 'Приложен файл: receipt · f.pdf', 'role': 'manager', 'at': 1760000000000}])
    r = close(client, override())
    assert r.status_code >= 400, r.json


# ---------- s27 обычный путь: invoicePaid=false + чек менеджера ----------
def test_ordinary_s27_invoice_unpaid_with_manager_receipt(monkeypatch):
    """Требование: чек менеджера сам подтверждает выплату, отдельная отметка оплаты инвойса не нужна.
    Если backend всё ещё требует pay.invoicePaid -> FAIL (UI hasReceipt пропускает, сервер вернёт 409)."""
    client, uid, crm = bank_board(monkeypatch)
    change_board(lambda d: d.update(pay={'invoicePaid': False}))
    assert upload(client, extra=True).status_code == 200
    before = _counts()
    r = ordinary_close(client, crm)
    print('INVOICE_UNPAID close', r.status_code, r.json.get('error'), r.json.get('missing'))
    assert r.status_code == 201, r.json
    assert _counts() == (before[0] + 1, before[1] + 1)


def test_operator_cannot_close_even_with_receipt(monkeypatch):
    """Запрет закрытия операционистом сохранён (и обычный, и ручной путь); CRM-сделка не создаётся."""
    client = rental_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200
    db = m.get_session()
    try:
        op = m.AdminUser(username='op-' + secrets.token_hex(4), role='operator', password_hash='unused')
        db.add(op); db.flush(); op_id = op.id; db.commit()
    finally:
        db.close()
    opc = _client(op_id)
    before = _counts()
    r = _close(opc, override(), client.get('/api/stand/state').json['version'])
    assert r.status_code == 403, r.json
    assert _counts() == before


@pytest.mark.parametrize('step', ['s14', 's4', 's11'])
def test_BLOCKER_manual_form_receipt_slot_upload_allowed_on_early_step(monkeypatch, step):
    """BLOCKER: поле чека в форме ручного переноса грузит в слот «Чек» (kind=receipt) на раннем шаге
    (СД-1489 стоит на s14). Менеджер обязан загрузить, а затем закрыть через manualOverride (201).
    Сейчас _stand_guard_transition даёт 403 для kind=receipt вне s26/s27 — тест НЕ подгонять под 403."""
    client = rental_board(monkeypatch, step=step)
    r = upload(client)
    assert r.status_code == 200, (step, r.status_code, r.json)
    closed = close(client, override())
    assert closed.status_code == 201, closed.json


# ---------- Приход USDT ВСЕГДА требует hash (наличные/банк/крипта); сверка сетью без подтверждения человека ----------
def pending_board(monkeypatch, **extra):
    """СД-1489: висит ручная сверка RUB у оператора + нота оператора."""
    client = rental_board(monkeypatch, manualBankReceipt={
        'id': 'old-rub-1217600', 'status': 'pending', 'handoff': True, 'requestedRole': 'operator',
        'requestedAt': '2026-10-18T10:00:00Z'},
        payTo={'bank': 'BBL', 'acc': '123-4-56789-0', 'dev': 'Villa Co', 'purpose': 'Synthetic villa'}, **extra)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        state['notes'] = [{'id': 'stand:manual-bank-receipt:1474:old-rub-1217600', 'role': 'operator',
                           'dealId': 1474, 'text': 'сверка', 'at': 1, 'read': False}]
        row.data = json.dumps(state); db.commit()
    finally:
        db.close()
    assert upload(client, extra=True, name='kbank-bbl-455000.pdf').status_code == 200
    return client


@pytest.mark.parametrize('variant', ['rub-cash-hash', 'cash-partner-hash'])
def test_regression_1489_partner_hash_plus_pending_rub_closes_in_one_submit(monkeypatch, variant):
    """Приходный hash партнёра сверяется сетью; висящая RUB-сверка отменяется; ни одного подтверждения
    человеком; один submit → 201; повторный submit не создаёт вторую сделку."""
    client = pending_board(monkeypatch, **({'cashPartnerUsdt': True} if variant.startswith('cash-partner') else {}))
    ov = override()
    before = _counts()
    r = close(client, ov)
    assert r.status_code == 201, r.json
    assert _counts() == (before[0] + 1, before[1] + 1)
    closed = r.json['data']['deals'][0]
    assert closed['closed'] is True and closed['step'] == 'done'
    # сервер САМ сверил приходный hash по сети: вызов verify_transfer с этим hash/сетью/суммой
    calls = [c for c in VERIFY_CALLS if c['ref'] == H_P]
    assert calls, VERIFY_CALLS
    assert 'trc20' in str(calls[0]['network']).lower() and float(calls[0]['amount']) == 14500.0, calls[0]
    assert [h['hash'] for h in closed['payinHashes']] == [H_P]       # hash принят и записан
    assert closed['payinHashes'][0].get('verified') is not False
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        kinds = {e.kind: e.provenance for e in db.query(m.StandCloseEvidence).filter_by(generation=row.generation)}
    finally:
        db.close()
    assert not {k for k, v in kinds.items() if v == 'operator_attestation'}, kinds
    assert (closed.get('manualBankReceipt') or {}).get('status') in ('cancelled', 'resolved'), closed.get('manualBankReceipt')
    assert not any(n.get('dealId') == 1474 and n.get('role') == 'operator' and not n.get('read')
                   for n in r.json['data'].get('notes') or []), r.json['data'].get('notes')
    texts = ' | '.join(str(e.get('text')) for e in closed.get('log') or [])
    assert 'вне задачника' in texts and 'без подтверждений операциониста' in texts, texts
    assert 'закрыто вручную менеджером' in texts.lower() and 'T24 Manager' in texts, texts
    close(client, ov, version=1)
    assert _counts() == (before[0] + 1, before[1] + 1)


@pytest.mark.parametrize('variant', ['rub-cash', 'cash-partner', 'bank'])
def test_no_payin_hash_is_now_negative_everywhere(monkeypatch, variant):
    """Все варианты без приходного hash — отказ; CRM-сделка не создаётся; сверка остаётся pending."""
    client = pending_board(monkeypatch, **({'cashPartnerUsdt': True} if variant == 'cash-partner' else {}))
    ov = override(hashes=False)
    if variant == 'bank':
        ov['payin']['method'] = 'Банк'
    before = _counts()
    r = close(client, ov)
    assert r.status_code >= 400, r.json
    assert r.json['error'] == 'payin_hash_required', r.json
    assert _counts() == before
    board = client.get('/api/stand/state').json['data']['deals'][0]
    assert not board.get('closed') and (board.get('manualBankReceipt') or {}).get('status') == 'pending'


def test_payin_hash_unverified_pending_blocks(monkeypatch):
    client = pending_board(monkeypatch)
    monkeypatch.setattr(m, 'verify_transfer', lambda *_a, **_k: {'status': 'pending'})
    before = _counts()
    r = close(client, override())
    assert r.status_code == 422 and r.json['error'] == 'payin_hash_unverified', r.json
    assert _counts() == before
    assert (client.get('/api/stand/state').json['data']['deals'][0].get('manualBankReceipt') or {}).get('status') == 'pending'


def test_payin_hash_invalid_format_blocks(monkeypatch):
    client = pending_board(monkeypatch)
    ov = override()
    ov['payin']['hashes'] = [payin_hash('not-a-hash')]
    # CRM несёт ТОТ ЖЕ невалидный hash: единственное отличие — невалидность, а не несовпадение CRM с доской
    monkeypatch.setattr(sys.modules[__name__], 'CRM', {
        **CRM, 'payin_tx_hashes': [{'hash': 'not-a-hash', 'network': 'trc20', 'amount_usdt': 14500}]})
    before = _counts()
    r = close(client, ov)
    assert r.status_code >= 400 and r.json['error'].startswith('payin_hash'), r.json
    assert _counts() == before


def test_payin_amount_mismatch_blocks(monkeypatch):
    client = pending_board(monkeypatch)
    monkeypatch.setattr(m, 'verify_transfer', lambda _h, _n, _s, _r, amount: {
        'status': 'confirmed', 'verifiedAmount': 100.0, 'verifiedAt': '2026-10-20T00:00:00Z', 'from': 'S'})
    before = _counts()
    r = close(client, override())
    assert r.status_code == 422 and r.json['error'] == 'payin_amount_mismatch', r.json
    assert _counts() == before


def test_payin_hash_of_another_deal_blocks(monkeypatch):
    client = pending_board(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        state['deals'].insert(0, {'id': 1, 'payinHashes': [{'hash': H_P, 'network': 'TRC20', 'amount': 14500}]})
        row.data = json.dumps(state); db.commit()
    finally:
        db.close()
    before = _counts()
    r = close(client, override())
    assert r.status_code == 422 and r.json['error'] == 'payin_hash_already_used', r.json
    assert _counts() == before


# ---------- обычный s27: приход проверен сетью, подписи человека нет ----------
def test_ordinary_s27_payin_is_network_verified_without_signoff(monkeypatch):
    client, uid, crm = bank_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200
    f, status = facts(client)
    assert f['payin']['ready'] and f['payin']['system'] is True and f['payin']['source'] == 'verified_network', f['payin']
    r = ordinary_close(client, crm)
    assert r.status_code == 201, r.json
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        kinds = {e.kind: e.provenance for e in db.query(m.StandCloseEvidence).filter_by(generation=row.generation)}
    finally:
        db.close()
    assert 'payin' not in kinds and not any(v == 'operator_attestation' for v in kinds.values()), kinds


def _operator_client():
    db = m.get_session()
    try:
        op = m.AdminUser(username='op-' + secrets.token_hex(4), role='operator', password_hash='unused')
        db.add(op); db.flush(); op_id = op.id; db.commit()
    finally:
        db.close()
    return _client(op_id)


@pytest.mark.parametrize('pay_type', ['Наличные', 'СБП', 'Банк'])
def test_ordinary_s27_non_crypto_payin_without_hash_asks_for_hash_not_human_signoff(monkeypatch, pay_type):
    """Без сетевого hash приход блокируется ПО ПРИЧИНЕ «нужен hash», а не «ждём подтверждения оператора»:
    ни кнопки подтверждения человеку (required_role/manual), ни POST close-evidence, создающего подпись."""
    client, uid, crm = bank_board(monkeypatch, payType=pay_type, payinHashes=[])
    assert upload(client, extra=True).status_code == 200
    f, status = facts(client)
    payin = f['payin']
    assert not payin['ready'], payin
    assert payin['reason'] != 'operator_confirmation_missing', payin
    assert payin['required_role'] != 'operator', payin           # UI не рисует кнопку «Подтвердить» оператору
    assert payin.get('system') is not True or not payin['ready'], payin
    assert 'payin' in status['missing']
    # попытка поставить подпись прихода (менеджер/оператор/админ) не создаёт запись и не обещает прохода
    for actor in (client, _operator_client()):
        r = actor.post('/api/stand/deals/1474/close-evidence', json={'version': status['version'], 'kind': 'payin'})
        assert r.status_code >= 400, r.json
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        assert db.query(m.StandCloseEvidence).filter_by(generation=row.generation, kind='payin').count() == 0
    finally:
        db.close()
    before = _counts()
    r = ordinary_close(client, {**crm, 'payin_tx_hashes': []})
    assert r.status_code == 409, r.json
    assert _counts() == before


def test_ordinary_s27_cash_partner_payin_ready_without_signoff_readiness_only(monkeypatch):
    """Cash-partner в обычном s27: приход с проверенным hash (ledgerUseId, TRC20) → verified_partner_network,
    system, без подписи человека. ТОЛЬКО readiness: полноценный crm-close требует резерва партии
    наличных в ledger, готовой чистой фикстуры для этого в моём файле нет (честное ограничение)."""
    client, uid, crm = bank_board(monkeypatch, payType='Наличные', cashPartnerUsdt=True, payinHashes=[{
        'hash': H_P, 'network': 'TRC20', 'amount': 13800, 'verified': True, 'ledgerUseId': 'use-1',
        'verifiedAt': '2026-10-20T00:00:00Z', 'from': 'S', 'to': 'W'}])
    assert upload(client, extra=True).status_code == 200
    f, _ = facts(client)
    assert f['payin']['ready'] and f['payin']['system'] is True, f['payin']
    assert f['payin']['source'] == 'verified_partner_network', f['payin']


def test_manual_override_empty_hash_string_blocks(monkeypatch):
    """hashes=[{hash:""}] — не приход: отказ payin_hash_*, без сделки, сверка остаётся pending."""
    client = pending_board(monkeypatch)
    ov = override()
    ov['payin']['hashes'] = [{'hash': '', 'network': 'trc20', 'receiver': 'TReceiverWallet111111111111', 'amount': 14500}]
    monkeypatch.setattr(sys.modules[__name__], 'CRM', {
        **CRM, 'payin_tx_hashes': [{'hash': '', 'network': 'trc20', 'amount_usdt': 14500}]})
    before = _counts()
    r = close(client, ov)
    assert r.status_code >= 400 and str(r.json['error']).startswith('payin_hash'), r.json
    assert _counts() == before
    assert (client.get('/api/stand/state').json['data']['deals'][0].get('manualBankReceipt') or {}).get('status') == 'pending'


@pytest.mark.parametrize('pay_type', ['Крипта', 'Наличные'])
def test_ordinary_s27_verified_payin_with_empty_hash_string_blocks_real_close(monkeypatch, pay_type):
    """Источник verified_network смотрит verified+amount, а не сам hash: пустая строка hash при
    verified:true не должна закрывать сделку. Проверяется реальный crm-close, а не только источник."""
    client, uid, crm = bank_board(monkeypatch, payType=pay_type, payinHashes=[{
        'hash': '', 'network': 'TRC20', 'amount': 13800, 'verified': True,
        'verifiedAt': '2026-10-20T00:00:00Z', 'from': 'S', 'to': 'W'}])
    assert upload(client, extra=True).status_code == 200
    before = _counts()
    r = ordinary_close(client, {**crm, 'payin_tx_hashes': [{'hash': '', 'network': 'trc20', 'amount_usdt': 13800}]})
    assert r.status_code >= 400, r.json
    assert _counts() == before
