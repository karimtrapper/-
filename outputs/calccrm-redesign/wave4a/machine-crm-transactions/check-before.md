# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=transactions`
DESIGN: `/Users/karimamirov/Desktop/untitled folder/outputs/calccrm-redesign/DESIGN.md`
Ширины: запрошено [375, 1280], обязательны для PASS [375, 768, 1280, 1920]
Роль: karim

_Вердикт машинный: проверена автоматическая часть гейтов. Вкус, иерархия и пункты «MANUAL» ниже остаются человеку._

**Причины вердикта:**
- FAIL в гейтах: 1. Токены, 2. Гардрейлы, 3. Контраст WCAG AA, 4. Ширины
- 768px: ширина не снята (не запрашивалась)
- 1920px: ширина не снята (не запрашивалась)
- проверены не все ширины: запрошено [375, 1280], для вердикта PASS нужны [375, 768, 1280, 1920]. Проверка одной ширины не считается проверкой экрана.
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

| Гейт | Вердикт | 375 | 768 | 1280 | 1920 |
|---|---|---|---|---|---|
| 1. Токены | **FAIL** | FAIL | BLOCKED | FAIL | BLOCKED |
| 2. Гардрейлы | **FAIL** | FAIL | BLOCKED | FAIL | BLOCKED |
| 3. Контраст WCAG AA | **FAIL** | FAIL | BLOCKED | FAIL | BLOCKED |
| 4. Ширины | **FAIL** | PASS | BLOCKED | FAIL | BLOCKED |
| 5. Текст | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |
| 6. Снимки | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |

## Телефон (≤700px)
- 375px: элементов 90, контраст проверен у 46, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (8)
  - `margin-вертикаль 14px` — 375px×14 — напр. `section#transactions > div.card`
  - `padding 14px` — 375px×7 — напр. `div.container`
  - `margin-вертикаль 6px` — 375px×5 — напр. `div.form-row > div.form-group > label.form-label` «Добавить кошелек TRON для мониторинга»
  - `gap 6px` — 375px×5 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
  - `padding 20px` — 375px×3 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `padding 36px` — 375px×1 — напр. `select#walletFilter` «Все кошельки»
- **шрифт вне токенов** (1)
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×3 — напр. `section#transactions > div.card`
- **кегль вне шкалы** (2)
  - `13px` — 375px×7 — напр. `div.form-row > div.form-group > label.form-label` «Добавить кошелек TRON для мониторинга»
  - `15px` — 375px×2 — напр. `select#walletFilter` «Все кошельки»
- **вес вне шкалы** (1)
  - `500` — 375px×7 — напр. `div.form-row > div.form-group > label.form-label` «Добавить кошелек TRON для мониторинга»
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
- **цвет текста вне палитры** (1)
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×1 — напр. `section#transactions > div.card > p` «Выберите транзакцию для создания сделки»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `6: 12, 13, 14, 15, 16, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×9 — напр. `div.form-row > div.form-group > input.form-control`
- **эмодзи в кнопке/ссылке/табе/заголовке** (1)
  - `⌛` — 375px×1 — напр. `div.form-row > div.form-group > button.btn.btn-secondary` «⌛ Загрузка...»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (3)
  - `TYourWalletAddress...` — 375px×1 — напр. `div.form-row > div.form-group > input.form-control` «TYourWalletAddress...»
  - `Теодор` — 375px×1 — напр. `div.form-row > div.form-group > input.form-control` «Теодор»
  - `Хэш транзакции (64 символа)` — 375px×1 — напр. `div.form-row > div.form-group > input.form-control` «Хэш транзакции (64 символа)»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (1)
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 375px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 375px×1 — напр. `select#walletFilter` «Все кошельки»

