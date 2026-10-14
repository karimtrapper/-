# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59104/crm`
DESIGN: `/Users/karimamirov/Desktop/untitled folder/outputs/calccrm-redesign/DESIGN.md`
Ширины: запрошено [375, 768, 1280, 1920], обязательны для PASS [375, 768, 1280, 1920]
Роль: karim

_Вердикт машинный: проверена автоматическая часть гейтов. Вкус, иерархия и пункты «MANUAL» ниже остаются человеку._

**Причины вердикта:**
- FAIL в гейтах: 1. Токены, 2. Гардрейлы, 3. Контраст WCAG AA
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

| Гейт | Вердикт | 375 | 768 | 1280 | 1920 |
|---|---|---|---|---|---|
| 1. Токены | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 2. Гардрейлы | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 3. Контраст WCAG AA | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 4. Ширины | **PASS** | PASS | PASS | PASS | PASS |
| 5. Текст | **PASS** | PASS | PASS | PASS | PASS |
| 6. Снимки | **BLOCKED** | PASS | PASS | PASS | PASS |

## Телефон (≤700px)
- 375px: элементов 59, контраст проверен у 33, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (6)
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `padding 14px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×1 — напр. `section#kyc > div.card`
  - `padding 20px` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
  - `gap 6px` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **шрифт вне токенов** (1)
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#kyc > div.card`
- **кегль вне шкалы** (2)
  - `15.2px` — 375px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
  - `14.4px` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **цвет текста вне палитры** (2)
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
  - `#999999 (ближайший navy-400 #94A3B8, ΔE 10.2)` — 375px×2 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `6: 12, 14, 14.4, 15.2, 16, 22` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **ошибка в консоли** (8)
  - `Не удалось обновить счётчик заявок на выплату: {stack: "TypeError: Failed to fetch
    at refreshPayoutAttention (http:/` — 375px×4
  - `Не удалось загрузить курс: {stack: "TypeError: Failed to fetch
    at loadCurrentRate (http://127.0.0.1:59104/crm:3720:3` — 375px×2
  - `{'column': 35, 'line': 11225, 'text': 'TypeError: Failed to fetch\n    at loadIncomes (http://127.0.0.1:59104/crm:11226:` — 375px×1
  - `{'column': 35, 'line': 11452, 'text': 'TypeError: Failed to fetch\n    at loadConversions (http://127.0.0.1:59104/crm:11` — 375px×1
  - `{stack: "TypeError: Failed to fetch
    at rxLoad (http://1….0.0.1:59104/crm:3772:40)
    at <anonymous>:1:55", message:` — 375px×1
  - `Error loading transactions: {stack: "TypeError: Failed to fetch
    at loadTransactions….0.0.1:59104/crm:3764:42)
    at` — 375px×1
  - `Error loading managers: {stack: "TypeError: Failed to fetch
    at loadManagers (ht….0.0.1:59104/crm:3765:38)
    at <an` — 375px×1
  - `Ошибка загрузки KYC: {stack: "TypeError: Failed to fetch
    at loadKYCSection (….0.0.1:59104/crm:3766:33)
    at <anony` — 375px×1
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
- **контраст ниже 4.5:1** (2)
  - `#999999 на #FFFFFF = 2.85:1 (16px/400)` — 375px×2 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»

### Гейт 4. Ширины: 375px PASS
находок нет

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: элементов 57, контраст проверен у 28, главных кнопок 0, адресов 0
- 1280px: элементов 62, контраст проверен у 33, главных кнопок 0, адресов 0
- 1920px: элементов 62, контраст проверен у 33, главных кнопок 0, адресов 0

### Гейт 1. Токены: 768px FAIL · 1280px FAIL · 1920px FAIL
- **отступ вне шкалы 4/8/12/16/24** (6)
  - `padding 20px` — 768px×3, 1280px×2, 1920px×2 — напр. `div.container`
  - `padding 6px` — 768px×1, 1280px×1, 1920px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `gap 6px` — 768px×1, 1280px×1, 1920px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
  - `padding 32px` — 1280px×1, 1920px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1, 1920px×1 — напр. `div.container`
  - `padding 100px` — 768px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 768px×2, 1280px×2, 1920px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 768px×1, 1280px×1, 1920px×1 — напр. `section#kyc > div.card`
- **кегль вне шкалы** (2)
  - `15.2px` — 768px×2, 1280px×2, 1920px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
  - `14.4px` — 768px×1, 1280px×1, 1920px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **фон вне палитры** (1)
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 768px×1, 1280px×1, 1920px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **цвет текста вне палитры** (2)
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
  - `#999999 (ближайший navy-400 #94A3B8, ΔE 10.2)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»

### Гейт 2. Гардрейлы: 768px FAIL · 1280px FAIL · 1920px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `6: 12, 14, 14.4, 15.2, 16, 22` — 768px×1, 1280px×1, 1920px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 768px×1, 1280px×1, 1920px×1
- **transition: all** (1)
  - `all` — 768px×1, 1280px×1, 1920px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **ошибка в консоли** (8)
  - `Не удалось обновить счётчик заявок на выплату: {stack: "TypeError: Failed to fetch
    at refreshPayoutAttention (http:/` — 768px×4, 1280px×5, 1920px×5
  - `Не удалось загрузить курс: {stack: "TypeError: Failed to fetch
    at loadCurrentRate (http://127.0.0.1:59104/crm:3720:3` — 768px×2, 1280px×2, 1920px×2
  - `{'column': 35, 'line': 11225, 'text': 'TypeError: Failed to fetch\n    at loadIncomes (http://127.0.0.1:59104/crm:11226:` — 768px×1, 1280px×1, 1920px×1
  - `{'column': 35, 'line': 11452, 'text': 'TypeError: Failed to fetch\n    at loadConversions (http://127.0.0.1:59104/crm:11` — 768px×1, 1280px×1, 1920px×1
  - `{stack: "TypeError: Failed to fetch
    at rxLoad (http://1….0.0.1:59104/crm:3772:40)
    at <anonymous>:1:55", message:` — 768px×1, 1280px×1, 1920px×1
  - `Error loading transactions: {stack: "TypeError: Failed to fetch
    at loadTransactions….0.0.1:59104/crm:3764:42)
    at` — 768px×1, 1280px×1, 1920px×1
  - `Error loading managers: {stack: "TypeError: Failed to fetch
    at loadManagers (ht….0.0.1:59104/crm:3765:38)
    at <an` — 768px×1, 1280px×1, 1920px×1
  - `Ошибка загрузки KYC: {stack: "TypeError: Failed to fetch
    at loadKYCSection (….0.0.1:59104/crm:3766:33)
    at <anony` — 768px×1, 1280px×1, 1920px×1
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

### Гейт 3. Контраст WCAG AA: 768px FAIL · 1280px FAIL · 1920px FAIL
- **контраст ниже 4.5:1** (2)
  - `#999999 на #FFFFFF = 2.85:1 (16px/400)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»

### Гейт 4. Ширины: 768px PASS · 1280px PASS · 1920px PASS
находок нет

### Гейт 5. Текст: 768px PASS · 1280px PASS · 1920px PASS
находок нет

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-kyc/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-kyc/before-karim-1280.png`
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

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
