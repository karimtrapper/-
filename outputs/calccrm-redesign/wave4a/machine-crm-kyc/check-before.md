# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=kyc`
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
- 375px: элементов 114, контраст проверен у 67, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (9)
  - `gap 6px` — 375px×8 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
  - `margin-вертикаль 2px` — 375px×7 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
  - `gap 10px` — 375px×7 — напр. `div#kycVerifiedList > div > div`
  - `padding 5px` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Документы»
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `padding 14px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 14px` — 375px×1 — напр. `section#kyc > div.card`
  - `padding 20px` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **шрифт вне токенов** (1)
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#kyc > div.card`
- **кегль вне шкалы** (4)
  - `12.48px` — 375px×14 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
  - `12.8px` — 375px×7 — напр. `div > div > span` «18.09.2026»
  - `15.2px` — 375px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
  - `14.4px` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **фон вне палитры** (2)
  - `#DCFCE7 (ближайший money-surface #F0FDF4, ΔE 7.7)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Документы»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **цвет текста вне палитры** (5)
  - `#999999 (ближайший navy-400 #94A3B8, ΔE 10.2)` — 375px×8 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 375px×7 — напр. `div > div > span` «✓»
  - `#4D7C0F (ближайший money-ink #065F46, ΔE 20.9)` — 375px×7 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
  - `#15803D (ближайший money-ink #065F46, ΔE 14.5)` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Документы»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
- **цвет рамки вне палитры** (2)
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 375px×28 — напр. `div#kycVerifiedList > div`
  - `#86EFAC (ближайший money-border #BBF7D0, ΔE 8.4)` — 375px×28 — напр. `div > div > button.btn.btn-sm` «Документы»
- **радиус вне шкалы 8/12/999** (1)
  - `6px` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Документы»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `8: 12, 12.48, 12.8, 14, 14.4, 15.2, 16, 22` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×8 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (1)
  - `📄🤳🎥🎬` — 375px×3 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
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
  - `#16A34A на #F0FDF4 = 3.15:1 (16px/400)` — 375px×7 — напр. `div > div > span` «✓»
  - `#999999 на #F0FDF4 = 2.72:1 (12.8px/400)` — 375px×7 — напр. `div > div > span` «18.09.2026»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 375px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
  - `#999999 на #FFFFFF = 2.85:1 (16px/400)` — 375px×1 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»

### Гейт 4. Ширины: 375px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `36px` — 375px×7 — напр. `div > div > button.btn.btn-sm` «Документы»

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 117, контраст проверен у 67, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (8)
  - `gap 6px` — 1280px×8 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
  - `margin-вертикаль 2px` — 1280px×7 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
  - `gap 10px` — 1280px×7 — напр. `div#kycVerifiedList > div > div`
  - `padding 5px` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Документы»
  - `padding 20px` — 1280px×2 — напр. `section#kyc > div.card`
  - `padding 6px` — 1280px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 1280px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×1 — напр. `section#kyc > div.card`
- **кегль вне шкалы** (4)
  - `12.48px` — 1280px×14 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
  - `12.8px` — 1280px×7 — напр. `div > div > span` «18.09.2026»
  - `15.2px` — 1280px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
  - `14.4px` — 1280px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **фон вне палитры** (2)
  - `#DCFCE7 (ближайший money-surface #F0FDF4, ΔE 7.7)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Документы»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **цвет текста вне палитры** (5)
  - `#999999 (ближайший navy-400 #94A3B8, ΔE 10.2)` — 1280px×8 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 1280px×7 — напр. `div > div > span` «✓»
  - `#4D7C0F (ближайший money-ink #065F46, ΔE 20.9)` — 1280px×7 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
  - `#15803D (ближайший money-ink #065F46, ΔE 14.5)` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Документы»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 1280px×2 — напр. `div#kycPendingSection > h4` «Ожидают проверки»
- **цвет рамки вне палитры** (2)
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 1280px×28 — напр. `div#kycVerifiedList > div`
  - `#86EFAC (ближайший money-border #BBF7D0, ΔE 8.4)` — 1280px×28 — напр. `div > div > button.btn.btn-sm` «Документы»
- **радиус вне шкалы 8/12/999** (1)
  - `6px` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Документы»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `8: 12, 12.48, 12.8, 14, 14.4, 15.2, 16, 22` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×8 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (1)
  - `📄🤳🎥🎬` — 1280px×3 — напр. `div > div > div` «📄🤳🎥🎬 документы сохранены»
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
  - `#16A34A на #F0FDF4 = 3.15:1 (16px/400)` — 1280px×7 — напр. `div > div > span` «✓»
  - `#999999 на #F0FDF4 = 2.72:1 (12.8px/400)` — 1280px×7 — напр. `div > div > span` «18.09.2026»
  - `#FFFFFF на #F97316 = 2.80:1 (14.4px/600)` — 1280px×1 — напр. `div.card > div.card-title > button.btn.btn-primary` «+ Запросить KYC»
  - `#999999 на #FFFFFF = 2.85:1 (16px/400)` — 1280px×1 — напр. `div#kycPendingList > div` «Нет ожидающих проверок»

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (1)
  - `36px` — 1280px×7 — напр. `div > div > button.btn.btn-sm` «Документы»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
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