### Гейт 4. Ширины: 375px PASS
находок нет

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 238, контраст проверен у 139, главных кнопок 0, адресов 9
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (14)
  - `gap 6px` — 1280px×23 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
  - `margin-вертикаль 5.6px` — 1280px×18 — напр. `div > div > input` «Теодор»
  - `margin-вертикаль 14px` — 1280px×11 — напр. `form#addWalletForm > div.form-row > div.form-group`
  - `padding 32px` — 1280px×10 — напр. `div.container`
  - `gap 10px` — 1280px×9 — напр. `div > div > div`
  - `padding 2px` — 1280px×9 — напр. `div > div > button.btn.btn-sm` «×»
  - `padding 5px` — 1280px×9 — напр. `div > div > button.btn.btn-sm` «×»
  - `padding 14px` — 1280px×6 — напр. `div.form-row > div.form-group > input.form-control`
  - `padding 20px` — 1280px×6 — напр. `section#transactions > div.card`
  - `margin-вертикаль 6px` — 1280px×5 — напр. `div.form-row > div.form-group > label.form-label` «Добавить кошелек TRON для мониторинга»
  - … и ещё 4 (полный список в JSON)
- **шрифт вне токенов** (2)
  - `arial` — 1280px×10 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
  - `monospace` — 1280px×9 — напр. `div > div > span` «0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×3 — напр. `section#transactions > div.card`
- **кегль вне шкалы** (7)
  - `12.48px` — 1280px×27 — напр. `div > div > span` «0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9»
  - `11.2px` — 1280px×9 — напр. `div > div > button.btn.btn-sm` «×»
  - `13.6px` — 1280px×8 — напр. `div > div > span` «| 2.73 TRX»
  - `13px` — 1280px×7 — напр. `div.form-row > div.form-group > label.form-label` «Добавить кошелек TRON для мониторинга»
  - `14.4px` — 1280px×4 — напр. `div > div > input` «Теодор · ERC-20»
  - `12.8px` — 1280px×4 — напр. `div > div > input` «Теодор»
  - `15px` — 1280px×2 — напр. `select#walletFilter` «Все кошельки»
- **вес вне шкалы** (1)
  - `500` — 1280px×7 — напр. `div.form-row > div.form-group > label.form-label` «Добавить кошелек TRON для мониторинга»
- **фон вне палитры** (4)
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 1280px×9 — напр. `div > div > button.btn.btn-sm` «×»
  - `#DBEAFE (ближайший navy-200 #E2E8F0, ΔE 5.0)` — 1280px×4 — напр. `div > div > span.badge` «приём оплаты»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 1280px×1 — напр. `div > div > span.badge` «мультисиг»
- **цвет текста вне палитры** (3)
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 1280px×9 — напр. `div > div > span` «| 2.73 TRX»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 1280px×8 — напр. `div > div > strong` «$0.00 USDT»
  - `#1E40AF (ближайший navy-600 #475569, ΔE 12.9)` — 1280px×4 — напр. `div > div > span.badge` «приём оплаты»
- **цвет рамки вне палитры** (1)
  - `#A7F3D0 (ближайший money-border #BBF7D0, ΔE 3.3)` — 1280px×18 — напр. `div > div > input` «Теодор · ERC-20»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×18 — напр. `div.form-row > div.form-group > input.form-control`
- **эмодзи в кнопке/ссылке/табе/заголовке** (2)
  - `📋` — 1280px×9 — напр. `div > div > span` «📋»
  - `⌛` — 1280px×1 — напр. `div.form-row > div.form-group > button.btn.btn-secondary` «⌛ Загрузка...»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- **кеглей на экране больше 4** (1)
  - `11: 11.2, 12, 12.48, 12.8, 13, 13.6, 14, 14.4, 15, 16, 22` — 1280px×1
- **синий фон (синих плашек нет)** (1)
  - `#DBEAFE` — 1280px×4 — напр. `div > div > span.badge` «приём оплаты»
- **кнопка-иконка без видимой подписи** (1)
  - `×` — 1280px×9 — напр. `div > div > button.btn.btn-sm` «×»
