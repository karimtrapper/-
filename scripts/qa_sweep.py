"""Сквозная проверка флоу CalcCRM на локальном стенде (без авторизации).

Прогоняет каждый сценарий целиком через API и сверяет числа, чтобы юзер
не наткнулся на баги руками. Всё созданное удаляется в конце.
"""
import json
import urllib.request

BASE = 'http://localhost:5055'
created_deals, created_refs, created_reimb = [], [], []
results = []


def api(method, path, body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {'success': False, 'error': f'HTTP {e.code}: {e.read().decode()[:200]}'}


def check(name, cond, detail=''):
    results.append((bool(cond), name, detail))
    print(('  ✅ ' if cond else '  ❌ ') + name + (f'  → {detail}' if detail and not cond else ''))


def approx(a, b, eps=0.02):
    return abs((a or 0) - b) < eps


def deal(**kw):
    r = api('POST', '/api/deals', kw)
    if r.get('success'):
        created_deals.append(r['deal']['id'])
        return r['deal']
    return {'_error': r.get('error')}


print('\n══ 1. Партнёры ══')
# удаление реферера мягкое (active=False), код остаётся занят — на повторном
# прогоне переиспользуем существующего и снова включаем его
existing = {r['code']: r for r in api('GET', '/api/referrers').get('referrers', [])}
all_refs = {r['code']: r for r in api('GET', '/api/referrers?include_inactive=1').get('referrers', [])}
ids = []
for p in [{'name': 'QA SID', 'code': 'GR-QASID', 'default_percent': 0.5,
           'comp_model': 'markup', 'markup_percent': 0.5},
          {'name': 'QA Valera', 'code': 'GR-QAVAL', 'default_percent': 10}]:
    r = api('POST', '/api/referrers', p)
    if r.get('success'):
        rid = r['referrer']['id']
        created_refs.append(rid)
    else:
        prev = existing.get(p['code']) or all_refs.get(p['code'])
        if not prev:
            ids.append(None); continue
        rid = prev['id']
        api('PUT', f'/api/referrers/{rid}', {'active': True})   # вернуть в строй
    ids.append(rid)
check('партнёры готовы', all(i is not None for i in ids), ids)
sid_id, val_id = (ids + [None, None])[:2]

print('\n══ 2. Сделка MF Corp: полный расчёт ══')
d = deal(client_name='QA MF', deal_kind='mf_realty', deal_type='pay_in',
         payin_method='crypto_direct', payin_amount_usdt=512000,
         realty_purpose='QA Villa', invoice_amount_thb=16742400,
         buy_rate_thb_usdt=33.20, client_spread_percent=1.5,
         sell_rate_thb_usdt=32.702, company_percent=0.9,
         doc_invoice_url='https://x/inv',
         agents=[{'referrer_id': sid_id, 'name': 'QA SID', 'tier': 1,
                  'comp_model': 'markup', 'percent': 0.5},
                 {'referrer_id': val_id, 'name': 'QA Valera', 'tier': 2,
                  'comp_model': 'crypto_share', 'percent': 10}])
check('сделка создана', 'id' in d, d.get('_error', ''))
if 'id' in d:
    check('отправлено в компанию ฿16 893 081.60', approx(d['company_sent_thb'], 16893081.60), d.get('company_sent_thb'))
    check('ушло с кошелька $508 827.76', approx(d['payout_amount_usdt'], 508827.76), d.get('payout_amount_usdt'))
    check('осталось в крипте $3 172.24', approx(d['profit_usdt'], 3172.24), d.get('profit_usdt'))
    check('комиссия компании $4 538.60', approx(d['company_fee_usdt'], 4538.60), d.get('company_fee_usdt'))
    ags = {a['tier']: a for a in d.get('agents') or []}
    check('SID ур.1 = $2 560.00', approx(ags.get(1, {}).get('payout_usdt'), 2560.00), ags.get(1, {}).get('payout_usdt'))
    check('Valera ур.2 = $61.22', approx(ags.get(2, {}).get('payout_usdt'), 61.22), ags.get(2, {}).get('payout_usdt'))
    check('останется в крипте $551.02', approx(d['crypto_remainder_usdt'], 551.02), d.get('crypto_remainder_usdt'))
    check('чистый доход $5 089.62', approx(d['net_profit_usdt'], 5089.62), d.get('net_profit_usdt'))
    check('тождество: чистый = крипта + компания',
          approx(d['net_profit_usdt'], d['crypto_remainder_usdt'] + d['company_fee_usdt']))
    check('возмещение фаундеру не нужно', d['needs_reimbursement'] is False)
    check('документы сохранены', d.get('doc_invoice_url') == 'https://x/inv')
    check('спред сохранён', approx(d.get('client_spread_percent'), 1.5))

print('\n══ 3. Правка процента и обратный ввод ══')
if 'id' in d:
    u = api('PUT', f"/api/deals/{d['id']}", {'company_percent': 0.5})['deal']
    check('процент 0.5% пересчитал комиссию', approx(u['company_fee_thb'], 83712.0), u.get('company_fee_thb'))
    # с партнёром на крипте процент компании НЕ нейтрален — он меняет его выплату
    check('чистый доход упал (партнёр на крипте забрал больше)',
          approx(u['net_profit_usdt'], 4887.90), u.get('net_profit_usdt'))
    check('агенты уцелели после правки', len(u.get('agents') or []) == 2)
    u2 = api('PUT', f"/api/deals/{d['id']}", {'company_sent_thb': 16893081.60})['deal']
    check('факт отправки вывел процент 0.90%', approx(u2['company_percent'], 0.90, 0.005), u2.get('company_percent'))

print('\n══ 4. Подбор процента ══')
prev = api('POST', '/api/deals/mf-realty/preview', {
    'invoice_amount_thb': 16742400, 'buy_rate_thb_usdt': 33.20,
    'payin_amount_usdt': 512000,
    'agents': [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5},
               {'tier': 2, 'comp_model': 'crypto_share', 'percent': 10}]})
