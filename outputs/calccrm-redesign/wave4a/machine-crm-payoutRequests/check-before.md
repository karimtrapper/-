# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=payoutRequests`
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
| 4. Ширины | **FAIL** | FAIL | BLOCKED | FAIL | BLOCKED |
| 5. Текст | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |
| 6. Снимки | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |

## Телефон (≤700px)
- 375px: элементов 711, контраст проверен у 423, главных кнопок 0, адресов 45

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (9)
  - `padding 2px` — 375px×93 — напр. `div > div > span` «Выплачено»
  - `margin-вертикаль 10px` — 375px×65 — напр. `div#payoutRequestsList > div`
  - `padding 6px` — 375px×58 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `gap 6px` — 375px×43 — напр. `div.card > div.card-title > div`
  - `padding 14px` — 375px×41 — напр. `div.container`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×1 — напр. `section#payoutRequests > div.card`
  - `padding 10px` — 375px×1 — напр. `input#payout-tx-21`
  - `padding 7px` — 375px×1 — напр. `input#payout-tx-21`
- **шрифт вне токенов** (2)
  - `monospace` — 375px×57 — напр. `div > div > code` «2208840021»
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#payoutRequests > div.card`
- **кегль вне шкалы** (4)
  - `13px` — 375px×169 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `11px` — 375px×65 — напр. `div > div > span` «Выплачено»
  - `15px` — 375px×32 — напр. `div > div > strong` «Руслан»
  - `18px` — 375px×32 — напр. `div > div > div` «1 003 ฿»
- **цвет текста вне палитры** (4)
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 375px×82 — напр. `div > div > span` «Выплачено»
  - `#2563EB (ближайший navy-500 #64748B, ΔE 13.5)` — 375px×8 — напр. `div > div > span` «🏦 Баты»
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 375px×7 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div > div > span` «Новая»
- **фон вне палитры** (4)
  - `#DCFCE7 (ближайший money-surface #F0FDF4, ΔE 7.7)` — 375px×27 — напр. `div > div > span` «Выплачено»
  - `#EFEFEF (ближайший page-mist #F8FAFC, ΔE 2.5)` — 375px×7 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `#EFF6FF (ближайший navy-100 #F1F5F9, ΔE 2.3)` — 375px×4 — напр. `div > div > span` «🏦 Баты»
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 375px×1 — напр. `div > div > button.btn.btn-sm` «Выплачено»
- **вес вне шкалы** (1)
  - `800` — 375px×32 — напр. `div > div > div` «1 003 ฿»
- **радиус вне шкалы 8/12/999** (2)
  - `4px` — 375px×57 — напр. `div > div > code` «2208840021»
  - `6px` — 375px×1 — напр. `input#payout-tx-21`

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `8: 11, 12, 13, 14, 15, 16, 18, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 700, 800` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×8 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
- **синий фон (синих плашек нет)** (1)
  - `#EFF6FF` — 375px×4 — напр. `div > div > span` «🏦 Баты»
- **плейсхолдер не помещается в поле (обрезан)** (1)
  - `Хеш транзакции TRC-20 (для «Выплачено»)` — 375px×1 — напр. `input#payout-tx-21` «Хеш транзакции TRC-20 (для «Выплачено»)»
- **у адреса overflow-wrap:anywhere / word-break:break-all** (1)
  - `overflow-wrap:normal; word-break:break-all` — 375px×45 — напр. `div > div > code` «TGVVngRG1jit9Yn3QASbDpE8wvKYPwdMua»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (4)
  - `✈` — 375px×26 — напр. `div > div > span` «✈️ Telegram:»
  - `💬` — 375px×6 — напр. `div > div > span` «💬 WhatsApp:»
  - `🏦` — 375px×4 — напр. `div > div > span` «🏦 Баты»
  - `📄` — 375px×2 — напр. `div > div > div` «📄 Чек отправлен»
- (warn) **текст набран капслоком руками** (1)
  - `VALERII KUTYRAEV` — 375px×1 — напр. `div > div > strong` «VALERII KUTYRAEV»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Хеш транзакции TRC-20 (для «Выплачено»)` — 375px×1 — напр. `input#payout-tx-21` «Хеш транзакции TRC-20 (для «Выплачено»)»
