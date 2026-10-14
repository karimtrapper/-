# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=documents`
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
- 375px: элементов 306, контраст проверен у 220, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (12)
  - `gap 6px` — 375px×53 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
  - `padding 6px` — 375px×27 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 11px` — 375px×26 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.btn-primary` «+ Платёж»
  - `padding 18px` — 375px×24 — напр. `div#docsList > div.docs-client > div.docs-client-head`
  - `padding 10px` — 375px×13 — напр. `div.docs-deal > span > span.badge.badge-pending` «черновик»
  - `padding 13px` — 375px×11 — напр. `div#docsList > div.docs-client > div.docs-client-head`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `padding 14px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×1 — напр. `section#documents > div.card`
  - `margin-вертикаль 5.6px` — 375px×1 — напр. `div.docs-head > div > p.docs-lede` «Договор подписывается на клиента, тип сделки, валютную пару »
  - … и ещё 2 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#documents > div.card`
- **цвет рамки вне палитры** (1)
  - `#767676 (ближайший navy-500 #64748B, ΔE 11.0)` — 375px×4 — напр. `input#docsSearch`
- **кегль вне шкалы** (8)
  - `13.76px` — 375px×39 — напр. `div.docs-client > div.docs-deal > span.docs-num` «RUB → USD»
  - `12.48px` — 375px×26 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.btn-primary` «+ Платёж»
  - `12.8px` — 375px×22 — напр. `div.docs-client > div.docs-client-head > span.docs-client-meta` «паспорт 76 7371427»
  - `13.92px` — 375px×13 — напр. `div.docs-client > div.docs-deal > span` «Фрихолд»
  - `11.4667px` — 375px×13 — напр. `div.docs-deal > span.docs-num > small` «По реквизитам»
  - `13.3333px` — 375px×13 — напр. `div.docs-deal > span.docs-money-cell > small` «RUB / USD»
  - `15.2px` — 375px×11 — напр. `div.docs-client > div.docs-client-head > span.docs-client-name` «Шпакова Елена Николаевна»
  - `14.4px` — 375px×1 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
- **фон вне палитры** (3)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×14 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 375px×13 — напр. `div.docs-deal > span > span.badge.badge-pending` «черновик»
  - `#EFEFEF (ближайший page-mist #F8FAFC, ΔE 2.5)` — 375px×13 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.docs-btn-sm` «Открыть»
- **вес вне шкалы** (1)
  - `650` — 375px×11 — напр. `div.docs-client > div.docs-client-head > span.docs-client-name` «Шпакова Елена Николаевна»
- **цвет текста вне палитры** (2)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 375px×13 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.docs-btn-sm` «Открыть»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×11 — напр. `div.docs-client > div.docs-client-head > span.docs-client-name` «Шпакова Елена Николаевна»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `12: 11.4667, 12, 12.48, 12.8, 13.3333, 13.76, 13.92, 14, 14.4, 15.2, 16, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 650, 700` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×27 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Клиент или номер` — 375px×1 — напр. `input#docsSearch` «Клиент или номер»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (2)
  - `#FFFFFF на #F97316 = 2.80:1 (12.48px/600)` — 375px×13 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.btn-primary` «+ Платёж»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 375px×1 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»

### Гейт 4. Ширины: 375px FAIL
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `19px и 58px (Δверха 20px)` — 375px×1 — напр. `input#docsSearch`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `19px` — 375px×1 — напр. `input#docsSearch`

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `11000,00 USDT × 2` — 375px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «11 000,00 USDT»
  - `10000,00 USD × 2` — 375px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «10 000,00 USD»
  - `266000,00 ₽ × 2` — 375px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «266 000,00 RUB»
  - `100000,00 THB × 2` — 375px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «100 000,00 THB»

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 309, контраст проверен у 220, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (11)
  - `gap 6px` — 1280px×40 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
  - `padding 6px` — 1280px×27 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 11px` — 1280px×26 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.btn-primary` «+ Платёж»
  - `padding 18px` — 1280px×24 — напр. `div#docsList > div.docs-client > div.docs-client-head`
  - `padding 10px` — 1280px×13 — напр. `div.docs-deal > span > span.badge.badge-pending` «черновик»
  - `padding 13px` — 1280px×11 — напр. `div#docsList > div.docs-client > div.docs-client-head`
  - `padding 20px` — 1280px×2 — напр. `section#documents > div.card`
  - `margin-вертикаль 5.6px` — 1280px×1 — напр. `div.docs-head > div > p.docs-lede` «Договор подписывается на клиента, тип сделки, валютную пару »
  - `margin-вертикаль 18px` — 1280px×1 — напр. `div#docsList`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - … и ещё 1 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 1280px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×1 — напр. `section#documents > div.card`
