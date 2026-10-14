# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59104/crm`
DESIGN: `/Users/karimamirov/Desktop/untitled folder/outputs/calccrm-redesign/DESIGN.md`
Ширины: запрошено [375, 768, 1280, 1920], обязательны для PASS [375, 768, 1280, 1920]
Роль: karim

_Вердикт машинный: проверена автоматическая часть гейтов. Вкус, иерархия и пункты «MANUAL» ниже остаются человеку._

**Причины вердикта:**
- FAIL в гейтах: 1. Токены, 2. Гардрейлы, 4. Ширины
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

| Гейт | Вердикт | 375 | 768 | 1280 | 1920 |
|---|---|---|---|---|---|
| 1. Токены | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 2. Гардрейлы | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 3. Контраст WCAG AA | **PASS** | PASS | PASS | PASS | PASS |
| 4. Ширины | **FAIL** | FAIL | FAIL | PASS | PASS |
| 5. Текст | **PASS** | PASS | PASS | PASS | PASS |
| 6. Снимки | **BLOCKED** | PASS | PASS | PASS | PASS |

## Телефон (≤700px)
- 375px: элементов 74, контраст проверен у 43, главных кнопок 0, адресов 0

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
  - `arial` — 375px×3 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#incomes > div.card`
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **кегль вне шкалы** (3)
  - `13.6px` — 375px×2 — напр. `div.card > div > button.btn.btn-secondary` «← Назад»
  - `14.4px` — 375px×1 — напр. `div.card > div > label` «Строк на странице:»
  - `13.3333px` — 375px×1 — напр. `select#incomesPerPage` «20»
- **цвет текста вне палитры** (1)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 375px×1 — напр. `select#incomesPerPage` «20»
- **цвет рамки вне палитры** (1)
  - `#767676 (ближайший navy-500 #64748B, ΔE 11.0)` — 375px×4 — напр. `select#incomesPerPage` «20»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `7: 12, 13.3333, 13.6, 14, 14.4, 16, 22` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×5 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×8 — напр. `thead > tr > th` «Дата»
- **ошибка в консоли** (4)
  - `Не удалось обновить счётчик заявок на выплату: {stack: "TypeError: Failed to fetch
    at refreshPayoutAttention (http:/` — 375px×2
  - `{'column': 35, 'line': 11225, 'text': 'TypeError: Failed to fetch\n    at loadIncomes (http://127.0.0.1:59104/crm:11226:` — 375px×1
  - `{stack: "TypeError: Failed to fetch
    at rxLoad (http://1….0.0.1:59104/crm:3772:40)
    at <anonymous>:1:55", message:` — 375px×1
  - `Не удалось загрузить курс: {stack: "TypeError: Failed to fetch
    at loadCurrentRate (http://127.0.0.1:59104/crm:3720:3` — 375px×1
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

### Гейт 3. Контраст WCAG AA: 375px PASS
находок нет

### Гейт 4. Ширины: 375px FAIL
- **горизонтальный скролл страницы** (1)
  - `scrollWidth 829 > innerWidth 375` — 375px×1
- **элемент выходит за экран** (6)
  - `right 829 > 375` — 375px×4 — напр. `section#incomes > div.card > table.table`
  - `right 459 > 375` — 375px×1 — напр. `thead > tr > th` «Конвертировать»
  - `right 511 > 375` — 375px×1 — напр. `thead > tr > th` «Вид»
  - `right 608 > 375` — 375px×1 — напр. `thead > tr > th` «Источник»
  - `right 686 > 375` — 375px×1 — напр. `thead > tr > th` «Сделка»
  - `right 805 > 375` — 375px×1 — напр. `thead > tr > th` «Конвертация»
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `19px` — 375px×1 — напр. `select#incomesPerPage` «20
30
50
все»

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: элементов 72, контраст проверен у 38, главных кнопок 0, адресов 0
- 1280px: элементов 77, контраст проверен у 43, главных кнопок 0, адресов 0
- 1920px: элементов 77, контраст проверен у 43, главных кнопок 0, адресов 0