check('превью считается', prev.get('success'), prev.get('error'))
if prev.get('success'):
    pct = prev['result']['suggested_company_percent']
    r2 = api('POST', '/api/deals/mf-realty/preview', {
        'invoice_amount_thb': 16742400, 'buy_rate_thb_usdt': 33.20,
        'payin_amount_usdt': 512000, 'company_percent': pct,
        'agents': [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5},
                   {'tier': 2, 'comp_model': 'crypto_share', 'percent': 10}]})['result']
    check('подобранный процент не уводит в минус', r2['crypto_remainder_usdt'] >= -0.01, r2['crypto_remainder_usdt'])
    check('дефицита нет', r2['crypto_shortfall_usdt'] == 0)
    over = api('POST', '/api/deals/mf-realty/preview', {
        'invoice_amount_thb': 16742400, 'buy_rate_thb_usdt': 33.20,
        'payin_amount_usdt': 512000, 'company_percent': pct + 0.5,
        'agents': [{'tier': 1, 'comp_model': 'markup', 'percent': 0.5}]})['result']
    check('перебор процента даёт дефицит', over['crypto_shortfall_usdt'] < 0)

print('\n══ 5. Обычная сделка (регресс) ══')
o = deal(client_name='QA Ordinary', deal_type='pay_in', payin_method='crypto_direct',
         payin_amount_usdt=1000, payout_amount_usdt=970, payout_method='transfer')
check('обычная сделка создана', 'id' in o, o.get('_error', ''))
if 'id' in o:
    check('тип exchange', o['deal_kind'] == 'exchange', o.get('deal_kind'))
    check('прибыль 30', approx(o['profit_usdt'], 30), o.get('profit_usdt'))
    check('поля MF пустые', o['company_fee_usdt'] is None and o['crypto_remainder_usdt'] is None)

print('\n══ 6. Приход крипты частями ══')
H = ['aa' * 32, 'bb' * 32, 'cc' * 32]
pp = deal(client_name='QA Parts', deal_type='pay_in', payin_method='crypto_direct',
          payin_amount_usdt=300000, payout_amount_usdt=295000, payout_method='transfer',
          payin_tx_hashes=[{'hash': H[0], 'amount_usdt': 200000},
                           {'hash': H[1], 'amount_usdt': 100000}])
check('сделка с частями создана', 'id' in pp, pp.get('_error', ''))
if 'id' in pp:
    check('две части сохранены', len(pp.get('payin_tx_hashes') or []) == 2)
    check('первый хэш в легаси-поле', pp.get('payin_tx_hash') == H[0])

print('\n══ 7. Реферальный код резолвится ══')
rc = deal(client_name='QA RefCode', deal_type='pay_in', payin_method='crypto_direct',
          payin_amount_usdt=1000, payout_amount_usdt=900, payout_method='transfer',
          referrer_name='GRQASID')
check('код GRQASID найден по нормализации', rc.get('referrer_id') == sid_id, rc.get('referrer_name'))
check('имя партнёра подставлено', rc.get('referrer_name') == 'QA SID', rc.get('referrer_name'))
bad = deal(client_name='QA NoCode', deal_type='pay_in', payin_method='crypto_direct',
           payin_amount_usdt=1000, payout_amount_usdt=900, payout_method='transfer',
           referrer_name='GR-NETAKOGO')
check('незарегистрированный код остаётся текстом',
      bad.get('referrer_id') is None and bad.get('referrer_name') == 'GR-NETAKOGO')

print('\n══ 8. Возмещение фаундеру ══')
rf = deal(client_name='QA Reimb', deal_type='pay_in', payin_method='crypto_direct',
          payin_amount_usdt=540, payout_amount_thb=17400, payout_method='transfer',
          payout_source='founder_personal', payout_founder_name='QA Андрей')
