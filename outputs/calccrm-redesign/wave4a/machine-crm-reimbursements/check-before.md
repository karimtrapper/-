# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=reimbursements`
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
| 4. Ширины | **FAIL** | FAIL | BLOCKED | PASS | BLOCKED |
| 5. Текст | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |
| 6. Снимки | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |

## Телефон (≤700px)
- 375px: элементов 2070, контраст проверен у 1436, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (12)
  - `padding 14px` — 375px×395 — напр. `div.container`
  - `gap 6px` — 375px×196 — напр. `div.form-row > div.form-group > button.btn.btn-sm` «+ ещё хэш»
  - `margin-вертикаль 10px` — 375px×192 — напр. `div#reimbursementsList > div.batch-card`
  - `margin-вертикаль 2px` — 375px×192 — напр. `div.batch-card > div.batch-info > h4` «Возмещение #252 - Теодор»
  - `padding 6px` — 375px×170 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 2px` — 375px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `margin-вертикаль 1px` — 375px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `margin-вертикаль 6px` — 375px×10 — напр. `div.card > div.form-group > label.form-label` «Добавить перевод из истории (исходящие USDT) — можно несколь»
  - `margin-вертикаль 14px` — 375px×8 — напр. `section#reimbursements > div.card`
  - `padding 36px` — 375px×2 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
  - … и ещё 2 (полный список в JSON)
- **шрифт вне токенов** (2)
  - `monospace` — 375px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×4 — напр. `section#reimbursements > div.card`
- **цвет текста вне палитры** (4)
  - `#667EEA (ближайший navy-500 #64748B, ΔE 13.2)` — 375px×192 — напр. `div.batch-card > div.batch-amount > div.thb` «$1538.77»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 375px×26 — напр. `div.batch-info > p > span` «Без хэша»
  - `#6B7280 (ближайший navy-500 #64748B, ΔE 4.1)` — 375px×7 — напр. `label > span > span` «25.09, 00:00»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×1 — напр. `section#reimbursements > div.card > p` «Когда переводите фаундеру USDT за несколько сделок одной тра»
- **фон вне палитры** (4)
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 375px×192 — напр. `div.batch-card > div.batch-amount > button.btn.btn-sm` «Удалить»
  - `#E0F2FE (ближайший navy-200 #E2E8F0, ΔE 4.7)` — 375px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 375px×2 — напр. `div#pendingReimbursementsList > div.card`
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 375px×2 — напр. `div#pendingReimbursementsList > div.card > button.btn.btn-success` «Создать возмещение и рассчитать прибыль»
- **радиус вне шкалы 8/12/999** (2)
  - `4px` — 375px×174 — напр. `div.card > div > label`
  - `6px` — 375px×9 — напр. `div > label > input.reimburse-alloc`
- **кегль вне шкалы** (5)
  - `13px` — 375px×420 — напр. `div.card > div.form-group > label.form-label` «Добавить перевод из истории (исходящие USDT) — можно несколь»
  - `18px` — 375px×192 — напр. `div.batch-card > div.batch-amount > div.thb` «$1538.77»
  - `13.6px` — 375px×191 — напр. `div.card > div.form-group > div` «⚠️ TronScan не ответил по 4 кошельк(у/ам) — список переводов»
  - `12.8px` — 375px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `15px` — 375px×2 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
- **вес вне шкалы** (1)
  - `500` — 375px×8 — напр. `div.card > div.form-group > label.form-label` «Добавить перевод из истории (исходящие USDT) — можно несколь»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `9: 12, 12.8, 13, 13.6, 14, 15, 16, 18, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×204 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
- **синий фон (синих плашек нет)** (1)
  - `#E0F2FE` — 375px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⏳` — 375px×192 — напр. `div.batch-card > div.batch-amount > div.rate` «⏳»
  - `⚠` — 375px×2 — напр. `div.card > div.form-group > div` «⚠️ TronScan не ответил по 4 кошельк(у/ам) — список переводов»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (3)
  - `Сколько USDT перевели` — 375px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-amount` «Сколько USDT перевели»
  - `THB/USDT` — 375px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-rate` «THB/USDT»
  - `TxHash #1` — 375px×2 — напр. `div.reimburse-tx-hashes > div > input.form-control.reimburse-tx-hash-input` «TxHash #1»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 375px×2 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