### Гейт 1. Токены: 768px FAIL · 1280px FAIL · 1920px FAIL
- **отступ вне шкалы 4/8/12/16/24** (9)
  - `padding 10px` — 768px×10, 1280px×10, 1920px×10 — напр. `thead > tr > th`
  - `gap 6px` — 768px×7, 1280px×7, 1920px×7 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
  - `padding 20px` — 768px×5, 1280px×4, 1920px×4 — напр. `div.container`
  - `padding 5px` — 768px×2, 1280px×2, 1920px×2 — напр. `div.card > div > button.btn.btn-secondary` «← Назад»
  - `padding 6px` — 768px×1, 1280px×1, 1920px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `gap 10px` — 768px×1, 1280px×1, 1920px×1 — напр. `section#incomes > div.card > div`
  - `padding 32px` — 1280px×1, 1920px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1, 1920px×1 — напр. `div.container`
  - `padding 100px` — 768px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 768px×3, 1280px×3, 1920px×3 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 768px×1, 1280px×1, 1920px×1 — напр. `section#incomes > div.card`
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 768px×1, 1280px×1, 1920px×1 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **кегль вне шкалы** (3)
  - `13.6px` — 768px×2, 1280px×2, 1920px×2 — напр. `div.card > div > button.btn.btn-secondary` «← Назад»
  - `14.4px` — 768px×1, 1280px×1, 1920px×1 — напр. `div.card > div > label` «Строк на странице:»
  - `13.3333px` — 768px×1, 1280px×1, 1920px×1 — напр. `select#incomesPerPage` «20»
- **цвет текста вне палитры** (1)
  - `#000000 (ближайший ink-navy #0F172A, ΔE 12.1)` — 768px×1, 1280px×1, 1920px×1 — напр. `select#incomesPerPage` «20»
- **цвет рамки вне палитры** (1)
  - `#767676 (ближайший navy-500 #64748B, ΔE 11.0)` — 768px×4, 1280px×4, 1920px×4 — напр. `select#incomesPerPage` «20»

### Гейт 2. Гардрейлы: 768px FAIL · 1280px FAIL · 1920px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `7: 12, 13.3333, 13.6, 14, 14.4, 16, 22` — 768px×1, 1280px×1, 1920px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 768px×1, 1280px×1, 1920px×1
- **transition: all** (1)
  - `all` — 768px×5, 1280px×5, 1920px×5 — напр. `button#convertSelectedBtn` «Конвертировать выбранное»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 768px×8, 1280px×8, 1920px×8 — напр. `thead > tr > th` «Дата»
- **ошибка в консоли** (4)
  - `Не удалось обновить счётчик заявок на выплату: {stack: "TypeError: Failed to fetch
    at refreshPayoutAttention (http:/` — 768px×2, 1280px×2, 1920px×2
  - `{'column': 35, 'line': 11225, 'text': 'TypeError: Failed to fetch\n    at loadIncomes (http://127.0.0.1:59104/crm:11226:` — 768px×1, 1280px×1, 1920px×1
  - `{stack: "TypeError: Failed to fetch
    at rxLoad (http://1….0.0.1:59104/crm:3772:40)
    at <anonymous>:1:55", message:` — 768px×1, 1280px×1, 1920px×1
  - `Не удалось загрузить курс: {stack: "TypeError: Failed to fetch
    at loadCurrentRate (http://127.0.0.1:59104/crm:3720:3` — 768px×1, 1280px×1, 1920px×1
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 768px×1, 1280px×1, 1920px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 768px×1, 1280px×1, 1920px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px PASS · 1280px PASS · 1920px PASS
находок нет

### Гейт 4. Ширины: 768px FAIL · 1280px PASS · 1920px PASS
- **горизонтальный скролл страницы** (1)
  - `scrollWidth 835 > innerWidth 768` — 768px×1
- **элемент выходит за экран** (2)
  - `right 835 > 768` — 768px×4 — напр. `section#incomes > div.card > table.table`
  - `right 811 > 768` — 768px×1 — напр. `thead > tr > th` «Конвертация»
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `19px` — 768px×1, 1280px×1, 1920px×1 — напр. `select#incomesPerPage` «20
30
50
все»

### Гейт 5. Текст: 768px PASS · 1280px PASS · 1920px PASS
находок нет

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
| 5 | Эмодзи вместо иконок; один размер иконок | partial | PASS* |
| 6 | Цветные полосы слева, синие подсказки, оранжевый вне кнопки | partial | PASS* |
| 7 | Адрес/хеш в одну строку; ничего шире экрана | auto | FAIL |
| 8 | Внутренние названия и коды на экране | partial | PASS* |
| 9 | Плейсхолдер вместо подписи / обрезанный плейсхолдер | partial | PASS* |
| 10 | Ряды «подпись — поле — кнопка» выровнены | partial | PASS* |
| 11 | Контраст WCAG AA | auto | PASS |
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
  - `uppercase` — 375px×8, 768px×8, 1280px×8, 1920px×8 — напр. `thead > tr > th` «Дата»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