- (warn) **адрес/хеш не Mono 14px** (2)
  - `12px` — 375px×24 — напр. `div > div > code` «TGVVngRG1jit9Yn3QASbDpE8wvKYPwdMua»
  - `11px` — 375px×21 — напр. `div > div > code` «5ee68a96dafef16513f1c3b86485ff01f7dec68217da015b26a9f74ee17e3d45»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (9)
  - `#94A3B8 на #FFFFFF = 2.56:1 (13px/400)` — 375px×106 — напр. `div > div > span` «Курс клиенту:»
  - `#94A3B8 на #FFFFFF = 2.56:1 (12px/400)` — 375px×32 — напр. `div > div > span` «GR-F07253»
  - `#16A34A на #DCFCE7 = 3.00:1 (11px/600)` — 375px×27 — напр. `div > div > span` «Выплачено»
  - `#16A34A на #F0FDF4 = 3.15:1 (11px/400)` — 375px×25 — напр. `div > div > code` «5ee68a96dafef16513f1c3b86485ff01f7dec68217da015b26a9f74ee17e»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 375px×4 — напр. `div > div > div` «возместить $30.95»
  - `#64748B на #F1F5F9 = 4.34:1 (11px/600)` — 375px×4 — напр. `div > div > span` «Отменено»
  - `#16A34A на #FFFFFF = 3.30:1 (13px/600)` — 375px×2 — напр. `div > div > div` «📄 Чек отправлен»
  - `#F97316 на #FFF7ED = 2.64:1 (11px/600)` — 375px×1 — напр. `div > div > span` «Новая»
  - `#FFFFFF на #22C55E = 2.28:1 (13px/600)` — 375px×1 — напр. `div > div > button.btn.btn-sm` «Выплачено»

### Гейт 4. Ширины: 375px FAIL
- **адрес/хеш переносится на 2+ строк** (1)
  - `2 стр.` — 375px×45 — напр. `div > div > code` «TGVVngRG1jit9Yn3QASbDpE8wvKYPwdMua»
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `36px` — 375px×8 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `30px` — 375px×1 — напр. `input#payout-tx-21`

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (2)
  - `413,00 $ × 2` — 375px×2 — напр. `div > div > div` «$413.00»
  - `450,01 $ × 2` — 375px×2 — напр. `div > div > div` «возместить $450.01»

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 714, контраст проверен у 423, главных кнопок 0, адресов 45
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (10)
  - `padding 2px` — 1280px×93 — напр. `div > div > span` «Выплачено»
  - `margin-вертикаль 10px` — 1280px×65 — напр. `div#payoutRequestsList > div`
  - `padding 6px` — 1280px×58 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `gap 6px` — 1280px×43 — напр. `div.card > div.card-title > div`
  - `padding 14px` — 1280px×40 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `padding 10px` — 1280px×1 — напр. `input#payout-tx-21`
  - `padding 7px` — 1280px×1 — напр. `input#payout-tx-21`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1 — напр. `div.container`
  - `padding 20px` — 1280px×1 — напр. `section#payoutRequests > div.card`
- **шрифт вне токенов** (2)
  - `monospace` — 1280px×57 — напр. `div > div > code` «2208840021»
  - `arial` — 1280px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×1 — напр. `section#payoutRequests > div.card`
- **кегль вне шкалы** (4)
  - `13px` — 1280px×169 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `11px` — 1280px×65 — напр. `div > div > span` «Выплачено»
  - `15px` — 1280px×32 — напр. `div > div > strong` «Руслан»
  - `18px` — 1280px×32 — напр. `div > div > div` «1 003 ฿»
- **цвет текста вне палитры** (4)
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 1280px×82 — напр. `div > div > span` «Выплачено»
  - `#2563EB (ближайший navy-500 #64748B, ΔE 13.5)` — 1280px×8 — напр. `div > div > span` «🏦 Баты»
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 1280px×7 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×1 — напр. `div > div > span` «Новая»
- **фон вне палитры** (4)
  - `#DCFCE7 (ближайший money-surface #F0FDF4, ΔE 7.7)` — 1280px×27 — напр. `div > div > span` «Выплачено»
  - `#EFEFEF (ближайший page-mist #F8FAFC, ΔE 2.5)` — 1280px×7 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `#EFF6FF (ближайший navy-100 #F1F5F9, ΔE 2.3)` — 1280px×4 — напр. `div > div > span` «🏦 Баты»
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 1280px×1 — напр. `div > div > button.btn.btn-sm` «Выплачено»
- **вес вне шкалы** (1)
  - `800` — 1280px×32 — напр. `div > div > div` «1 003 ฿»
- **радиус вне шкалы 8/12/999** (2)
  - `4px` — 1280px×57 — напр. `div > div > code` «2208840021»
  - `6px` — 1280px×1 — напр. `input#payout-tx-21`

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `8: 11, 12, 13, 14, 15, 16, 18, 22` — 1280px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 700, 800` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×8 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
- **синий фон (синих плашек нет)** (1)
  - `#EFF6FF` — 1280px×4 — напр. `div > div > span` «🏦 Баты»