check('сделка ждёт возмещения', rf.get('needs_reimbursement') is True, rf.get('needs_reimbursement'))
pend = api('GET', '/api/reimbursements/pending')
in_queue = any(x['id'] == rf.get('id') for f in pend.get('by_founder', []) for x in f['deals'])
check('попала в очередь возмещения', in_queue)
mf_in_queue = any(x['id'] == d.get('id') for f in pend.get('by_founder', []) for x in f['deals'])
check('MF-сделка в очередь НЕ попала', not mf_in_queue)
if 'id' in rf:
    six = [f'{i:02d}' * 32 for i in range(1, 7)]
    rr = api('POST', '/api/reimbursements',
             {'founder_name': 'QA Андрей', 'deal_ids': [rf['id']],
              'amount_usdt': 520, 'tx_hashes': six})
    check('возмещение с 6 хэшами создано', rr.get('success'), rr.get('error'))
    if rr.get('success'):
        created_reimb.append(rr['reimbursement']['id'])
        check('все 6 хэшей сохранены', len(rr['reimbursement']['tx_hashes']) == 6)
        after = api('GET', f"/api/deals/{rf['id']}")['deal']
        check('сделка завершена возмещением', after['status'] == 'completed', after['status'])
        check('выплата USDT проставлена', approx(after['payout_amount_usdt'], 520))

print('\n══ 9. Фактические переводы в MF Corp ══')
# Отправка ушла шестью переводами: 5×100 000 + 8 828 = $508 828.00 при расчётных
# $508 827.76 — расхождение должно быть видно, а не растворяться в модели
parts = [{'hash': f'QAPAYOUT{i}', 'amount_usdt': 100000, 'to_address': 'TQAmfcorp0000000001',
          'date': '05.08.2026'} for i in range(5)]
parts.append({'hash': 'QAPAYOUT5', 'amount_usdt': 8828, 'to_address': 'TQAmfcorp0000000001',
              'date': '05.08.2026'})
prev = api('POST', '/api/deals/mf-realty/preview',
           {'invoice_amount_thb': 16742400, 'buy_rate_thb_usdt': 33.20,
            'payin_amount_usdt': 512000, 'company_percent': 0.9,
            'payout_tx_hashes': parts})
if prev.get('success'):
    pr = prev['result']
    check('превью: себестоимость по факту $508 828.00', approx(pr['cost_usdt'], 508828.00), pr.get('cost_usdt'))
    check('превью: по курсу $508 827.76', approx(pr['computed_cost_usdt'], 508827.76), pr.get('computed_cost_usdt'))
    check('превью: расхождение $0.24', approx(pr['cost_diff_usdt'], 0.24), pr.get('cost_diff_usdt'))
else:
    check('превью с переводами отвечает', False, prev.get('error'))

dp = deal(client_name='QA MF Факт', deal_kind='mf_realty', deal_type='pay_in',
          payin_method='crypto_direct', payin_amount_usdt=512000,
          realty_purpose='QA Villa Факт', invoice_amount_thb=16742400,
          buy_rate_thb_usdt=33.20, company_percent=0.9, payout_tx_hashes=parts)
check('сделка с переводами создана', 'id' in dp, dp.get('_error', ''))
if 'id' in dp:
    check('переводов сохранено 6', len(dp.get('payout_tx_hashes') or []) == 6)
    check('адрес получателя виден',
          (dp['payout_tx_hashes'][0] or {}).get('to_address') == 'TQAmfcorp0000000001')
    check('себестоимость по факту $508 828.00', approx(dp['payout_amount_usdt'], 508828.00), dp.get('payout_amount_usdt'))
    check('в крипте $3 172.00 (на $0.24 меньше модели)', approx(dp['profit_usdt'], 3172.00), dp.get('profit_usdt'))
    check('сумма переводов = себестоимости',
          approx(sum(x['amount_usdt'] for x in dp['payout_tx_hashes']), dp['payout_amount_usdt']))
    # Хэши заняты: повторно привязать к другой сделке нельзя
    inc = api('GET', '/api/transactions/incoming')
    check('эндпоинт входящих отвечает', inc.get('success') is True, inc.get('error'))
    # Снимаем переводы — возвращаемся к расчёту по курсу
    api('PUT', f"/api/deals/{dp['id']}", {'payout_tx_hashes': []})
    back = api('GET', f"/api/deals/{dp['id']}")['deal']
    check('без переводов вернулись к $508 827.76', approx(back['payout_amount_usdt'], 508827.76), back.get('payout_amount_usdt'))

print('\n══ 10. Дедуп переводов TronScan ══')
out = api('GET', '/api/transactions/outgoing')
check('эндпоинт исходящих отвечает', out.get('success') is True, out.get('error'))

print('\n══ Уборка ══')
for rid in created_reimb:
    api('DELETE', f'/api/reimbursements/{rid}')
for did in created_deals:
    api('DELETE', f'/api/deals/{did}')
for rid in created_refs:
    api('DELETE', f'/api/referrers/{rid}')
left = api('GET', '/api/deals?per_page=1000&include_lose=1')
qa_left = [x['id'] for x in left.get('deals', []) if (x.get('client_name') or '').startswith('QA ')]
check('тестовые сделки удалены', not qa_left, qa_left)

ok = sum(1 for r in results if r[0])
print(f'\n{"─"*60}\nИТОГ: {ok}/{len(results)} проверок прошли')
for good, name, detail in results:
    if not good:
        print(f'  ❌ {name}  → {detail}')
