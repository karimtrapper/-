"""payTo в договоре берётся из кошелька единого реестра CRM, а не из отдельного
справочника задачника. Проверяем _stand_doc_request (собирает money-поля для
генератора документов) на крипто-сделке с walletId из реестра и с легаси-id.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_wallet_registry_docfields.py -v
"""
import pytest

from app import Wallet, get_session, _stand_doc_request


GRUSHA = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
TEODOR = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'

BASE_F = {'fio': 'Иван Иванов', 'passNo': '1234 567890',
          'amountThb': '2000', 'amountPay': '20', 'rate': '100'}


@pytest.fixture(autouse=True)
def clean_wallets():
    s = get_session()
    try:
        s.query(Wallet).delete()
        s.commit()
    finally:
        s.close()
    yield


def test_payto_resolves_from_registry_wallet_by_id():
    s = get_session()
    try:
        w = Wallet(address=TEODOR, blockchain='TRON', owner='Теодор',
                  is_multisig=False, accepts_payin=True)
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    deal = {'type': 'Обмен', 'payType': 'Крипта', 'walletId': str(wid)}
    result = _stand_doc_request({}, deal, BASE_F)
    assert 'error' not in result, result
    money = result['money']
    assert money['payin_wallet'] == TEODOR
    assert money['payin_network'] == 'TRON (TRC-20)'
    assert money['payin_recipient'] == 'Теодор'


def test_payto_resolves_from_legacy_grusha_id_as_company():
    s = get_session()
    try:
        s.add(Wallet(address=GRUSHA, blockchain='TRON', owner='компания',
                     is_multisig=True, accepts_payin=True))
        s.commit()
    finally:
        s.close()
    deal = {'type': 'Обмен', 'payType': 'Крипта', 'walletId': 'grusha'}
    result = _stand_doc_request({}, deal, BASE_F)
    assert 'error' not in result, result
    money = result['money']
    assert money['payin_wallet'] == GRUSHA
    assert money['payin_recipient'] == 'MF Corporation Company Limited'
    assert money['payin_recipient_role'] == 'Агент / Agent'


def test_payto_missing_when_wallet_not_accepting_payin():
    s = get_session()
    try:
        w = Wallet(address=TEODOR, blockchain='TRON', owner='Теодор', accepts_payin=False)
        s.add(w)
        s.commit()
        wid = w.id
    finally:
        s.close()
    deal = {'type': 'Обмен', 'payType': 'Крипта', 'walletId': str(wid)}
    result = _stand_doc_request({}, deal, BASE_F)
    assert result.get('error') == 'missing_fields'
    assert 'payTo' in result.get('fields', [])
