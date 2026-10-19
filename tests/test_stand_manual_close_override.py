"""Прямые юнит-тесты _stand_manual_close_apply_override — ядро валидации и
применения фактов ручного переноса сделки в CRM (минуя штатный шаг s27).

Вызывается напрямую как чистая функция (без HTTP, без БД) — паттерн как в
tests/test_t31_legacy_manual.py для _stand_guard_transition."""
import app as A

REASON = 'Клиент на связи, перевёл через кассу — проверено вручную'


def board(**overrides):
    """Минимальная сделка на доске: по умолчанию «Обмен валюты», открыта,
    без файлов и хешей — overrides переопределяют/добавляют поля сделки."""
    deal = {
        'id': 1489, 'step': 's14', 'type': 'Обмен валюты',
        'closed': False, 'files': {}, 'payinHashes': [], 'log': [],
    }
    deal.update(overrides)
    state = {'deals': [deal], 'convs': [], 'notes': []}
    return state, deal


def confirmed_echo(ref, network, sender, receiver, amount):
    """Фейковый verify: подтверждает перевод суммой, которую ему передали —
    без обращения к сети, как того требует бриф (не монкипатчим network I/O)."""
    return {'status': 'confirmed', 'verifiedAmount': float(amount or 0),
            'verifiedAt': '2026-01-01T00:00:00Z', 'from': sender or 'TSenderWallet11111111111111'}


def test_rejects_manual_origin_deal():
    state, deal = board(originMode='manual')
    override = {'reason': REASON}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager') == 'manual_override_not_applicable'


def test_rejects_already_closed_deal():
    state, deal = board(closed=True)
    override = {'reason': REASON}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager') == 'already_closed'


def test_rejects_missing_reason():
    state, deal = board()
    override = {'reason': 'коротко'}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager') == 'manual_override_reason_required'


def test_rejects_missing_payin_hash_for_crypto():
    state, deal = board()
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager') == 'payin_hash_required'


def test_rejects_unverified_hash():
    state, deal = board()

    def pending(ref, network, sender, receiver, amount):
        return {'status': 'pending'}

    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': 'a' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=pending) == 'payin_hash_unverified'


def test_rejects_reused_hash():
    tx_hash = 'b' * 64
    other_deal = {'id': 1, 'payinHashes': [{'hash': tx_hash, 'network': 'TRC20', 'amount': 100}]}
    state, deal = board()
    state['deals'].insert(0, other_deal)
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': tx_hash, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'payin_hash_already_used'


def test_rejects_payin_amount_mismatch():
    state, deal = board()
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': 'c' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 80}]}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'payin_amount_mismatch'


def test_rejects_missing_evidence_for_non_crypto_payin():
    state, deal = board()
    override = {'reason': REASON,
                'payin': {'method': 'СБП', 'amountUsdt': 100}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager') == 'payin_evidence_missing'


def test_rejects_missing_payout_evidence_for_exchange():
    state, deal = board(type='Обмен валюты')
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': 'd' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'payout': {'source': 'cash', 'amountUsdt': 90}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'payout_evidence_missing'


def test_applies_override_and_logs_reason_on_success():
    state, deal = board(type='Оплата недвижимости', kind='Лизхолд')
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': 'e' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]}}
    result = A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo)
    assert result is None
    assert any(h['hash'] == 'e' * 64 and h.get('verified') is True
               for h in deal['payinHashes'])
    assert REASON in deal['log'][-1]['text']
    assert deal['log'][-1]['role'] == 'manager'


def test_rejects_invalid_agents_shape():
    """Доп. проверка (сверх 9 из брифа): шаг 8 валидации — agents, если
    передан, должен быть списком, а не произвольным значением."""
    state, deal = board(type='Оплата недвижимости', kind='Лизхолд')
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': '2' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'agents': 'not-a-list'}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'agents_invalid'


def test_applies_payout_override_for_exchange_deal():
    """Доп. проверка (сверх 9 из брифа): расходная сторона для exchange-сделки
    применяется аналогично приходной — крипто-хеш расхода тоже проверяется и
    записывается, а не просто принимается на слово."""
    state, deal = board(type='Обмен валюты')
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': 'f' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'payout': {'source': 'coins', 'amountUsdt': 90, 'hashes': [
                    {'hash': '1' * 64, 'network': 'trc20', 'sender': 'TOurWallet1111111111111111',
                     'receiver': 'TClientWallet111111111111', 'amount': 90}]}}
    result = A._stand_manual_close_apply_override(
        state, deal, override, 'admin', verify=confirmed_echo)
    assert result is None
    assert deal['paySrc'] == 'coins'
    assert any(h['hash'] == '1' * 64 for h in deal['payout']['hashes'])
    assert deal['payout']['usdt'] == 90
