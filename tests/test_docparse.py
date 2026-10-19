# -*- coding: utf-8 -*-
"""merge(): склейка полей из паспорта/инвойса/SPA — владение по документам.

Баг (TG «Баги» #808): в «Объект / Property» приложения к договору попадал
российский адрес регистрации клиента вместо адреса объекта из инвойса —
паспорт не владеет property_address, но его значение всё равно оставалось
в fields, потому что инвойс тоже не значился владельцем.
"""
import docparse


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
