# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=partners`
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
- 375px: элементов 115, контраст проверен у 64, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (9)
  - `gap 6px` — 375px×22 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
  - `padding 6px` — 375px×15 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 10px` — 375px×14 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `margin-вертикаль 2px` — 375px×7 — напр. `div > div > div` «Наценка: 1.5%»
  - `margin-вертикаль 6px` — 375px×7 — напр. `div > div > div`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `padding 14px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×1 — напр. `section#partners > div.card`
  - `padding 20px` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
- **шрифт вне токенов** (1)
  - `arial` — 375px×9 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#partners > div.card`
- **кегль вне шкалы** (1)
  - `14.4px` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
- **фон вне палитры** (3)
  - `#EFF6FF (ближайший navy-100 #F1F5F9, ΔE 2.3)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Откл.»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
- **цвет рамки вне палитры** (1)
  - `#E5E7EB (ближайший navy-200 #E2E8F0, ΔE 2.2)` — 375px×28 — напр. `div#partnersList > div`
- **радиус вне шкалы 8/12/999** (1)
  - `6px` — 375px×21 — напр. `div > div > input` «http://127.0.0.1:59110/partner/d62da961ee89c206fce75cecb66ec»
- **цвет текста вне палитры** (2)
  - `#3B82F6 (ближайший navy-500 #64748B, ΔE 15.0)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `#D97706 (ближайший action-coral #C2410C, ΔE 18.4)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Откл.»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `5: 12, 14, 14.4, 16, 22` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×15 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
- **синий фон (синих плашек нет)** (1)
  - `#EFF6FF` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (3)
  - `#3B82F6 на #EFF6FF = 3.38:1 (12px/600)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `#D97706 на #FEF3C7 = 2.86:1 (12px/600)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Откл.»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»

### Гейт 4. Ширины: 375px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `36px` — 375px×14 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `24px` — 375px×7 — напр. `div > div > input` «http://127.0.0.1:59110/partner/d62da961ee89c206fce75cecb66ec»

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 118, контраст проверен у 64, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (8)
  - `gap 6px` — 1280px×22 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
  - `padding 6px` — 1280px×15 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 10px` — 1280px×14 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `margin-вертикаль 2px` — 1280px×7 — напр. `div > div > div` «Наценка: 1.5%»
  - `margin-вертикаль 6px` — 1280px×7 — напр. `div > div > div`
  - `padding 20px` — 1280px×2 — напр. `section#partners > div.card`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 1280px×9 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×1 — напр. `section#partners > div.card`
- **кегль вне шкалы** (1)
  - `14.4px` — 1280px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
- **фон вне палитры** (3)
  - `#EFF6FF (ближайший navy-100 #F1F5F9, ΔE 2.3)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Откл.»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
- **цвет рамки вне палитры** (1)
  - `#E5E7EB (ближайший navy-200 #E2E8F0, ΔE 2.2)` — 1280px×28 — напр. `div#partnersList > div`
- **радиус вне шкалы 8/12/999** (1)
  - `6px` — 1280px×21 — напр. `div > div > input` «http://127.0.0.1:59110/partner/d62da961ee89c206fce75cecb66ec»
- **цвет текста вне палитры** (2)
  - `#3B82F6 (ближайший navy-500 #64748B, ΔE 15.0)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `#D97706 (ближайший action-coral #C2410C, ΔE 18.4)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Откл.»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `5: 12, 14, 14.4, 16, 22` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×15 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»
- **синий фон (синих плашек нет)** (1)
  - `#EFF6FF` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (3)
  - `#3B82F6 на #EFF6FF = 3.38:1 (12px/600)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `#D97706 на #FEF3C7 = 2.86:1 (12px/600)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Откл.»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 1280px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Добавить партнёра»

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `36px` — 1280px×14 — напр. `div > div > button.btn.btn-sm` «Изм.»
  - `24px` — 1280px×7 — напр. `div > div > input` «http://127.0.0.1:59110/partner/d62da961ee89c206fce75cecb66ec»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
находок нет

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-partners/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-partners/before-karim-1280.png`
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

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
