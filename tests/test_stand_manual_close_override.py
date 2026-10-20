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


REALTY_FACTS = {
    'amountThb': 50000, 'companyPct': 1, 'rates': {'usdtThb': 36.0, 'client': 35.0},
    'payTo': {'purpose': 'Оплата аренды виллы'},
    'mfPayout': [{'hash': 'f' * 64, 'net': 'TRC20', 'amount': 1388.89}],
    'docs': {'inv': True, 'receipt': True},
}


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


def test_allows_restating_hash_already_recorded_on_same_deal():
    """СД-1489 на s27: приход уже верифицирован обычным флоу и лежит в
    payinHashes этой же сделки. Менеджер переносит её в CRM через override,
    форма предзаполняет уже известный факт — это не повторное использование
    хеша, это переподтверждение своего же факта. Должно пройти, а не упасть
    с payin_hash_already_used, и не задвоить запись в payinHashes."""
    tx_hash = '9' * 64
    state, deal = board(type='Оплата недвижимости', kind='Лизхолд', **REALTY_FACTS,
                        payinHashes=[{'hash': tx_hash, 'network': 'TRC20', 'amount': 100,
                                      'verified': True}])
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': tx_hash, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]}}
    result = A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo)
    assert result is None
    assert [h['hash'] for h in deal['payinHashes']].count(tx_hash) == 1


def test_rejects_hash_used_by_different_deal_even_when_current_deal_has_its_own_hash():
    """Исключение из дедупа — только для СВОЕЙ сделки. Хеш чужой сделки
    всё ещё реальное повторное использование и отклоняется, даже если
    override этой же заявкой переподтверждает собственный (другой) хеш."""
    own_hash = '9' * 64
    other_hash = 'b' * 64
    other_deal = {'id': 1, 'payinHashes': [{'hash': other_hash, 'network': 'TRC20', 'amount': 100}]}
    state, deal = board(type='Оплата недвижимости', kind='Лизхолд',
                        payinHashes=[{'hash': own_hash, 'network': 'TRC20', 'amount': 100,
                                      'verified': True}])
    state['deals'].insert(0, other_deal)
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': other_hash, 'network': 'trc20',
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


def test_payin_amount_mismatch_tolerance_matches_frontend_payin_tol():
    """Допуск сверки суммы должен совпадать с фронтовой PAYIN_TOL=5 USDT
    (static/stand/tasks.html:9344), а не с допуском в 1 цент/копейку."""
    # Разница $3 — внутри допуска (<=5): проверка прихода проходит целиком.
    state, deal = board(type='Оплата недвижимости', kind='Лизхолд', **REALTY_FACTS)
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': '3' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 97}]}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) is None

    # Разница $6 — вне допуска (>5): отклоняем как mismatch.
    state, deal = board()
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': '4' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 94}]}}
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


def test_rejects_payout_evidence_present_only_as_developer_invoice():
    """'inv' — инвойс застройщика (только для realty), не подходит как
    доказательство расхода exchange-сделки: нужен именно receipt (единый
    слот на фронте для прихода и расхода, Task 5)."""
    state, deal = board(type='Обмен валюты',
                        files={'inv': [{'file': 'invoice.pdf'}]})
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': '5' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'payout': {'source': 'cash', 'amountUsdt': 90}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'payout_evidence_missing'


def test_applies_override_and_logs_reason_on_success():
    state, deal = board(type='Оплата недвижимости', kind='Лизхолд', **REALTY_FACTS)
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
    state, deal = board(type='Оплата недвижимости', kind='Лизхолд', **REALTY_FACTS)
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': '2' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'agents': 'not-a-list'}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'agents_invalid'


def test_rejects_non_dict_override_without_crashing():
    """override сам может быть не-dict истинным значением (строка/список/число) —
    не должно уронить функцию в AttributeError, должен вернуться код ошибки."""
    state, deal = board()
    for bad_override in ('просто строка', [1, 2, 3], 42):
        assert A._stand_manual_close_apply_override(
            state, deal, bad_override, 'manager') == 'manual_override_reason_required'


def test_rejects_non_dict_payin_without_crashing():
    """override['payin'] не-dict истинное значение — не AttributeError на
    payin.get('method'), а обычный код отсутствующего способа прихода."""
    state, deal = board()
    override = {'reason': REASON, 'payin': 'крипта, но строкой'}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager') == 'payin_method_required'


