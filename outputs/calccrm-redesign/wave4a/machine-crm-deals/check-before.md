# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=deals`
DESIGN: `/Users/karimamirov/Desktop/untitled folder/outputs/calccrm-redesign/DESIGN.md`
Ширины: запрошено [375, 1280], обязательны для PASS [375, 768, 1280, 1920]
Роль: karim

_Вердикт машинный: проверена автоматическая часть гейтов. Вкус, иерархия и пункты «MANUAL» ниже остаются человеку._

**Причины вердикта:**
- FAIL в гейтах: 1. Токены, 2. Гардрейлы, 3. Контраст WCAG AA
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
| 4. Ширины | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |
| 5. Текст | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |
| 6. Снимки | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |

## Телефон (≤700px)
- 375px: элементов 791, контраст проверен у 601, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (8)
  - `padding 10px` — 375px×61 — напр. `thead > tr > th` «ID»
  - `gap 6px` — 375px×54 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
  - `padding 14px` — 375px×53 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×7 — напр. `section#deals > div.card`
  - `padding 20px` — 375px×2 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
  - `padding 36px` — 375px×2 — напр. `select#filterStatus` «Все»
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **цвет текста вне палитры** (3)
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 375px×49 — напр. `tbody#dealsTable > tr > td` «$15.00»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×1 — напр. `section#deals > div.crm-section-head > h1` «Сделки»
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 375px×1 — напр. `tbody#dealsTable > tr > td` «-»
- **фон вне палитры** (3)
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 375px×47 — напр. `tr > td > span.badge.badge-completed` «Завершена»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 375px×3 — напр. `tr > td > span.badge.badge-pending` «Ожидает»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×2 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×2 — напр. `section#deals > div.card`
- **кегль вне шкалы** (1)
  - `13px` — 375px×52 — напр. `tr > td > button.btn.btn-sm` «Детали»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `5: 12, 13, 14, 16, 22` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×54 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×11 — напр. `thead > tr > th` «ID»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Имя менеджера` — 375px×1 — напр. `input#filterManager` «Имя менеджера»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (3)
  - `#10B981 на #FFFFFF = 2.54:1 (14px/600)` — 375px×49 — напр. `tbody#dealsTable > tr > td` «$15.00»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 375px×2 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
  - `#EF4444 на #FFFFFF = 3.76:1 (14px/600)` — 375px×1 — напр. `tbody#dealsTable > tr > td` «-»
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 375px×2 — напр. `select#filterStatus` «Все»

### Гейт 4. Ширины: 375px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `36px` — 375px×51 — напр. `tr > td > button.btn.btn-sm` «Детали»

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (9)
  - `12500 ฿ × 4` — 375px×4 — напр. `tbody#dealsTable > tr > td` «12 500 ฿»
  - `1000,00 $ × 3` — 375px×3 — напр. `tbody#dealsTable > tr > td` «$1000.00»
  - `45000 ฿ × 3` — 375px×3 — напр. `tbody#dealsTable > tr > td` «45 000 ฿»
  - `18000 ฿ × 2` — 375px×2 — напр. `tbody#dealsTable > tr > td` «18 000 ฿»
  - … и ещё 5 (полный список в JSON)

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 794, контраст проверен у 601, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (9)
  - `padding 10px` — 1280px×61 — напр. `thead > tr > th` «ID»
  - `gap 6px` — 1280px×54 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
  - `padding 14px` — 1280px×52 — напр. `tr > td > button.btn.btn-sm` «Детали»
  - `margin-вертикаль 14px` — 1280px×5 — напр. `div.card > div.form-row > div.form-group`
  - `padding 20px` — 1280px×4 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
  - `padding 36px` — 1280px×2 — напр. `select#filterStatus` «Все»
  - `padding 6px` — 1280px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 1280px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **цвет текста вне палитры** (3)
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 1280px×49 — напр. `tbody#dealsTable > tr > td` «$15.00»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 1280px×1 — напр. `section#deals > div.crm-section-head > h1` «Сделки»
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 1280px×1 — напр. `tbody#dealsTable > tr > td` «-»
- **фон вне палитры** (3)
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 1280px×47 — напр. `tr > td > span.badge.badge-completed` «Завершена»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 1280px×3 — напр. `tr > td > span.badge.badge-pending` «Ожидает»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×2 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×2 — напр. `section#deals > div.card`
- **кегль вне шкалы** (1)
  - `13px` — 1280px×52 — напр. `tr > td > button.btn.btn-sm` «Детали»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `5: 12, 13, 14, 16, 22` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×54 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 1280px×11 — напр. `thead > tr > th` «ID»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Имя менеджера` — 1280px×1 — напр. `input#filterManager` «Имя менеджера»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (3)
  - `#10B981 на #FFFFFF = 2.54:1 (14px/600)` — 1280px×49 — напр. `tbody#dealsTable > tr > td` «$15.00»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 1280px×2 — напр. `section#deals > div.crm-section-head > button.btn.btn-primary` «+ Создать сделку»
  - `#EF4444 на #FFFFFF = 3.76:1 (14px/600)` — 1280px×1 — напр. `tbody#dealsTable > tr > td` «-»
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 1280px×2 — напр. `select#filterStatus` «Все»

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `36px` — 1280px×51 — напр. `tr > td > button.btn.btn-sm` «Детали»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (9)
  - `12500 ฿ × 4` — 1280px×4 — напр. `tbody#dealsTable > tr > td` «12 500 ฿»
  - `1000,00 $ × 3` — 1280px×3 — напр. `tbody#dealsTable > tr > td` «$1000.00»
  - `45000 ฿ × 3` — 1280px×3 — напр. `tbody#dealsTable > tr > td` «45 000 ฿»
  - `18000 ฿ × 2` — 1280px×2 — напр. `tbody#dealsTable > tr > td` «18 000 ฿»
  - … и ещё 5 (полный список в JSON)

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-deals/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-deals/before-karim-1280.png`
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
| 6 | Цветные полосы слева, синие подсказки, оранжевый вне кнопки | partial | PASS* |
| 7 | Адрес/хеш в одну строку; ничего шире экрана | auto | PASS |
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
  - `uppercase` — 375px×11, 1280px×11 — напр. `thead > tr > th` «ID»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
