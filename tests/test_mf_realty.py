"""
Сделки по недвижимости через MF Corporation (leasehold).

Спека: docs/specs/2026-08-04-mf-corp-leasehold.md
Эталон — таблица «Cделки недвижимость», листы май–июль: все ожидаемые числа
взяты из реальных строк, а не придуманы.

Суть: деньги расходятся по двум карманам — комиссия оседает в батах на счёте
тайской компании, остаток остаётся прибылью в USDT. Чистый доход = сумма обоих.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_mf_realty.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Deal, Client, AdminUser, DealAgent, Referrer,
                 compute_mf_realty, suggest_company_percent, compute_agent_cascade)
import secrets


def approx(a, b, eps=0.02):
    return abs((a or 0) - b) < eps


# ── Фикстуры ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(DealAgent).delete()
        s.query(Deal).delete()
        s.query(Client).delete()
        s.query(Referrer).delete()
        s.commit()
    finally:
        s.close()
    yield


@pytest.fixture
def db():
    s = get_session()
    yield s
    s.close()


@pytest.fixture
def tc():
    app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='test_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = aid
        yield c


# ── Расчёт против реальных строк таблицы ─────────────────────────────────

class TestAgainstSheet:
    """Каждый тест — строка из Google-таблицы. Числа обязаны совпадать до цента."""

    def test_july_nahodkina(self):
        """июль · находкина bho property · rub-thb, агент фиксом $323."""
        r = compute_mf_realty(622370, 33.22, 19929.17, company_percent=1,
                              agents=[{'tier': 1, 'comp_model': 'fixed', 'fixed_usdt': 323.00}])
        assert approx(r['invoice_cost_usdt'], 18734.80)
        assert approx(r['cost_usdt'], 18922.15), 'с кошелька уходит инвойс + комиссия'
        assert approx(r['gross_profit_usdt'], 1194.37)
        assert approx(r['company_fee_thb'], 6223.70)
        assert approx(r['company_fee_usdt'], 187.35)
        assert approx(r['crypto_remainder_usdt'], 684.02)
        assert approx(r['net_profit_usdt'], 871.37)

    def test_july_vladimir_no_agent(self):
        """июль · Владимир Гавриш · без агента: весь доход делится на два кармана."""
        r = compute_mf_realty(2647300, 33.37, 81780.00, company_percent=1, agents=[])
        assert approx(r['gross_profit_usdt'], 2448.26)
        assert approx(r['company_fee_usdt'], 793.32)
        assert approx(r['crypto_remainder_usdt'], 1654.95)
        assert approx(r['net_profit_usdt'], 2448.26)

    def test_june_julia_payin_from_sell_rate(self):
        """июнь · grusha & julia · приход выводится из курса продажи."""
        r = compute_mf_realty(390360, 33.24, None, sell_rate=32.53, company_percent=1,
                              agents=[{'tier': 1, 'comp_model': 'fixed', 'fixed_usdt': 41.10}])
        assert approx(r['payin_usdt'], 12000.00)
        assert approx(r['invoice_cost_usdt'], 11743.68)
        assert approx(r['crypto_remainder_usdt'], 97.78)
        assert approx(r['net_profit_usdt'], 215.22)

    def test_may_amal_percent_from_fact(self):
        """май · Amal Property · процент выводится ОБРАТНО из отправленной суммы."""
        r = compute_mf_realty(2600000, 32.41, 81037.35, company_sent_thb=2626996.55, agents=[])
        assert approx(r['company_fee_thb'], 26996.55)
        assert approx(r['company_percent'], 1.0383, eps=0.001)
        assert approx(r['company_fee_usdt'], 832.97)
        assert approx(r['gross_profit_usdt'], 815.20)

    def test_fact_wins_over_percent(self):
        """Заданы обе стороны — фактическая сумма приоритетнее процента."""
        r = compute_mf_realty(1000000, 33.0, 31000, company_percent=1,
                              company_sent_thb=1005000, agents=[])
        assert approx(r['company_fee_thb'], 5000)
        assert approx(r['company_percent'], 0.5)


# ── Два кармана ───────────────────────────────────────────────────────────

class TestTwoPockets:
    def test_net_equals_crypto_plus_company(self):
        """Главное тождество: чистый доход = крипта + компания."""
        r = compute_mf_realty(622370, 33.22, 19929.17, company_percent=1,
                              agents=[{'tier': 1, 'comp_model': 'fixed', 'fixed_usdt': 323.00}])
        assert approx(r['net_profit_usdt'], r['crypto_remainder_usdt'] + r['company_fee_usdt'])

    def test_bigger_company_percent_shrinks_crypto(self):
        """Больше процент компании → меньше остаётся в крипте, чистый доход тот же."""
        low = compute_mf_realty(1000000, 33.0, 31000, company_percent=0.5, agents=[])
        high = compute_mf_realty(1000000, 33.0, 31000, company_percent=1.5, agents=[])
        assert high['crypto_remainder_usdt'] < low['crypto_remainder_usdt']
        assert approx(high['net_profit_usdt'], low['net_profit_usdt'])

    def test_company_percent_neutral_without_crypto_share(self):
        """Без партнёра на крипте процент компании — просто дележ карманов."""
        ag = [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5}]
        low = compute_mf_realty(16742400, 33.20, 512000, company_percent=0.5, agents=ag)
        high = compute_mf_realty(16742400, 33.20, 512000, company_percent=0.9, agents=ag)
        assert approx(low['net_profit_usdt'], high['net_profit_usdt'])

    def test_company_percent_trades_against_crypto_share_partner(self):
        """С партнёром на крипте процент компании перестаёт быть нейтральным.

        Меньше оставили компании → больше осталось в крипте → больше забрал
        партнёр → меньше наш чистый доход. Это не баг, а следствие базы:
        сначала считается, сколько осело в компании, и только остаток делится.
        """
        ag = [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5},
              {'tier': 2, 'comp_model': 'crypto_share', 'percent': 10}]
        low = compute_mf_realty(16742400, 33.20, 512000, company_percent=0.5, agents=ag)
        high = compute_mf_realty(16742400, 33.20, 512000, company_percent=0.9, agents=ag)
        assert low['agents'][1]['_payout'] > high['agents'][1]['_payout']
        assert low['net_profit_usdt'] < high['net_profit_usdt']
        assert approx(low['net_profit_usdt'], 4887.90)
        assert approx(high['net_profit_usdt'], 5089.62)

    def test_zero_percent_all_in_crypto(self):
        r = compute_mf_realty(1000000, 33.0, 31000, company_percent=0, agents=[])
        assert r['company_fee_usdt'] == 0
        assert approx(r['crypto_remainder_usdt'], r['gross_profit_usdt'])
        assert approx(r['cost_usdt'], r['invoice_cost_usdt'])

    def test_cost_includes_company_fee(self):
        """Себестоимость = вся отправка: баты покупаем вместе с комиссией."""
        r = compute_mf_realty(16742400, 33.20, 511968.69, company_percent=0.9, agents=[])
        assert approx(r['company_sent_thb'], 16893081.60)
        assert approx(r['cost_usdt'], 508827.76), 'проверка по арифметике Карима'
        assert approx(r['crypto_profit_usdt'], 3140.93)
        assert approx(r['net_profit_usdt'], 7679.53)

    def test_client_rate_from_spread(self):
        """Курс клиенту = наш курс минус спред: 33.20 − 1.5% = 32.702."""
        from app import client_sell_rate
        assert approx(client_sell_rate(33.20, 1.5), 32.702, eps=0.0005)
        r = compute_mf_realty(16742400, 33.20, None, sell_rate=client_sell_rate(33.20, 1.5),
                              company_percent=0.9, agents=[])
        assert approx(r['payin_usdt'], 511968.69)


# ── Выплаты партнёрам ────────────────────────────────────────────────────

class TestAgents:
    def test_crypto_share_base_excludes_company_fee(self):
        """crypto_share берёт % от того, что в крипте, а не от валовой прибыли."""
        r = compute_mf_realty(1000000, 33.0, 31000, company_percent=1,
                              agents=[{'tier': 1, 'comp_model': 'crypto_share', 'percent': 10}])
        assert approx(r['agents'][0]['_payout'], round(r['crypto_profit_usdt'] * 0.1, 2))

    def test_revshare_would_overpay(self):
        """Тот же процент через revshare даёт больше — это и есть переплата партнёру."""
        crypto = compute_mf_realty(1000000, 33.0, 31000, company_percent=1,
                                   agents=[{'tier': 1, 'comp_model': 'crypto_share', 'percent': 10}])
        rev = compute_mf_realty(1000000, 33.0, 31000, company_percent=1,
                                agents=[{'tier': 1, 'comp_model': 'revshare', 'percent': 10}])
        assert rev['agents'][0]['_payout'] > crypto['agents'][0]['_payout']

    def test_sid_valera_cascade(self):
        """Кейс #458: SID 0.5% от объёма (ур.1) + Валера 10% от остатка (ур.2)."""
        r = compute_mf_realty(16742400, 33.20, 512000, company_percent=0.9, agents=[
            {'tier': 1, 'comp_model': 'markup', 'percent': 0.5},
            {'tier': 2, 'comp_model': 'crypto_share', 'percent': 10},
        ])
        sid, valera = r['agents']
        assert approx(sid['_payout'], 512000 * 0.005)          # $2 560 от объёма
        crypto_after_sid = r['crypto_profit_usdt'] - sid['_payout']
        assert approx(valera['_payout'], round(max(crypto_after_sid, 0) * 0.1, 2))
        assert approx(r['net_profit_usdt'],
                      r['crypto_remainder_usdt'] + r['company_fee_usdt'])

    def test_no_negative_payout_when_profit_unknown(self):
        """R9: прибыль ещё 0, ур.1 уже взял markup → ур.2 получает 0, а не минус."""
        res, _ = compute_agent_cascade(0, 512000, [
            {'tier': 1, 'comp_model': 'markup', 'percent': 0.5},
            {'tier': 2, 'comp_model': 'revshare', 'percent': 10},
        ])
        assert res[0]['_payout'] == 2560.0
        assert res[1]['_payout'] == 0.0, 'до фикса тут было -256.00'

    def test_negative_base_crypto_share_also_zero(self):
        res, _ = compute_agent_cascade(0, 100000, [
            {'tier': 1, 'comp_model': 'markup', 'percent': 1},
            {'tier': 2, 'comp_model': 'crypto_share', 'percent': 50},
        ], crypto_base_usdt=-500)
        assert res[1]['_payout'] == 0.0

    def test_ordinary_deals_unchanged(self):
        """Регресс: обычный каскад без crypto_base работает как раньше."""
        res, net = compute_agent_cascade(2793.15, 58409, [
            {'tier': 1, 'comp_model': 'revshare', 'percent': 20},
            {'tier': 2, 'comp_model': 'revshare', 'percent': 50},
        ])
        assert res[0]['_payout'] == 558.63
        assert res[1]['_payout'] == 1117.26
        assert net == 1117.26


