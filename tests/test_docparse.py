# -*- coding: utf-8 -*-
"""merge(): склейка полей из паспорта/инвойса/SPA — владение по документам.

Баг (TG «Баги» #808): в «Объект / Property» приложения к договору попадал
российский адрес регистрации клиента вместо адреса объекта из инвойса —
паспорт не владеет property_address, но его значение всё равно оставалось
в fields, потому что инвойс тоже не значился владельцем.
"""
import docparse


def test_vehicle_contract_and_invoice_keep_roles_and_surface_conflict():
    contract = {'_kind': 'vehicle_contract', '_file': 'vehicle_contract',
                'vehicle_model': 'Test Model', 'vehicle_vin': 'QA-VIN-1',
                'seller_name': 'Seller Ltd.', 'seller_id': 'REG-1',
                'vehicle_contract_total': '100000 USD'}
    invoice = {'_kind': 'auto_invoice', '_file': 'auto_invoice',
               'recipient_name': 'Payment Partner Ltd.', 'seller_name': 'Other Seller Ltd.',
               'invoice_amount': '20000', 'invoice_currency': 'USD'}
    merged = docparse.merge([contract, invoice])
    assert merged['fields']['seller_name'] == 'Seller Ltd.'
    assert merged['fields']['recipient_name'] == 'Payment Partner Ltd.'
    assert merged['fields']['vehicle_contract_total'] == '100000 USD'
    assert merged['fields']['invoice_amount'] == '20000'
    assert 'seller_name' in merged['conflicts']


def _result(file, kind, **fields):
    res = {k: None for k in docparse.FIELD_DEFS}
    res.update(fields)
    res['_file'] = file
    res['_kind'] = kind
    res['masked_fields'] = []
    return res


def test_invoice_property_address_wins_over_passport_russian_address():
    passport = _result('passport.png', 'passport',
                       client_name_ru='Иванов Иван',
                       property_address='59, Building 57, Apartment 53, Krasnoyarsk, Shchorsa Street')
    invoice = _result('invoice.png', 'invoice',
                      project_name='Origin Residences Phuket Bangtao',
                      unit_no='C309',
                      property_address='Origin Residences, Bangtao, Phuket')
    merged = docparse.merge([passport, invoice])
    assert merged['fields']['property_address'] == 'Origin Residences, Bangtao, Phuket'
    assert merged['provenance']['property_address'] == 'invoice.png'
    assert 'property_address' not in merged['conflicts']


def test_invoice_property_address_wins_regardless_of_upload_order():
    passport = _result('passport.png', 'passport',
                       property_address='59, Building 57, Apartment 53, Krasnoyarsk, Shchorsa Street')
    invoice = _result('invoice.png', 'invoice',
                      property_address='Origin Residences, Bangtao, Phuket')
    merged = docparse.merge([invoice, passport])
    assert merged['fields']['property_address'] == 'Origin Residences, Bangtao, Phuket'
    assert merged['provenance']['property_address'] == 'invoice.png'


def test_spa_still_owns_property_address_when_invoice_absent():
    spa = _result('spa.png', 'spa', property_address='Origin Residences, Bangtao, Phuket')
    merged = docparse.merge([spa])
    assert merged['fields']['property_address'] == 'Origin Residences, Bangtao, Phuket'