- **цвет рамки вне палитры** (1)
  - `#767676 (ближайший navy-500 #64748B, ΔE 11.0)` — 1280px×4 — напр. `input#docsSearch`
- **кегль вне шкалы** (8)
  - `13.76px` — 1280px×39 — напр. `div.docs-client > div.docs-deal > span.docs-num` «RUB → USD»
  - `12.48px` — 1280px×26 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.btn-primary` «+ Платёж»
  - `12.8px` — 1280px×22 — напр. `div.docs-client > div.docs-client-head > span.docs-client-meta` «паспорт 76 7371427»
  - `13.92px` — 1280px×13 — напр. `div.docs-client > div.docs-deal > span` «Фрихолд»
  - `11.4667px` — 1280px×13 — напр. `div.docs-deal > span.docs-num > small` «По реквизитам»
  - `13.3333px` — 1280px×13 — напр. `div.docs-deal > span.docs-money-cell > small` «RUB / USD»
  - `15.2px` — 1280px×11 — напр. `div.docs-client > div.docs-client-head > span.docs-client-name` «Шпакова Елена Николаевна»
  - `14.4px` — 1280px×1 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
- **фон вне палитры** (3)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×14 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 1280px×13 — напр. `div.docs-deal > span > span.badge.badge-pending` «черновик»
  - `#EFEFEF (ближайший page-mist #F8FAFC, ΔE 2.5)` — 1280px×13 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.docs-btn-sm` «Открыть»
- **вес вне шкалы** (1)
  - `650` — 1280px×11 — напр. `div.docs-client > div.docs-client-head > span.docs-client-name` «Шпакова Елена Николаевна»
- **цвет текста вне палитры** (2)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 1280px×13 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.docs-btn-sm` «Открыть»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 1280px×11 — напр. `div.docs-client > div.docs-client-head > span.docs-client-name` «Шпакова Елена Николаевна»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `12: 11.4667, 12, 12.48, 12.8, 13.3333, 13.76, 13.92, 14, 14.4, 15.2, 16, 22` — 1280px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 650, 700` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×27 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Клиент или номер` — 1280px×1 — напр. `input#docsSearch` «Клиент или номер»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (2)
  - `#FFFFFF на #F97316 = 2.80:1 (12.48px/600)` — 1280px×13 — напр. `div.docs-deal > span.docs-deal-actions > button.btn.btn-primary` «+ Платёж»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 1280px×1 — напр. `div.docs-head > div > button.btn.btn-primary` «Новый договор»

### Гейт 4. Ширины: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `19px и 48px (Δверха 15px)` — 1280px×1 — напр. `input#docsSearch`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `19px` — 1280px×1 — напр. `input#docsSearch`

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `11000,00 USDT × 2` — 1280px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «11 000,00 USDT»
  - `10000,00 USD × 2` — 1280px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «10 000,00 USD»
  - `266000,00 ₽ × 2` — 1280px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «266 000,00 RUB»
  - `100000,00 THB × 2` — 1280px×2 — напр. `div.docs-client > div.docs-deal > span.docs-money-cell` «100 000,00 THB»

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-documents/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-documents/before-karim-1280.png`
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