# ── Подбор процента компании ─────────────────────────────────────────────

class TestSuggestPercent:
    def test_suggested_percent_leaves_enough_for_agents(self):
        """Кейс «поставлю 0.9, потому что Валере ещё платить» — считает система."""
        agents = [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5},
                  {'tier': 2, 'comp_model': 'crypto_share', 'percent': 10}]
        pct = suggest_company_percent(16742400, 33.20, 512000, agents=agents)
        r = compute_mf_realty(16742400, 33.20, 512000, company_percent=pct, agents=agents)
        assert r['crypto_remainder_usdt'] >= -0.01, 'дефицита быть не должно'
        assert r['crypto_shortfall_usdt'] == 0

    def test_suggested_is_maximum_possible(self):
        """Подсказка — именно максимум: чуть больше уже уводит в минус."""
        agents = [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5}]
        pct = suggest_company_percent(16742400, 33.20, 512000, agents=agents)
        higher = compute_mf_realty(16742400, 33.20, 512000, company_percent=pct + 0.05,
                                   agents=agents)
        assert higher['crypto_remainder_usdt'] < 0

    def test_no_profit_no_percent(self):
        """Прибыли нет (курсы сошлись), а агент берёт markup — подсказка 0%.

        Дефицит при этом остаётся: markup партнёра больше валового дохода.
        Система не выдумывает процент, которого не существует.
        """
        agents = [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5}]
        assert suggest_company_percent(16742400, 32.70, 512000, agents=agents) == 0.0

    def test_too_big_percent_flags_shortfall(self):
        """Перебор процента → отрицательный остаток и явный признак дефицита."""
        r = compute_mf_realty(16742400, 33.20, 512000, company_percent=5,
                              agents=[{'tier': 1, 'comp_model': 'markup', 'percent': 0.5}])
        assert r['crypto_remainder_usdt'] < 0
        assert r['crypto_shortfall_usdt'] < 0

    def test_keep_usdt_reserves_extra(self):
        base = suggest_company_percent(1000000, 33.0, 31000, agents=[])
        with_keep = suggest_company_percent(1000000, 33.0, 31000, agents=[], keep_usdt=100)
        assert with_keep < base

    def test_no_rates_returns_zero(self):
        assert suggest_company_percent(0, 0, 0) == 0.0