- **у адреса overflow-wrap:anywhere / word-break:break-all** (1)
  - `overflow-wrap:normal; word-break:break-all` — 1280px×45 — напр. `div > div > code` «TGVVngRG1jit9Yn3QASbDpE8wvKYPwdMua»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (4)
  - `✈` — 1280px×26 — напр. `div > div > span` «✈️ Telegram:»
  - `💬` — 1280px×6 — напр. `div > div > span` «💬 WhatsApp:»
  - `🏦` — 1280px×4 — напр. `div > div > span` «🏦 Баты»
  - `📄` — 1280px×2 — напр. `div > div > div` «📄 Чек отправлен»
- (warn) **текст набран капслоком руками** (1)
  - `VALERII KUTYRAEV` — 1280px×1 — напр. `div > div > strong` «VALERII KUTYRAEV»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Хеш транзакции TRC-20 (для «Выплачено»)` — 1280px×1 — напр. `input#payout-tx-21` «Хеш транзакции TRC-20 (для «Выплачено»)»
- (warn) **адрес/хеш не Mono 14px** (2)
  - `12px` — 1280px×24 — напр. `div > div > code` «TGVVngRG1jit9Yn3QASbDpE8wvKYPwdMua»
  - `11px` — 1280px×21 — напр. `div > div > code` «5ee68a96dafef16513f1c3b86485ff01f7dec68217da015b26a9f74ee17e3d45»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (9)
  - `#94A3B8 на #FFFFFF = 2.56:1 (13px/400)` — 1280px×106 — напр. `div > div > span` «Курс клиенту:»
  - `#94A3B8 на #FFFFFF = 2.56:1 (12px/400)` — 1280px×32 — напр. `div > div > span` «GR-F07253»
  - `#16A34A на #DCFCE7 = 3.00:1 (11px/600)` — 1280px×27 — напр. `div > div > span` «Выплачено»
  - `#16A34A на #F0FDF4 = 3.15:1 (11px/400)` — 1280px×25 — напр. `div > div > code` «5ee68a96dafef16513f1c3b86485ff01f7dec68217da015b26a9f74ee17e»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 1280px×4 — напр. `div > div > div` «возместить $30.95»
  - `#64748B на #F1F5F9 = 4.34:1 (11px/600)` — 1280px×4 — напр. `div > div > span` «Отменено»
  - `#16A34A на #FFFFFF = 3.30:1 (13px/600)` — 1280px×2 — напр. `div > div > div` «📄 Чек отправлен»
  - `#F97316 на #FFF7ED = 2.64:1 (11px/600)` — 1280px×1 — напр. `div > div > span` «Новая»
  - `#FFFFFF на #22C55E = 2.28:1 (13px/600)` — 1280px×1 — напр. `div > div > button.btn.btn-sm` «Выплачено»

### Гейт 4. Ширины: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `30px и 36px (Δверха 3px)` — 1280px×1 — напр. `input#payout-tx-21`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `36px` — 1280px×8 — напр. `div.card-title > div > button.btn.btn-sm` «Все»
  - `30px` — 1280px×1 — напр. `input#payout-tx-21`

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (2)
  - `413,00 $ × 2` — 1280px×2 — напр. `div > div > div` «$413.00»
  - `450,01 $ × 2` — 1280px×2 — напр. `div > div > div` «возместить $450.01»

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-payoutRequests/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-payoutRequests/before-karim-1280.png`
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

## Гардрейлы (18)

| № | Запрет | Охват | Вердикт |
|---|---|---|---|
| 1 | Один шрифт + моно, 4 кегля, 3 веса | auto | FAIL |
| 2 | Цвета/отступы/радиусы/тени только из токенов | auto | FAIL |
| 3 | Сосиски, градиенты, hover-зум, анимации появления | partial | FAIL |
| 4 | Кнопки без глагола, две главные, иконка без подписи | partial | PASS* |
| 5 | Эмодзи вместо иконок; один размер иконок | partial | PASS* |
| 6 | Цветные полосы слева, синие подсказки, оранжевый вне кнопки | partial | FAIL |
| 7 | Адрес/хеш в одну строку; ничего шире экрана | auto | FAIL |
| 8 | Внутренние названия и коды на экране | partial | PASS* |
| 9 | Плейсхолдер вместо подписи / обрезанный плейсхолдер | partial | FAIL |
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

## Дополнительно (Don't из DESIGN.md)
- **текст набран капслоком руками** (1)
  - `VALERII KUTYRAEV` — 375px×1, 1280px×1 — напр. `div > div > strong` «VALERII KUTYRAEV»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
