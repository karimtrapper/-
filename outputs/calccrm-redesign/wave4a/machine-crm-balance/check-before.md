# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=balance`
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
- 375px: элементов 75, контраст проверен у 47, главных кнопок 0, адресов 4

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (7)
  - `gap 6px` — 375px×10 — напр. `button#btnSubBinance` «Binance (USDT)»
  - `padding 14px` — 375px×7 — напр. `div.container`
  - `padding 5px` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «×»
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×1 — напр. `section#balance > div.card`
  - `padding 20px` — 375px×1 — напр. `div#subtabBinance > div > button.btn.btn-primary` «+ Добавить кошелек»
- **шрифт вне токенов** (2)
  - `monospace` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×4 — напр. `section#balance > div.card`
- **радиус вне шкалы 8/12/999** (2)
  - `6px` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «⟳ Сверить с сетью»
  - `10px` — 375px×1 — напр. `section#balance > div.card > div`
- **кегль вне шкалы** (4)
  - `11.2px` — 375px×6 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «×»
  - `13px` — 375px×3 — напр. `button#btnSubBinance` «Binance (USDT)»
  - `12.8px` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `24px` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»
- **фон вне палитры** (2)
  - `#EFEFEF (ближайший page-mist #F8FAFC, ΔE 2.5)` — 375px×5 — напр. `button#btnSubCash` «Наличные (THB)»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×2 — напр. `button#btnSubBinance` «Binance (USDT)»
- **цвет текста вне палитры** (4)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 375px×8 — напр. `button#btnSubCash` «Наличные (THB)»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»
  - `#999999 (ближайший navy-400 #94A3B8, ΔE 10.2)` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
- **вес вне шкалы** (1)
  - `800` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `8: 11.2, 12, 12.8, 13, 14, 16, 22, 24` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 700, 800` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×10 — напр. `button#btnSubBinance` «Binance (USDT)»
- **кнопка-иконка без видимой подписи** (1)
  - `×` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «×»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **адрес/хеш не моноширинным шрифтом** (1)
  - `inter` — 375px×1 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
- (warn) **адрес/хеш не Mono 14px** (1)
  - `11.2px` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (3)
  - `#999999 на #FFFFFF = 2.85:1 (11.2px/400)` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `#FFFFFF на #F97316 = 2.80:1 (13px/600)` — 375px×1 — напр. `button#btnSubBinance` «Binance (USDT)»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 375px×1 — напр. `div#subtabBinance > div > button.btn.btn-primary` «+ Добавить кошелек»
- **контраст ниже 3:1** (1)
  - `#10B981 на #FFFFFF = 2.54:1 (24px/800)` — 375px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»

### Гейт 4. Ширины: 375px FAIL
- **горизонтальный скролл страницы** (1)
  - `scrollWidth 524 > innerWidth 375` — 375px×1
- **элемент выходит за экран** (1)
  - `right 524 > 375` — 375px×1 — напр. `div#subtabBinance > div > button.btn.btn-primary` «+ Добавить кошелек»
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `36px` — 375px×6 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «×»

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (1)
  - `0,00 $ × 2` — 375px×2 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 78, контраст проверен у 47, главных кнопок 0, адресов 4
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (7)
  - `gap 6px` — 1280px×10 — напр. `button#btnSubBinance` «Binance (USDT)»
  - `padding 14px` — 1280px×3 — напр. `button#btnSubBinance` «Binance (USDT)»
  - `padding 5px` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «×»
  - `padding 20px` — 1280px×2 — напр. `section#balance > div.card`
  - `padding 6px` — 1280px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1 — напр. `div.container`
- **шрифт вне токенов** (2)
  - `monospace` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `arial` — 1280px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×4 — напр. `section#balance > div.card`
- **радиус вне шкалы 8/12/999** (2)
  - `6px` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «⟳ Сверить с сетью»
  - `10px` — 1280px×1 — напр. `section#balance > div.card > div`
- **кегль вне шкалы** (4)
  - `11.2px` — 1280px×6 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «×»
  - `13px` — 1280px×3 — напр. `button#btnSubBinance` «Binance (USDT)»
  - `12.8px` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `24px` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»
- **фон вне палитры** (2)
  - `#EFEFEF (ближайший page-mist #F8FAFC, ΔE 2.5)` — 1280px×5 — напр. `button#btnSubCash` «Наличные (THB)»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×2 — напр. `button#btnSubBinance` «Binance (USDT)»
- **цвет текста вне палитры** (4)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 1280px×8 — напр. `button#btnSubCash` «Наличные (THB)»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»
  - `#999999 (ближайший navy-400 #94A3B8, ΔE 10.2)` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
- **вес вне шкалы** (1)
  - `800` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `8: 11.2, 12, 12.8, 13, 14, 16, 22, 24` — 1280px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 700, 800` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×10 — напр. `button#btnSubBinance` «Binance (USDT)»
- **кнопка-иконка без видимой подписи** (1)
  - `×` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > button.btn.btn-sm` «×»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **адрес/хеш не моноширинным шрифтом** (1)
  - `inter` — 1280px×1 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
- (warn) **адрес/хеш не Mono 14px** (1)
  - `11.2px` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (3)
  - `#999999 на #FFFFFF = 2.85:1 (11.2px/400)` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div` «TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74»
  - `#FFFFFF на #F97316 = 2.80:1 (13px/600)` — 1280px×1 — напр. `button#btnSubBinance` «Binance (USDT)»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 1280px×1 — напр. `div#subtabBinance > div > button.btn.btn-primary` «+ Добавить кошелек»
- **контраст ниже 3:1** (1)
  - `#10B981 на #FFFFFF = 2.54:1 (24px/800)` — 1280px×3 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `36px` — 1280px×9 — напр. `button#btnSubBinance` «Binance (USDT)»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (1)
  - `0,00 $ × 2` — 1280px×2 — напр. `div#walletsSummaryGrid > div.stat-card > div.stat-value` «$0.00»

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-balance/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-balance/before-karim-1280.png`
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

## Гардрейлы (18)

| № | Запрет | Охват | Вердикт |
|---|---|---|---|
| 1 | Один шрифт + моно, 4 кегля, 3 веса | auto | FAIL |
| 2 | Цвета/отступы/радиусы/тени только из токенов | auto | FAIL |
| 3 | Сосиски, градиенты, hover-зум, анимации появления | partial | FAIL |
| 4 | Кнопки без глагола, две главные, иконка без подписи | partial | FAIL |
| 5 | Эмодзи вместо иконок; один размер иконок | partial | PASS* |
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

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
