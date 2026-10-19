from app import (
    DEAL_KIND_LABELS,
    canonical_deal_kind_from_stand,
    canonical_payin_from_stand,
    canonical_deal_kind_from_legacy,
    canonical_payin_from_legacy,
    is_verified_flow,
)


def test_stand_canonical_mapping_freehold_requisites_verified():
    assert is_verified_flow(
        canonical_deal_kind_from_stand('Оплата недвижимости', 'Фрихолд'),
        canonical_payin_from_stand('По реквизитам'),
    ) is True


def test_stand_canonical_mapping_leasehold_requisites_verified():
    assert is_verified_flow(
        canonical_deal_kind_from_stand('Оплата недвижимости', 'Лизхолд'),
        canonical_payin_from_stand('По реквизитам'),
    ) is True


def test_stand_canonical_mapping_rental_cash_unverified():
    assert is_verified_flow(
        canonical_deal_kind_from_stand('Оплата недвижимости', 'Аренда'),
        canonical_payin_from_stand('Наличные'),
    ) is False


def test_stand_canonical_mapping_exchange_is_unverified():
    assert is_verified_flow(
        canonical_deal_kind_from_stand('Обмен валюты', None),
        canonical_payin_from_stand('СБП'),
    ) is False


def test_legacy_canonical_mapping_mf_realty_flow_sole_verified():
    assert is_verified_flow(
        canonical_deal_kind_from_legacy('mf_realty'),
        canonical_payin_from_legacy('flow_sole_reqs'),
    ) is True


def test_legacy_canonical_mapping_mf_freehold_sber_reqs_verified():
    assert is_verified_flow(
        canonical_deal_kind_from_legacy('mf_freehold'),
        canonical_payin_from_legacy('sber_reqs'),
    ) is True


def test_legacy_canonical_mapping_rental_sber_wl_unverified():
    assert is_verified_flow(
        canonical_deal_kind_from_legacy('rental'),
        canonical_payin_from_legacy('sber_wl'),
    ) is False


def test_legacy_canonical_mapping_exchange_crypto_unverified():
    assert is_verified_flow(
        canonical_deal_kind_from_legacy('exchange'),
        canonical_payin_from_legacy('crypto_direct'),
    ) is False


def test_is_verified_flow_none_inputs_are_unverified():
    assert is_verified_flow(None, 'requisites') is False
    assert is_verified_flow('freehold', None) is False
    assert is_verified_flow(None, None) is False


def test_unknown_native_values_translate_to_none():
    assert canonical_deal_kind_from_stand('Оплата недвижимости', 'НечтоНовое') is None
    assert canonical_payin_from_stand('НечтоНовое') is None
    assert canonical_deal_kind_from_legacy('НечтоНовое') is None
    assert canonical_payin_from_legacy('НечтоНовое') is None


def test_deal_kind_labels_has_rental_for_legacy_crm_analytics_parity():
    assert DEAL_KIND_LABELS.get('rental') == 'Аренда'