- **контраст ниже 4.5:1** (4)
  - `#FFFFFF на #EF4444 = 3.76:1 (13px/600)` — 375px×192 — напр. `div.batch-card > div.batch-amount > button.btn.btn-sm` «Удалить»
  - `#64748B на #E0F2FE = 4.15:1 (12.8px/400)` — 375px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `#F59E0B на #F8FAFC = 2.05:1 (13px/400)` — 375px×26 — напр. `div.batch-info > p > span` «Без хэша»
  - `#FFFFFF на #22C55E = 2.28:1 (14px/600)` — 375px×2 — напр. `div#pendingReimbursementsList > div.card > button.btn.btn-success` «Создать возмещение и рассчитать прибыль»
- **контраст плейсхолдера ниже 4.5:1** (1)
  - `#757575 на #F8FAFC = 4.40:1` — 375px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-rate` «THB/USDT»

### Гейт 4. Ширины: 375px FAIL
- **горизонтальный скролл страницы** (1)
  - `scrollWidth 381 > innerWidth 375` — 375px×1
- **элемент выходит за экран** (2)
  - `right 376 > 375` — 375px×3 — напр. `div#reimbursementsList > div.batch-card > div.batch-amount`
  - `right 381 > 375` — 375px×3 — напр. `div#reimbursementsList > div.batch-card > div.batch-amount`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `36px` — 375px×194 — напр. `div.form-row > div.form-group > button.btn.btn-sm` «+ ещё хэш»
  - `25px` — 375px×7 — напр. `div > label > input.reimburse-alloc`

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (171)
  - `1820,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#357 Igor Pirogov — $1820.00»
  - `1200,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#429 Andrey Zaytsev - Grusha — $1200.00»
  - `155,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#346 Ivan - Grusha — $155.00»
  - `247,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#345 Роман — $247.00»
  - … и ещё 167 (полный список в JSON)

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 2073, контраст проверен у 1436, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (13)
  - `padding 14px` — 1280px×394 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
  - `gap 6px` — 1280px×196 — напр. `div.form-row > div.form-group > button.btn.btn-sm` «+ ещё хэш»
  - `margin-вертикаль 10px` — 1280px×192 — напр. `div#reimbursementsList > div.batch-card`
  - `margin-вертикаль 2px` — 1280px×192 — напр. `div.batch-card > div.batch-info > h4` «Возмещение #252 - Теодор»
  - `padding 6px` — 1280px×170 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 2px` — 1280px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `margin-вертикаль 1px` — 1280px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `margin-вертикаль 6px` — 1280px×10 — напр. `div.card > div.form-group > label.form-label` «Добавить перевод из истории (исходящие USDT) — можно несколь»
  - `margin-вертикаль 14px` — 1280px×6 — напр. `div.card > div.form-row > div.form-group`
  - `padding 20px` — 1280px×6 — напр. `section#reimbursements > div.card`
  - … и ещё 3 (полный список в JSON)
- **шрифт вне токенов** (2)
  - `monospace` — 1280px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `arial` — 1280px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×4 — напр. `section#reimbursements > div.card`
- **цвет текста вне палитры** (4)
  - `#667EEA (ближайший navy-500 #64748B, ΔE 13.2)` — 1280px×192 — напр. `div.batch-card > div.batch-amount > div.thb` «$1538.77»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 1280px×26 — напр. `div.batch-info > p > span` «Без хэша»
  - `#6B7280 (ближайший navy-500 #64748B, ΔE 4.1)` — 1280px×7 — напр. `label > span > span` «25.09, 00:00»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 1280px×1 — напр. `section#reimbursements > div.card > p` «Когда переводите фаундеру USDT за несколько сделок одной тра»
- **фон вне палитры** (4)
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 1280px×192 — напр. `div.batch-card > div.batch-amount > button.btn.btn-sm` «Удалить»
  - `#E0F2FE (ближайший navy-200 #E2E8F0, ΔE 4.7)` — 1280px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 1280px×2 — напр. `div#pendingReimbursementsList > div.card`
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 1280px×2 — напр. `div#pendingReimbursementsList > div.card > button.btn.btn-success` «Создать возмещение и рассчитать прибыль»
- **радиус вне шкалы 8/12/999** (2)
  - `4px` — 1280px×174 — напр. `div.card > div > label`
  - `6px` — 1280px×9 — напр. `div > label > input.reimburse-alloc`