def test_rejects_non_iterable_payin_hashes_without_crashing():
    """override['payin']['hashes'] — не-list истинное значение (например
    int) — не TypeError на `for item in hashes`, а payin_hash_required."""
    state, deal = board()
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': 12345}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager') == 'payin_hash_required'


def test_rejects_non_dict_payout_without_crashing():
    """override['payout'] не-dict истинное значение для exchange-сделки —
    не AttributeError на payout.get('source'), а payout_source_required."""
    state, deal = board(type='Обмен валюты')
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': '6' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'payout': 'наличка, но строкой'}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'payout_source_required'


def test_rejects_non_iterable_payout_hashes_without_crashing():
    """override['payout']['hashes'] — не-list истинное значение — не
    TypeError, а payout_hash_required."""
    state, deal = board(type='Обмен валюты')
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': '7' * 64, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'payout': {'source': 'coins', 'amountUsdt': 90, 'hashes': {'not': 'a list'}}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'payout_hash_required'


def test_rejects_hash_reused_between_payin_and_payout_in_same_submission():
    """Топовый риск-сценарий из плана: один и тот же хеш подсунут и как приход,
    и как расход в одной заявке — должен быть отклонён, а не засчитан дважды."""
    tx_hash = '8' * 64
    state, deal = board(type='Обмен валюты')
    override = {'reason': REASON,
                'payin': {'method': 'Крипта', 'amountUsdt': 100, 'hashes': [
                    {'hash': tx_hash, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]},
                'payout': {'source': 'coins', 'amountUsdt': 100, 'hashes': [
                    {'hash': tx_hash, 'network': 'trc20',
                     'receiver': 'TReceiverWallet111111111111', 'amount': 100}]}}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) == 'payout_hash_already_used'


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


def test_manager_manual_close_rental_cash_accepts_verified_facts_and_corrections():
    """Менеджер переносит существующую аренду за наличные, минуя гейт новой заявки.

    Прибыль берёт скорректированный инвойс и реальный USDT, а расходный хеш
    становится фактом MF Corp только после сетевой проверки.
    """
    state, deal = board(type='Оплата недвижимости', kind='Аренда', payType='Наличные',
                        amountRub=1217600, **{**REALTY_FACTS, 'mfPayout': []})
    override = {'reason': REASON,
                'payin': {'method': 'Наличные', 'amountRub': 1217600,
                          'amountUsdt': 14500, 'manualBankConfirmed': True},
                'payout': {'amountUsdt': 13800, 'hashes': [
                    {'hash': '9' * 64, 'network': 'trc20',
                     'receiver': 'TCompanyWallet111111111111', 'amount': 13800}]},
                'realty': {'invoiceThb': 455000, 'buyRate': 33.42,
                           'sellRate': None, 'companyPercent': 1},
                'agents': []}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=confirmed_echo) is None
    assert deal['payType'] == 'Наличные' and deal['amountUsdt'] == 14500
    assert deal['amountThb'] == 455000 and deal['rates']['usdtThb'] == 33.42
    assert deal['manualRealtySellRate'] is None
    assert deal['mfPayout'][0]['hash'] == '9' * 64
    assert deal['mfPayout'][0]['verified'] is True
    actual = A.compute_mf_realty(455000, 33.42, 14500,
                                  company_percent=1, actual_cost_usdt=13800)
    assert actual['net_profit_usdt'] < 14500


def test_manual_close_rental_rejects_unverified_mf_transfer():
    state, deal = board(type='Оплата недвижимости', kind='Аренда', payType='Наличные',
                        **{**REALTY_FACTS, 'mfPayout': []})
    override = {'reason': REASON,
                'payin': {'method': 'Наличные', 'amountUsdt': 14500,
                          'manualBankConfirmed': True},
                'payout': {'amountUsdt': 13800, 'hashes': [
                    {'hash': '9' * 64, 'network': 'trc20', 'amount': 13800}]},
                'realty': {'invoiceThb': 455000, 'buyRate': 33.42,
                           'sellRate': None, 'companyPercent': 1}}
    def pending(*_args):
        return {'status': 'pending'}
    assert A._stand_manual_close_apply_override(
        state, deal, override, 'manager', verify=pending) == 'payout_hash_unverified'
    assert deal['mfPayout'] == []
