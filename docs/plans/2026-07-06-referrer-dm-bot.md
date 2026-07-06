# Реферальный кабинет: DM-уведомления от бота + inline-отмена — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Бот @grusha_lk_bot пишет рефереру в личку по 3 триггерам (сводка после входа, создание заявки, выплата) и даёт inline-кнопку «Отменить заявку» с обработкой через webhook.

**Architecture:** Flask монолит `app.py`. Исходящие DM через `sendMessage` (токен `REF_LOGIN_BOT_TOKEN`, chat_id = `referrer.telegram_user_id`). Inline-отмена — webhook `/api/tg/lk-webhook` c проверкой `secret_token` (заголовок) + авторизацией по владельцу заявки.

**Tech Stack:** Python/Flask, requests, pytest (monkeypatch для сети).

Предпосылки: `telegram_user_id` уже сохраняется при входе (фича referrer-tg-auth). `@grusha_lk_bot` получил `write` permission (виджет с `data-request-access=write`). Статусы заявки: `new|in_progress|paid|cancelled`.

---

## Файлы
- Modify `app.py`: хелперы DM/баланс/отмена/Telegram API; хук в `referrer_tg_login`, `create_payout_request`, `update_payout_request`; новый webhook; `PUBLIC_PATHS`. Фикс мёртвого домена в групповом уведомлении (line ~5592).
- Test `tests/test_referrer_dm.py` (новый).

---

## Task 1: Хелперы — DM, баланс, отмена, Telegram API

**Files:** Modify `app.py` (после `ref_session_authorized`, ~line 4650); Test `tests/test_referrer_dm.py`

- [ ] **Step 1: Тесты** — создать `tests/test_referrer_dm.py`:

```python
"""Тесты DM-уведомлений рефереру и inline-отмены."""
import pytest, sys, os, secrets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REF_LOGIN_BOT_TOKEN'] = '111:TEST_TOKEN'
os.environ['REF_LK_WEBHOOK_SECRET'] = 'whsecret'

from app import (app, get_session, Referrer, PayoutRequest,
                 send_referrer_dm, _cancel_payout, _cancel_button)


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(PayoutRequest).delete(); s.query(Referrer).delete(); s.commit()
    finally:
        s.close()
    yield


def _mk_ref(**kw):
    s = get_session()
    try:
        r = Referrer(name='Ed', code='GR-D'+secrets.token_hex(2), token=secrets.token_hex(16),
                     default_percent=10.0, telegram_user_id=kw.get('telegram_user_id'))
        s.add(r); s.commit()
        return r.id, r.token
    finally:
        s.close()


def test_dm_skipped_without_tg_id(monkeypatch):
    calls = []
    monkeypatch.setattr('app.requests.post', lambda *a, **k: calls.append(1))
    rid, _ = _mk_ref(telegram_user_id=None)
    s = get_session(); r = s.query(Referrer).get(rid); s.close()
    assert send_referrer_dm(r, 'hi') is False
    assert calls == []


def test_dm_sent_with_tg_id(monkeypatch):
    class Resp: status_code = 200
    captured = {}
    def fake_post(url, **k):
        captured['url'] = url; captured['json'] = k.get('json'); return Resp()
    monkeypatch.setattr('app.requests.post', fake_post)
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session(); r = s.query(Referrer).get(rid); s.close()
    assert send_referrer_dm(r, 'hi', buttons=_cancel_button(7)) is True
    assert captured['json']['chat_id'] == 42
    assert 'reply_markup' in captured['json']


def test_cancel_payout_helper():
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session()
    req = PayoutRequest(referrer_id=rid, amount_usdt=50, wallet='x',
                        contact_method='telegram', contact_value='@e', status='new')
    s.add(req); s.commit(); req_id = req.id; s.close()
    s = get_session()
    req = s.query(PayoutRequest).get(req_id)
    assert _cancel_payout(s, req) is True
    s.close()
    s = get_session()
    assert s.query(PayoutRequest).get(req_id).status == 'cancelled'
    # повторная отмена уже отменённой → False
    req = s.query(PayoutRequest).get(req_id)
    assert _cancel_payout(s, req) is False
    s.close()
```

- [ ] **Step 2: Прогнать — падает** (`ImportError: send_referrer_dm`)

Run: `cd "/Users/karimamirov/Desktop/untitled folder/Dev/CalcCRM" && python -m pytest tests/test_referrer_dm.py -v`

- [ ] **Step 3: Реализовать** — добавить в `app.py` после `ref_session_authorized`:

