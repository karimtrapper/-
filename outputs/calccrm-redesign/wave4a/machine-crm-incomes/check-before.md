# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=incomes`
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
- 375px: элементов 418, контраст проверен у 245, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (9)
  - `padding 10px` — 375px×10 — напр. `thead > tr > th`
  - `gap 6px` — 375px×7 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
  - `padding 20px` — 375px×3 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
  - `padding 5px` — 375px×2 — напр. `div.card > div > button.btn.btn-secondary` «← Назад»
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `padding 14px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×1 — напр. `section#incomes > div.card`
  - `gap 10px` — 375px×1 — напр. `section#incomes > div.card > div`
- **шрифт вне токенов** (1)
  - `arial` — 375px×23 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#incomes > div.card`
- **кегль вне шкалы** (5)
  - `13.3333px` — 375px×21 — напр. `tr > td > input.incAmt` «536274.36»
  - `12.8px` — 375px×19 — напр. `tr > td > div` «клиент платил 540 054,74»
  - `14.4px` — 375px×3 — напр. `div#incomesSummary > div` «🗄 до запуска учёта (раньше 2026-08-19): 410 150 282,67 ₽ — »
  - `13.6px` — 375px×2 — напр. `div.card > div > button.btn.btn-secondary` «← Назад»
  - `16.8px` — 375px×1 — напр. `div#incomesSummary > b` «На счёте не сконвертировано: 1 304 910,75 ₽»
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **цвет текста вне палитры** (2)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 375px×21 — напр. `tr > td > input.incAmt` «536274.36»
  - `#0000EE (ближайший navy-700 #334155, ΔE 19.3)` — 375px×20 — напр. `tr > td > a` «✏️»
- **цвет рамки вне палитры** (1)
  - `#767676 (ближайший navy-500 #64748B, ΔE 11.0)` — 375px×84 — напр. `tr > td > input.incAmt` «536274.36»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `9: 12, 12.8, 13.3333, 13.6, 14, 14.4, 16, 16.8, 22` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×5 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×8 — напр. `thead > tr > th` «Дата»
- **эмодзи в кнопке/ссылке/табе/заголовке** (1)
  - `✏` — 375px×20 — напр. `tr > td > a` «✏️»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⏳` — 375px×20 — напр. `tr > td > span` «⏳ лежит на счёте»
  - `🗄` — 375px×1 — напр. `div#incomesSummary > div` «🗄 до запуска учёта (раньше 2026-08-19): 410 150 282,67 ₽ — к»
- (warn) **текст набран капслоком руками** (1)
  - `АМИРОВ КАРИМ КАРНЕЛЬЕВИЧ` — 375px×1 — напр. `tbody#incomesTable > tr > td` «АМИРОВ КАРИМ КАРНЕЛЬЕВИЧ»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (4)
  - `#CBD5E1 на #FFFFFF = 1.48:1 (14px/400)` — 375px×20 — напр. `tr > td > span` «—»
  - `#94A3B8 на #FFFFFF = 2.56:1 (14px/400)` — 375px×20 — напр. `tr > td > span` «⏳ лежит на счёте»
  - `#94A3B8 на #FFFFFF = 2.56:1 (12.8px/400)` — 375px×19 — напр. `tr > td > div` «клиент платил 540 054,74»
  - `#94A3B8 на #FFFFFF = 2.56:1 (14.4px/400)` — 375px×1 — напр. `div#incomesSummary > div` «🗄 до запуска учёта (раньше 2026-08-19): 410 150 282,67 ₽ — »

### Гейт 4. Ширины: 375px FAIL
- **горизонтальный скролл страницы** (1)
  - `scrollWidth 947 > innerWidth 375` — 375px×1
- **элемент выходит за экран** (10)
  - `right 947 > 375` — 375px×10 — напр. `section#incomes > div.card > table.table`
  - `right 514 > 375` — 375px×4 — напр. `thead > tr > th` «Конвертировать»
  - `right 611 > 375` — 375px×4 — напр. `thead > tr > th` «Вид»
  - `right 707 > 375` — 375px×4 — напр. `thead > tr > th` «Источник»
  - `right 786 > 375` — 375px×4 — напр. `thead > tr > th` «Сделка»
  - `right 905 > 375` — 375px×4 — напр. `thead > tr > th` «Конвертация»
  - `right 502 > 375` — 375px×3 — напр. `tr > td > input.incAmt`
  - `right 637 > 375` — 375px×3 — напр. `tr > td > span` «—»
  - `right 882 > 375` — 375px×2 — напр. `tr > td > span` «⏳ лежит на счёте»
  - `right 935 > 375` — 375px×2 — напр. `tr > td > a` «✏️»
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `19px` — 375px×21 — напр. `tr > td > input.incAmt` «536274.36»

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `34755,00 ₽ × 5` — 375px×5 — напр. `tbody#incomesTable > tr > td` «34 755,00 ₽»
  - `39720,00 ₽ × 2` — 375px×2 — напр. `tbody#incomesTable > tr > td` «39 720,00 ₽»
  - `19860,00 ₽ × 2` — 375px×2 — напр. `tbody#incomesTable > tr > td` «19 860,00 ₽»
  - `9,93 ₽ × 2` — 375px×2 — напр. `tbody#incomesTable > tr > td` «9,93 ₽»

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 421, контраст проверен у 245, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (8)
  - `padding 10px` — 1280px×10 — напр. `thead > tr > th`
  - `gap 6px` — 1280px×7 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
  - `padding 20px` — 1280px×4 — напр. `section#incomes > div.card`
  - `padding 5px` — 1280px×2 — напр. `div.card > div > button.btn.btn-secondary` «← Назад»
  - `padding 6px` — 1280px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `gap 10px` — 1280px×1 — напр. `section#incomes > div.card > div`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 1280px×23 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×1 — напр. `section#incomes > div.card`
