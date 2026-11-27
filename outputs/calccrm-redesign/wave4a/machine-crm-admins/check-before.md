# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=admins`
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
- 375px: элементов 253, контраст проверен у 162, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (10)
  - `padding 6px` — 375px×66 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `gap 6px` — 375px×53 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
  - `padding 10px` — 375px×27 — напр. `div > div > select.form-control` «Админ»
  - `padding 14px` — 375px×19 — напр. `div.container`
  - `padding 2px` — 375px×13 — напр. `div > div > span` «Админ»
  - `margin-вертикаль 14px` — 375px×7 — напр. `section#admins > div.card`
  - `margin-вертикаль 6px` — 375px×5 — напр. `div.form-row > div.form-group > label.form-label` «Имя»
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `padding 36px` — 375px×1 — напр. `select#adminRole` «Админ»
  - `padding 20px` — 375px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
- **шрифт вне токенов** (1)
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#admins > div.card`
- **кегль вне шкалы** (2)
  - `15px` — 375px×19 — напр. `select#adminRole` «Админ»
  - `13px` — 375px×6 — напр. `section#admins > div.card > p` «Каждому свой логин, пароль и роль. Роль решает, какие задачи»
- **вес вне шкалы** (1)
  - `500` — 375px×5 — напр. `div.form-row > div.form-group > label.form-label` «Имя»
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
- **радиус вне шкалы 8/12/999** (1)
  - `10px` — 375px×13 — напр. `div#adminsList > div`

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `6: 12, 13, 14, 15, 16, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×71 — напр. `input#adminName`
- **оранжевый вне главной кнопки и счётчика «на мне»** (1)
  - `текст #C2410C` — 375px×13 — напр. `div > div > span` «Админ»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⚪` — 375px×8 — напр. `div > div > div` «· — · ⚪ Telegram ID не задан»
  - `🟢` — 375px×5 — напр. `div > div > div` «· — · 🟢 Telegram ID задан»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (5)
  - `Telegram ID` — 375px×13 — напр. `div > div > input.form-control` «Telegram ID»
  - `Валера` — 375px×1 — напр. `input#adminName` «Валера»
  - `@username (не обязателен)` — 375px×1 — напр. `input#adminTelegram` «@username (не обязателен)»
  - `valera` — 375px×1 — напр. `input#adminLogin` «valera»
  - … и ещё 1 (полный список в JSON)
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 375px×14 — напр. `select#adminRole` «Админ»
- **контраст ниже 4.5:1** (1)
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 375px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»

### Гейт 4. Ширины: 375px PASS
находок нет

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 256, контраст проверен у 162, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (11)
  - `padding 6px` — 1280px×66 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `gap 6px` — 1280px×53 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
  - `padding 10px` — 1280px×27 — напр. `div > div > select.form-control` «Админ»
  - `padding 14px` — 1280px×18 — напр. `input#adminName`
  - `padding 2px` — 1280px×13 — напр. `div > div > span` «Админ»
  - `margin-вертикаль 14px` — 1280px×6 — напр. `form#addAdminForm > div.form-row > div.form-group`
  - `margin-вертикаль 6px` — 1280px×5 — напр. `div.form-row > div.form-group > label.form-label` «Имя»
  - `padding 20px` — 1280px×2 — напр. `section#admins > div.card`
  - `padding 36px` — 1280px×1 — напр. `select#adminRole` «Админ»
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - … и ещё 1 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 1280px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×1 — напр. `section#admins > div.card`
- **кегль вне шкалы** (2)
  - `15px` — 1280px×19 — напр. `select#adminRole` «Админ»
  - `13px` — 1280px×6 — напр. `section#admins > div.card > p` «Каждому свой логин, пароль и роль. Роль решает, какие задачи»
- **вес вне шкалы** (1)
  - `500` — 1280px×5 — напр. `div.form-row > div.form-group > label.form-label` «Имя»
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»
- **радиус вне шкалы 8/12/999** (1)
  - `10px` — 1280px×13 — напр. `div#adminsList > div`

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `6: 12, 13, 14, 15, 16, 22` — 1280px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×71 — напр. `input#adminName`
- **оранжевый вне главной кнопки и счётчика «на мне»** (1)
  - `текст #C2410C` — 1280px×13 — напр. `div > div > span` «Админ»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- **плейсхолдер не помещается в поле (обрезан)** (1)
  - `@username (не обязателен)` — 1280px×1 — напр. `input#adminTelegram` «@username (не обязателен)»
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⚪` — 1280px×8 — напр. `div > div > div` «· — · ⚪ Telegram ID не задан»
  - `🟢` — 1280px×5 — напр. `div > div > div` «· — · 🟢 Telegram ID задан»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (5)
  - `Telegram ID` — 1280px×13 — напр. `div > div > input.form-control` «Telegram ID»
  - `Валера` — 1280px×1 — напр. `input#adminName` «Валера»
  - `@username (не обязателен)` — 1280px×1 — напр. `input#adminTelegram` «@username (не обязателен)»
  - `valera` — 1280px×1 — напр. `input#adminLogin` «valera»
  - … и ещё 1 (полный список в JSON)
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 1280px×14 — напр. `select#adminRole` «Админ»
- **контраст ниже 4.5:1** (1)
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 1280px×1 — напр. `div.form-row > div.form-group > button.btn.btn-primary` «Добавить»

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
находок нет

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
находок нет

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-admins/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-admins/before-karim-1280.png`
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
| 9 | Плейсхолдер вместо подписи / обрезанный плейсхолдер | partial | FAIL |
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
