"""Legacy task migration must not reclassify a deal's origin."""
import copy

import app as A


def board(manual_marker=None):
    deal = {'id': 31, 'step': 's14', 'type': 'Оплата недвижимости',
            'kind': 'Лизхолд', 'pay': {}, 'log': []}
    if manual_marker is not None:
        deal['manual'] = manual_marker
    return {'deals': [deal], 'convs': [], 'notes': []}


def test_legacy_absent_manual_accepts_browser_false():
    before = board()
    after = copy.deepcopy(before)
    after['deals'][0].update(manual=False, step='s22')
    assert A._stand_guard_transition(before, after, actor='manager') is None


def test_manual_origin_spoof_still_rejected():
    before = board(True)
    before['deals'][0]['originMode'] = 'manual'
    after = copy.deepcopy(before)
    after['deals'][0]['manual'] = False
    assert A._stand_guard_transition(before, after, actor='manager') == (
        'Происхождение сделки нельзя изменить')


def test_legacy_cannot_be_promoted_to_manual():
    before = board()
    after = copy.deepcopy(before)
    after['deals'][0]['manual'] = True
    assert A._stand_guard_transition(before, after, actor='manager') == (
        'Происхождение сделки нельзя изменить')