- **кегль вне шкалы** (5)
  - `13px` — 1280px×420 — напр. `div.card > div.form-group > label.form-label` «Добавить перевод из истории (исходящие USDT) — можно несколь»
  - `18px` — 1280px×192 — напр. `div.batch-card > div.batch-amount > div.thb` «$1538.77»
  - `13.6px` — 1280px×191 — напр. `div.card > div.form-group > div` «⚠️ TronScan не ответил по 4 кошельк(у/ам) — список переводов»
  - `12.8px` — 1280px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `15px` — 1280px×2 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
- **вес вне шкалы** (1)
  - `500` — 1280px×8 — напр. `div.card > div.form-group > label.form-label` «Добавить перевод из истории (исходящие USDT) — можно несколь»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `9: 12, 12.8, 13, 13.6, 14, 15, 16, 18, 22` — 1280px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×204 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
- **синий фон (синих плашек нет)** (1)
  - `#E0F2FE` — 1280px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⏳` — 1280px×192 — напр. `div.batch-card > div.batch-amount > div.rate` «⏳»
  - `⚠` — 1280px×2 — напр. `div.card > div.form-group > div` «⚠️ TronScan не ответил по 4 кошельк(у/ам) — список переводов»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (3)
  - `Сколько USDT перевели` — 1280px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-amount` «Сколько USDT перевели»
  - `THB/USDT` — 1280px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-rate` «THB/USDT»
  - `TxHash #1` — 1280px×2 — напр. `div.reimburse-tx-hashes > div > input.form-control.reimburse-tx-hash-input` «TxHash #1»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 1280px×2 — напр. `div.card > div.form-group > select.form-control.reimburse-tx-select` «-- Выбрать из списка или ввести вручную --»
- **контраст ниже 4.5:1** (4)
  - `#FFFFFF на #EF4444 = 3.76:1 (13px/600)` — 1280px×192 — напр. `div.batch-card > div.batch-amount > button.btn.btn-sm` «Удалить»
  - `#64748B на #E0F2FE = 4.15:1 (12.8px/400)` — 1280px×167 — напр. `div.batch-info > p > code` «6681c90af3425398344e4b2c6...»
  - `#F59E0B на #F8FAFC = 2.05:1 (13px/400)` — 1280px×26 — напр. `div.batch-info > p > span` «Без хэша»
  - `#FFFFFF на #22C55E = 2.28:1 (14px/600)` — 1280px×2 — напр. `div#pendingReimbursementsList > div.card > button.btn.btn-success` «Создать возмещение и рассчитать прибыль»
- **контраст плейсхолдера ниже 4.5:1** (1)
  - `#757575 на #F8FAFC = 4.40:1` — 1280px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-rate` «THB/USDT»

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `36px` — 1280px×194 — напр. `div.form-row > div.form-group > button.btn.btn-sm` «+ ещё хэш»
  - `25px` — 1280px×7 — напр. `div > label > input.reimburse-alloc`

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (171)
  - `1820,00 $ × 4` — 1280px×4 — напр. `div.batch-card > div.batch-info > div` «#357 Igor Pirogov — $1820.00»
  - `1200,00 $ × 4` — 1280px×4 — напр. `div.batch-card > div.batch-info > div` «#429 Andrey Zaytsev - Grusha — $1200.00»
  - `155,00 $ × 4` — 1280px×4 — напр. `div.batch-card > div.batch-info > div` «#346 Ivan - Grusha — $155.00»
  - `247,00 $ × 4` — 1280px×4 — напр. `div.batch-card > div.batch-info > div` «#345 Роман — $247.00»
  - … и ещё 167 (полный список в JSON)

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-reimbursements/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-reimbursements/before-karim-1280.png`
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
| 9 | Плейсхолдер вместо подписи / обрезанный плейсхолдер | partial | PASS* |
| 10 | Ряды «подпись — поле — кнопка» выровнены | partial | PASS* |
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