- **кегль вне шкалы** (5)
  - `13.3333px` — 1280px×21 — напр. `tr > td > input.incAmt` «536274.36»
  - `12.8px` — 1280px×19 — напр. `tr > td > div` «клиент платил 540 054,74»
  - `14.4px` — 1280px×3 — напр. `div#incomesSummary > div` «🗄 до запуска учёта (раньше 2026-08-19): 410 150 282,67 ₽ — »
  - `13.6px` — 1280px×2 — напр. `div.card > div > button.btn.btn-secondary` «← Назад»
  - `16.8px` — 1280px×1 — напр. `div#incomesSummary > b` «На счёте не сконвертировано: 1 304 910,75 ₽»
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×1 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **цвет текста вне палитры** (2)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 1280px×21 — напр. `tr > td > input.incAmt` «536274.36»
  - `#0000EE (ближайший navy-700 #334155, ΔE 19.3)` — 1280px×20 — напр. `tr > td > a` «✏️»
- **цвет рамки вне палитры** (1)
  - `#767676 (ближайший navy-500 #64748B, ΔE 11.0)` — 1280px×84 — напр. `tr > td > input.incAmt` «536274.36»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `9: 12, 12.8, 13.3333, 13.6, 14, 14.4, 16, 16.8, 22` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×5 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 1280px×8 — напр. `thead > tr > th` «Дата»
- **эмодзи в кнопке/ссылке/табе/заголовке** (1)
  - `✏` — 1280px×20 — напр. `tr > td > a` «✏️»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⏳` — 1280px×20 — напр. `tr > td > span` «⏳ лежит на счёте»
  - `🗄` — 1280px×1 — напр. `div#incomesSummary > div` «🗄 до запуска учёта (раньше 2026-08-19): 410 150 282,67 ₽ — к»
- (warn) **текст набран капслоком руками** (1)
  - `АМИРОВ КАРИМ КАРНЕЛЬЕВИЧ` — 1280px×1 — напр. `tbody#incomesTable > tr > td` «АМИРОВ КАРИМ КАРНЕЛЬЕВИЧ»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (4)
  - `#CBD5E1 на #FFFFFF = 1.48:1 (14px/400)` — 1280px×20 — напр. `tr > td > span` «—»
  - `#94A3B8 на #FFFFFF = 2.56:1 (14px/400)` — 1280px×20 — напр. `tr > td > span` «⏳ лежит на счёте»
  - `#94A3B8 на #FFFFFF = 2.56:1 (12.8px/400)` — 1280px×19 — напр. `tr > td > div` «клиент платил 540 054,74»
  - `#94A3B8 на #FFFFFF = 2.56:1 (14.4px/400)` — 1280px×1 — напр. `div#incomesSummary > div` «🗄 до запуска учёта (раньше 2026-08-19): 410 150 282,67 ₽ — »

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `19px` — 1280px×21 — напр. `tr > td > input.incAmt` «536274.36»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `34755,00 ₽ × 5` — 1280px×5 — напр. `tbody#incomesTable > tr > td` «34 755,00 ₽»
  - `39720,00 ₽ × 2` — 1280px×2 — напр. `tbody#incomesTable > tr > td` «39 720,00 ₽»
  - `19860,00 ₽ × 2` — 1280px×2 — напр. `tbody#incomesTable > tr > td` «19 860,00 ₽»
  - `9,93 ₽ × 2` — 1280px×2 — напр. `tbody#incomesTable > tr > td` «9,93 ₽»

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-incomes/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-incomes/before-karim-1280.png`
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

## Гардрейлы (18)

| № | Запрет | Охват | Вердикт |
|---|---|---|---|
| 1 | Один шрифт + моно, 4 кегля, 3 веса | auto | FAIL |
| 2 | Цвета/отступы/радиусы/тени только из токенов | auto | FAIL |
| 3 | Сосиски, градиенты, hover-зум, анимации появления | partial | FAIL |
| 4 | Кнопки без глагола, две главные, иконка без подписи | partial | PASS* |
| 5 | Эмодзи вместо иконок; один размер иконок | partial | FAIL |
| 6 | Цветные полосы слева, синие подсказки, оранжевый вне кнопки | partial | PASS* |
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

## Дополнительно (Don't из DESIGN.md)
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×8, 1280px×8 — напр. `thead > tr > th` «Дата»
- **текст набран капслоком руками** (1)
  - `АМИРОВ КАРИМ КАРНЕЛЬЕВИЧ` — 375px×1, 1280px×1 — напр. `tbody#incomesTable > tr > td` «АМИРОВ КАРИМ КАРНЕЛЬЕВИЧ»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
