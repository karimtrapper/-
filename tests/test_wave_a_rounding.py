"""Exhaustive decimal parity against the UI for both audited tariffs."""
import hashlib
import subprocess
from decimal import Decimal, ROUND_HALF_UP
import stand_prepay


def test_all_integer_invoices_100000_through_1000000_both_tariffs():
    result = subprocess.run(['node', 'tests/test_wave_a_rounding.js'], capture_output=True, text=True, check=True)
    hashes = dict(line.split() for line in result.stdout.splitlines())
    for tariff, percent in [('soft', Decimal('.015')), ('bank', Decimal('.008'))]:
        expected = hashlib.sha256()
        for invoice in range(100000, 1000001):
            fee = (Decimal(invoice)*percent+50).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            expected.update(f'{Decimal(invoice)+fee:.2f}\n'.encode())
        assert hashes[tariff] == expected.hexdigest(), tariff
    assert stand_prepay.amount({'invoiceUsd': 941, 'ippsTariff': 'soft'}) == 1005.12
    assert stand_prepay.amount({'invoiceUsd': 133205, 'ippsTariff': 'soft'}) == 135253.08
