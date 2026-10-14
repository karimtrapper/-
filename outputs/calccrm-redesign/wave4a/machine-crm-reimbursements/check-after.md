# design-gate · check — **PASS**

URL: `http://127.0.0.1:59109/crm?section=reimbursements`
DESIGN: `/Users/karimamirov/Desktop/untitled folder/outputs/calccrm-redesign/DESIGN.md`
Ширины: запрошено [375, 768, 1280, 1920], обязательны для PASS [375, 768, 1280, 1920]
Роль: karim

_Вердикт машинный: проверена автоматическая часть гейтов. Вкус, иерархия и пункты «MANUAL» ниже остаются человеку._

| Гейт | Вердикт | 375 | 768 | 1280 | 1920 |
|---|---|---|---|---|---|
| 1. Токены | **PASS** | PASS | PASS | PASS | PASS |
| 2. Гардрейлы | **PASS** | PASS | PASS | PASS | PASS |
| 3. Контраст WCAG AA | **PASS** | PASS | PASS | PASS | PASS |
| 4. Ширины | **PASS** | PASS | PASS | PASS | PASS |
| 5. Текст | **PASS** | PASS | PASS | PASS | PASS |
| 6. Снимки | **PASS** | PASS | PASS | PASS | PASS |

## Телефон (≤700px)
- 375px: элементов 2070, контраст проверен у 1438, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px PASS
находок нет

### Гейт 2. Гардрейлы: 375px PASS
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⏳` — 375px×192 — напр. `div.batch-card > div.batch-amount > div.rate` «⏳»
  - `⚠` — 375px×2 — напр. `div.card > div.form-group > div.reimburse-wallet-warning` «⚠️ TronScan не ответил по 2 кошельк(у/ам) — список переводов»
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

### Гейт 3. Контраст WCAG AA: 375px PASS
находок нет

### Гейт 4. Ширины: 375px PASS
находок нет

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (171)
  - `1820,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#357 Igor Pirogov — $1 820,00»
  - `1200,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#429 Andrey Zaytsev - Grusha — $1 200,00»
  - `155,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#346 Ivan - Grusha — $155,00»
  - `247,00 $ × 4` — 375px×4 — напр. `div.batch-card > div.batch-info > div` «#345 Роман — $247,00»
  - … и ещё 167 (полный список в JSON)

## Компьютер (>700px)
- 768px: элементов 2068, контраст проверен у 1433, главных кнопок 0, адресов 0
- 1280px: элементов 2073, контраст проверен у 1438, главных кнопок 0, адресов 0
- 1920px: элементов 2073, контраст проверен у 1438, главных кнопок 0, адресов 0

### Гейт 1. Токены: 768px PASS · 1280px PASS · 1920px PASS
находок нет

### Гейт 2. Гардрейлы: 768px PASS · 1280px PASS · 1920px PASS
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `⏳` — 768px×192, 1280px×192, 1920px×192 — напр. `div.batch-card > div.batch-amount > div.rate` «⏳»
  - `⚠` — 768px×2, 1280px×2, 1920px×2 — напр. `div.card > div.form-group > div.reimburse-wallet-warning` «⚠️ TronScan не ответил по 2 кошельк(у/ам) — список переводов»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (3)
  - `Сколько USDT перевели` — 768px×2, 1280px×2, 1920px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-amount` «Сколько USDT перевели»
  - `THB/USDT` — 768px×2, 1280px×2, 1920px×2 — напр. `div.form-row > div.form-group > input.form-control.reimburse-rate` «THB/USDT»
  - `TxHash #1` — 768px×2, 1280px×2, 1920px×2 — напр. `div.reimburse-tx-hashes > div > input.form-control.reimburse-tx-hash-input` «TxHash #1»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 768px×1, 1280px×1, 1920px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px PASS · 1280px PASS · 1920px PASS
находок нет

### Гейт 4. Ширины: 768px PASS · 1280px PASS · 1920px PASS
находок нет

### Гейт 5. Текст: 768px PASS · 1280px PASS · 1920px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (171)
  - `1820,00 $ × 4` — 768px×4, 1280px×4, 1920px×4 — напр. `div.batch-card > div.batch-info > div` «#357 Igor Pirogov — $1 820,00»
  - `1200,00 $ × 4` — 768px×4, 1280px×4, 1920px×4 — напр. `div.batch-card > div.batch-info > div` «#429 Andrey Zaytsev - Grusha — $1 200,00»
  - `155,00 $ × 4` — 768px×4, 1280px×4, 1920px×4 — напр. `div.batch-card > div.batch-info > div` «#346 Ivan - Grusha — $155,00»
  - `247,00 $ × 4` — 768px×4, 1280px×4, 1920px×4 — напр. `div.batch-card > div.batch-info > div` «#345 Роман — $247,00»
  - … и ещё 167 (полный список в JSON)

## Гейт 6. Снимки — PASS
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-reimbursements/after-karim-375.png`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-reimbursements/before-karim-375.png`
- 1280px: после `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-reimbursements/after-karim-1280.png`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-reimbursements/before-karim-1280.png`

## Гардрейлы (18)

| № | Запрет | Охват | Вердикт |
|---|---|---|---|
| 1 | Один шрифт + моно, 4 кегля, 3 веса | auto | PASS |
| 2 | Цвета/отступы/радиусы/тени только из токенов | auto | PASS |
| 3 | Сосиски, градиенты, hover-зум, анимации появления | partial | PASS* |
| 4 | Кнопки без глагола, две главные, иконка без подписи | partial | PASS* |
| 5 | Эмодзи вместо иконок; один размер иконок | partial | PASS* |
| 6 | Цветные полосы слева, синие подсказки, оранжевый вне кнопки | partial | PASS* |
| 7 | Адрес/хеш в одну строку; ничего шире экрана | auto | PASS |
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
| 18 | Состояния, анимации transform/opacity, ошибки консоли | partial | PASS* |

`PASS*` — автоматическая часть чистая; остальное смотрит человек.

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