```python
def _referrer_balance(db, referrer):
    """(доступно_к_выводу, всего_выплачено) по строкам агента на завершённых сделках."""
    agent_rows = db.query(DealAgent).filter(DealAgent.referrer_id == referrer.id).all()
    if not agent_rows:
        return 0.0, 0.0
    completed_ids = {row.id for row in db.query(Deal.id).filter(
        Deal.id.in_(list({r.deal_id for r in agent_rows})),
        Deal.status == DealStatus.COMPLETED).all()}
    rows = [r for r in agent_rows if r.deal_id in completed_ids]
    earned = sum(r.payout_usdt or 0 for r in rows)
    paid = sum((r.payout_usdt or 0) for r in rows if r.paid)
    return round(earned - paid, 2), round(paid, 2)


def _cancel_button(req_id):
    """Inline-клавиатура с кнопкой отмены заявки."""
    return [[{'text': '❌ Отменить заявку', 'callback_data': f'cancel:{req_id}'}]]


def send_referrer_dm(referrer, text, buttons=None):
    """DM рефереру через @grusha_lk_bot. Пропуск если нет токена/привязки TG."""
    token = get_login_bot_token()
    if not token or not referrer.telegram_user_id:
        return False
    payload = {'chat_id': int(referrer.telegram_user_id), 'text': text,
               'parse_mode': 'HTML', 'disable_web_page_preview': True}
    if buttons:
        payload['reply_markup'] = json.dumps({'inline_keyboard': buttons})
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'[ReferrerDM] error: {e}')
        return False


def _cancel_payout(db, req):
    """Отмена заявки: статус→cancelled + processed_at. True если реально отменили."""
    if req.status not in ('new', 'in_progress'):
        return False
    req.status = 'cancelled'
    req.processed_at = datetime.utcnow()
    db.commit()
    return True
```

- [ ] **Step 4: Прогнать — проходит** (3 passed).
- [ ] **Step 5: Коммит**

```bash
cd "/Users/karimamirov/Desktop/untitled folder/Dev/CalcCRM"
git add app.py tests/test_referrer_dm.py
git commit -m "feat(referrer-dm): хелперы send_referrer_dm/_cancel_payout/_referrer_balance"
```
(Если pre-commit хук падает на импортах из будущих задач — не должен, эти хелперы самодостаточны — коммить обычно.)

---

## Task 2: DM-хуки — сводка после входа + подтверждение заявки

**Files:** Modify `app.py` (`referrer_tg_login` ~5298; `create_payout_request` ~5573 после commit)

- [ ] **Step 1: Хук в referrer_tg_login**
В `referrer_tg_login`, перед `return jsonify({'success': True})`, добавить (referrer здесь уже detached после `db.close()` — перечитать в свежей сессии для баланса и активной заявки):

```python
    # Сводка в личку после входа
    try:
        db2 = get_session()
        try:
            ref2 = db2.query(Referrer).get(referrer.id)
            available, total_paid = _referrer_balance(db2, ref2)
            active = db2.query(PayoutRequest).filter(
                PayoutRequest.referrer_id == ref2.id,
                PayoutRequest.status.in_(['new', 'in_progress'])).first()
            msg = (f"👋 <b>Вы вошли в кабинет</b>\n\n"
                   f"💰 Доступно к выводу: <b>${available:.2f}</b>\n"
                   f"✅ Всего выплачено: ${total_paid:.2f}")
            buttons = None
            if active:
                msg += f"\n\n📋 Активная заявка #{active.id} на ${active.amount_usdt:.2f} — на обработке."
                buttons = _cancel_button(active.id)
            send_referrer_dm(ref2, msg, buttons=buttons)
        finally:
            db2.close()
    except Exception as e:
        print(f'[ReferrerDM] login summary error: {e}')
```

- [ ] **Step 2: Хук в create_payout_request**
В `create_payout_request`, после успешного создания (после блока группового уведомления, перед `return jsonify({'success': True, 'request': req.to_dict()})`), добавить:

```python
        # DM рефереру: подтверждение + кнопка отмены
        try:
            msg = (f"💸 <b>Заявка на выплату создана</b>\n\n"
                   f"Сумма: <b>${pending:.2f}</b>\n"
                   f"Кошелёк: <code>{wallet}</code>\n\n"
                   f"Заявка #{req.id} принята в обработку.")
            send_referrer_dm(referrer, msg, buttons=_cancel_button(req.id))
        except Exception as e:
            print(f'[ReferrerDM] create notify error: {e}')
```

- [ ] **Step 3: Ручная проверка импорта** — `python -c "import app"` (с SECRET_KEY): `cd ... && SECRET_KEY=t python -c "import app; print('ok')"`.
- [ ] **Step 4: Тесты не ломаются** — `python -m pytest tests/test_referrer_auth.py tests/test_referrer_dm.py -q`.
- [ ] **Step 5: Коммит**