# ── API ───────────────────────────────────────────────────────────────────

def _mf_payload(**extra):
    data = {
        'client_name': 'MF Realty Client',
        'deal_kind': 'mf_realty',
        'deal_type': 'pay_in',
        'payin_method': 'crypto_direct',
        'payin_amount_usdt': 19929.17,
        'realty_purpose': 'находкина bho property',
        'invoice_amount_thb': 622370,
        'buy_rate_thb_usdt': 33.22,
        'company_percent': 1,
    }
    data.update(extra)
    return data


class TestApi:
    def test_create_computes_pockets(self, tc):
        deal = tc.post('/api/deals', json=_mf_payload()).json['deal']
        assert deal['deal_kind'] == 'mf_realty'
        assert approx(deal['company_fee_thb'], 6223.70)
        assert approx(deal['company_fee_usdt'], 187.35)
        assert approx(deal['profit_usdt'], 1007.02), 'прибыль сделки = то, что в крипте'
        assert approx(deal['crypto_remainder_usdt'], 1007.02)   # без агентов
        assert approx(deal['net_profit_usdt'], 1194.37), 'чистый = крипта + компания'

    def test_create_with_agents(self, tc):
        deal = tc.post('/api/deals', json=_mf_payload(agents=[
            {'tier': 1, 'comp_model': 'fixed', 'fixed_usdt': 323.00, 'name': 'Агент'},
        ])).json['deal']
        assert approx(deal['crypto_remainder_usdt'], 684.02)
        assert approx(deal['net_profit_usdt'], 871.37)

    def test_not_queued_for_reimbursement(self, tc):
        """Платим со своего кошелька — в очередь возмещения фаундеру не попадаем."""
        deal = tc.post('/api/deals', json=_mf_payload()).json['deal']
        assert deal['needs_reimbursement'] is False

    def test_update_recalculates(self, tc):
        did = tc.post('/api/deals', json=_mf_payload()).json['deal']['id']
        deal = tc.put(f'/api/deals/{did}', json={'company_percent': 0.5}).json['deal']
        assert approx(deal['company_fee_thb'], 3111.85)
        assert approx(deal['net_profit_usdt'], 1194.37), 'чистый доход не зависит от процента'
        assert approx(deal['crypto_remainder_usdt'], 1100.71)
        assert approx(deal['payout_amount_usdt'], 18828.47), 'с кошелька ушла вся отправка'

    def test_update_by_fact_overrides_percent(self, tc):
        """Прислали фактическую сумму отправки — процент выводится из неё."""
        did = tc.post('/api/deals', json=_mf_payload()).json['deal']['id']
        deal = tc.put(f'/api/deals/{did}', json={'company_sent_thb': 630000}).json['deal']
        assert approx(deal['company_fee_thb'], 7630)
        assert approx(deal['company_percent'], 1.2259, eps=0.001)

    def test_update_keeps_agents(self, tc):
        did = tc.post('/api/deals', json=_mf_payload(agents=[
            {'tier': 1, 'comp_model': 'fixed', 'fixed_usdt': 323.00, 'name': 'Агент'},
        ])).json['deal']['id']
        deal = tc.put(f'/api/deals/{did}', json={'company_percent': 1}).json['deal']
        assert len(deal['agents']) == 1
        assert approx(deal['crypto_remainder_usdt'], 684.02)

    def test_ordinary_deal_untouched(self, tc):
        """Регресс: обычная сделка считается как раньше и не получает поля MF."""
        deal = tc.post('/api/deals', json={
            'client_name': 'Ordinary', 'deal_type': 'pay_in', 'payin_method': 'crypto_direct',
            'payin_amount_usdt': 1000, 'payout_amount_usdt': 970, 'payout_method': 'transfer',
        }).json['deal']
        assert deal['deal_kind'] == 'exchange'
        assert deal['company_fee_usdt'] is None
        assert approx(deal['profit_usdt'], 30)

    def test_preview_endpoint(self, tc):
        r = tc.post('/api/deals/mf-realty/preview', json={
            'invoice_amount_thb': 622370, 'buy_rate_thb_usdt': 33.22,
            'payin_amount_usdt': 19929.17, 'company_percent': 1,
        }).json
        assert r['success']
        assert approx(r['result']['net_profit_usdt'], 1194.37)
        assert 'suggested_company_percent' in r['result']

    def test_preview_bad_input(self, tc):
        r = tc.post('/api/deals/mf-realty/preview', json={'invoice_amount_thb': 'abc'})
        assert r.status_code == 400