- **у адреса overflow-wrap:anywhere / word-break:break-all** (1)
  - `overflow-wrap:normal; word-break:break-all` — 1280px×9 — напр. `div > div > span` «0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (5)
  - `Подпись — чей это кошелёк?` — 1280px×9 — напр. `div > div > input` «Подпись — чей это кошелёк?»
  - `Владелец` — 1280px×9 — напр. `div > div > input` «Владелец»
  - `TYourWalletAddress...` — 1280px×1 — напр. `div.form-row > div.form-group > input.form-control` «TYourWalletAddress...»
  - `Теодор` — 1280px×1 — напр. `div.form-row > div.form-group > input.form-control` «Теодор»
  - … и ещё 1 (полный список в JSON)
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`
- (warn) **адрес/хеш не Mono 14px** (1)
  - `12.48px` — 1280px×9 — напр. `div > div > span` «0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9»

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (3)
  - `#FFFFFF на #EF4444 = 3.76:1 (11.2px/600)` — 1280px×9 — напр. `div > div > button.btn.btn-sm` «×»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 1280px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
  - `#94A3B8 на #F0FDF4 = 2.45:1 (16px/400)` — 1280px×1 — напр. `div > div > span` «нет данных»
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 1280px×1 — напр. `select#walletFilter` «Все кошельки»
- **контраст ниже 3:1** (1)
  - `#10B981 на #F0FDF4 = 2.42:1 (16px/700)` — 1280px×8 — напр. `div > div > strong` «$0.00 USDT»
- **контраст плейсхолдера ниже 4.5:1** (1)
  - `#757575 на #F0FDF4 = 4.40:1` — 1280px×18 — напр. `div > div > input` «Подпись — чей это кошелёк?»

### Гейт 4. Ширины: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **адрес/хеш переносится на 2+ строк** (1)
  - `2 стр.` — 1280px×1 — напр. `div > div > span` «0x68aEA0F5386a57b48953F6fFF2f22D29D00D9ba9»
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `21px и 36px (Δверха 12px)` — 1280px×9 — напр. `div > div > input` «Теодор · ERC-20»
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `21px` — 1280px×9 — напр. `div > div > input` «Теодор · ERC-20»
  - `20px` — 1280px×9 — напр. `div > div > input` «Теодор»
  - `36px` — 1280px×9 — напр. `div > div > button.btn.btn-sm` «×»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (1)
  - `0,00 USDT × 6` — 1280px×6 — напр. `div > div > strong` «$0.00 USDT»

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-transactions/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-transactions/before-karim-1280.png`
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

## Гардрейлы (18)

| № | Запрет | Охват | Вердикт |
|---|---|---|---|
| 1 | Один шрифт + моно, 4 кегля, 3 веса | auto | FAIL |
| 2 | Цвета/отступы/радиусы/тени только из токенов | auto | FAIL |
| 3 | Сосиски, градиенты, hover-зум, анимации появления | partial | FAIL |
| 4 | Кнопки без глагола, две главные, иконка без подписи | partial | FAIL |
| 5 | Эмодзи вместо иконок; один размер иконок | partial | FAIL |
| 6 | Цветные полосы слева, синие подсказки, оранжевый вне кнопки | partial | FAIL |
| 7 | Адрес/хеш в одну строку; ничего шире экрана | auto | FAIL |
| 8 | Внутренние названия и коды на экране | partial | PASS* |
| 9 | Плейсхолдер вместо подписи / обрезанный плейсхолдер | partial | PASS* |
| 10 | Ряды «подпись — поле — кнопка» выровнены | partial | FAIL |
| 11 | Контраст WCAG AA | auto | FAIL |
| 12 | Повтор одной цифры на экране | partial | PASS* |
| 13 | Кликабельное vs статичное | manual | MANUAL |
| 14 | Независимые вертикальные стеки вместо строк | manual | MANUAL |
| 15 | Больше двух текстовых ролей в компактном контроле | auto | PASS |
| 16 | Микротекст, который надо читать | partial | PASS* |
| 17 | Пустоты и завышенные строки | manual | MANUAL |
| 18 | Состояния, анимации transform/opacity, ошибки консоли | partial | FAIL |

`PASS*` — автоматическая часть чистая; остальное смотрит человек.

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