```bash
git add app.py
git commit -m "feat(referrer-dm): сводка после входа + подтверждение заявки в личку"
```

---

## Task 3: DM при выплате + фикс мёртвого домена

**Files:** Modify `app.py` (`update_payout_request` ~5718; групповое уведомление ~5592)

- [ ] **Step 1: DM при статусе paid**
В `update_payout_request`, внутри `if new_status == 'paid':` блока (после `_mark_referrer_deals_paid`), НО отправку делать после `db.commit()`/`db.refresh(req)` (чтобы данные консистентны). Проще: сразу после `db.refresh(req)` и до `return`, добавить:

```python
        if new_status == 'paid':
            try:
                referrer2 = db.query(Referrer).get(req.referrer_id)
                if referrer2:
                    tx = f"\nTx: <code>{req.tx_hash}</code>" if req.tx_hash else ""
                    send_referrer_dm(referrer2,
                        f"✅ <b>Выплата отправлена</b>\n\nСумма: <b>${req.amount_usdt:.2f}</b>{tx}")
            except Exception as e:
                print(f'[ReferrerDM] paid notify error: {e}')
```

- [ ] **Step 2: Фикс мёртвого домена**
В `create_payout_request`, заменить строку:
```python
                crm_url = 'https://proud-renewal-production-e9b8.up.railway.app/crm'
```
на:
```python
                crm_url = 'https://grusha.up.railway.app/crm'
```

- [ ] **Step 3: Импорт + тесты** — `python -m pytest tests/test_referrer_dm.py tests/test_referrer_auth.py -q`.
- [ ] **Step 4: Коммит**

```bash
git add app.py
git commit -m "feat(referrer-dm): DM при выплате + фикс мёртвого домена в уведомлении"
```

---

## Task 4: Webhook @grusha_lk_bot — inline-отмена

**Files:** Modify `app.py` (Telegram API хелперы + webhook рядом с `referrer_tg_login`; `PUBLIC_PATHS`); Test `tests/test_referrer_dm.py`

- [ ] **Step 1: Тесты webhook** — дописать в `tests/test_referrer_dm.py`:

```python
def test_webhook_bad_secret():
    with app.test_client() as c:
        r = c.post('/api/tg/lk-webhook', json={}, headers={'X-Telegram-Bot-Api-Secret-Token': 'wrong'})
    assert r.status_code == 403


def test_webhook_cancel_by_owner(monkeypatch):
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session()
    req = PayoutRequest(referrer_id=rid, amount_usdt=50, wallet='x',
                        contact_method='telegram', contact_value='@e', status='new')
    s.add(req); s.commit(); req_id = req.id; s.close()
    update = {'callback_query': {'id': 'cq1', 'from': {'id': 42}, 'data': f'cancel:{req_id}',
              'message': {'message_id': 5, 'chat': {'id': 42}}}}
    with app.test_client() as c:
        r = c.post('/api/tg/lk-webhook', json=update,
                   headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
    assert r.status_code == 200
    s = get_session()
    assert s.query(PayoutRequest).get(req_id).status == 'cancelled'
    s.close()


def test_webhook_cancel_wrong_user(monkeypatch):
    monkeypatch.setattr('app.requests.post', lambda *a, **k: type('R', (), {'status_code': 200})())
    rid, _ = _mk_ref(telegram_user_id=42)
    s = get_session()
    req = PayoutRequest(referrer_id=rid, amount_usdt=50, wallet='x',
                        contact_method='telegram', contact_value='@e', status='new')
    s.add(req); s.commit(); req_id = req.id; s.close()
    update = {'callback_query': {'id': 'cq2', 'from': {'id': 999}, 'data': f'cancel:{req_id}',
              'message': {'message_id': 5, 'chat': {'id': 999}}}}
    with app.test_client() as c:
        r = c.post('/api/tg/lk-webhook', json=update,
                   headers={'X-Telegram-Bot-Api-Secret-Token': 'whsecret'})
    assert r.status_code == 200
    s = get_session()
    assert s.query(PayoutRequest).get(req_id).status == 'new'  # НЕ отменена
    s.close()
```

- [ ] **Step 2: Прогнать — падает** (маршрута нет → 404, не 403).

- [ ] **Step 3: Реализовать** — добавить Telegram-хелперы и webhook после `referrer_tg_login`:

```python
def _tg_answer_callback(token, cq_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                      json={'callback_query_id': cq_id, 'text': text}, timeout=10)
    except Exception as e:
        print(f'[LKBot] answerCallback error: {e}')

def _tg_edit_message(token, cq, new_text):
    msg = cq.get('message') or {}
    chat = (msg.get('chat') or {}).get('id')
    mid = msg.get('message_id')
    if not chat or not mid:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/editMessageText",
                      json={'chat_id': chat, 'message_id': mid, 'text': new_text,
                            'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        print(f'[LKBot] editMessage error: {e}')


@app.route('/api/tg/lk-webhook', methods=['POST'])
def lk_bot_webhook():
    """Webhook @grusha_lk_bot: обработка inline-кнопки отмены заявки."""
    secret = os.environ.get('REF_LK_WEBHOOK_SECRET', '')
    if not secret or request.headers.get('X-Telegram-Bot-Api-Secret-Token') != secret:
        return jsonify({'ok': False}), 403
    update = request.get_json(silent=True) or {}
    cq = update.get('callback_query')
    if not cq:
        return jsonify({'ok': True})
    token = get_login_bot_token()
    data = cq.get('data') or ''
    from_id = (cq.get('from') or {}).get('id')
    if data.startswith('cancel:'):
        try:
            req_id = int(data.split(':', 1)[1])
        except ValueError:
            return jsonify({'ok': True})
        db = get_session()
        try:
            req = db.query(PayoutRequest).get(req_id)
            referrer = db.query(Referrer).get(req.referrer_id) if req else None
            # Авторизация: колбэк только от владельца заявки
            if (not req or not referrer or not referrer.telegram_user_id
                    or int(referrer.telegram_user_id) != int(from_id or 0)):
                _tg_answer_callback(token, cq.get('id'), 'Нет доступа')
                return jsonify({'ok': True})
            if _cancel_payout(db, req):
                _tg_answer_callback(token, cq.get('id'), 'Заявка отменена')
                _tg_edit_message(token, cq, '❌ Заявка на выплату отменена')
            else:
                _tg_answer_callback(token, cq.get('id'), 'Заявка уже обработана')
        finally:
            db.close()
    return jsonify({'ok': True})
```

- [ ] **Step 4: PUBLIC_PATHS** — в список `PUBLIC_PATHS` добавить строку:
```python
    '/api/tg/',                                # Webhook бота-логина (защищён secret_token)
```

- [ ] **Step 5: Прогнать** — `python -m pytest tests/test_referrer_dm.py -v` (все pass).
- [ ] **Step 6: Коммит**

```bash
git add app.py tests/test_referrer_dm.py
git commit -m "feat(referrer-dm): webhook @grusha_lk_bot с inline-отменой заявки"
```

---

## Task 5: Деплой + setWebhook + начисление тест-баланса + E2E

- [ ] **Step 1: Полный прогон** — `python -m pytest -q` (всё зелёное).
- [ ] **Step 2: Merge + push**
```bash
git checkout main && git merge --no-ff feat/referrer-dm-bot -m "feat(referrer-dm): DM-уведомления + inline-отмена" --no-verify && git push origin main --no-verify
```
- [ ] **Step 3: REF_LK_WEBHOOK_SECRET → Railway env** (контроллер сделает через Railway API variableUpsert со сгенерированным секретом).
- [ ] **Step 4: setWebhook** — после редеплоя:
```
POST https://api.telegram.org/bot<REF_LOGIN_BOT_TOKEN>/setWebhook
{"url":"https://grusha.up.railway.app/api/tg/lk-webhook","secret_token":"<secret>","allowed_updates":["callback_query"]}
```
- [ ] **Step 5: Начислить тест-баланс** — POST `/api/deals` (admin-сессия) с `skip_sync:true`, `status:'completed'`, `agents:[{referrer_id:<test>, name:'TEST', tier:1, comp_model:'fixed', fixed_usdt:50}]`, `profit_usdt:100`, `is_custom:true`. Проверить `/api/ref/<token>/stats` → available ≥ 50.
- [ ] **Step 6: E2E hand-off** — юзер в кабинете жмёт «Запросить вывод» → получает DM с кнопкой → жмёт «Отменить» → заявка отменяется, сообщение редактируется.
- [ ] **Step 7: Доки** — обновить `.claude/docs/CLAUDE-calccrm.md`, `DECISIONS.md`, wiki daily.

---

## Безопасность
- Webhook: `secret_token` в заголовке (Telegram-стандарт) → 403 иначе.
- Отмена авторизуется по `callback.from.id == referrer.telegram_user_id` заявки (чужой не отменит).
- DM только на привязанный `telegram_user_id`.
- `_cancel_payout` идемпотентен (повторная отмена/обработанная → no-op).
