# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=exchangers`
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
| 4. Ширины | **FAIL** | PASS | BLOCKED | FAIL | BLOCKED |
| 5. Текст | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |
| 6. Снимки | **BLOCKED** | PASS | BLOCKED | PASS | BLOCKED |

## Телефон (≤700px)
- 375px: элементов 3309, контраст проверен у 2302, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (8)
  - `padding 10px` — 375px×238 — напр. `select#rxFltMer` «Все мерчанты»
  - `padding 3px` — 375px×224 — напр. `tr > td > span.rx-pill` «✅ Закрыто»
  - `padding 14px` — 375px×13 — напр. `div.container`
  - `margin-вертикаль 2px` — 375px×4 — напр. `div#rxSummary > div.rx-card > div.sub` «224 сделок»
  - `margin-вертикаль 14px` — 375px×2 — напр. `section#exchangers > div.rx-subtabs`
  - `gap 6px` — 375px×2 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 375px×10 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×5 — напр. `div#rxSummary > div.rx-card`
- **кегль вне шкалы** (3)
  - `11px` — 375px×229 — напр. `div#rxSummary > div.rx-card > div.sub` «224 сделок»
  - `13px` — 375px×5 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
  - `20px` — 375px×4 — напр. `div#rxSummary > div.rx-card > div.val.num` «836 255,61»
- **вес вне шкалы** (1)
  - `800` — 375px×4 — напр. `div#rxSummary > div.rx-card > div.val.num` «836 255,61»
- **цвет текста вне палитры** (3)
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 375px×226 — напр. `div#rxSummary > div.rx-card > div.val` «8»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 375px×1 — напр. `div#rxSummary > div.rx-card > div.val.num` «607 599,11»
  - `#0000EE (ближайший navy-700 #334155, ΔE 19.3)` — 375px×1 — напр. `tr > td > a.num` «✅ CNV-0001»
- **фон вне палитры** (2)
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 375px×139 — напр. `tr > td > span.rx-pill` «✅ Закрыто»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×1 — напр. `section#exchangers > div.rx-subtabs > button.rx-subtab.active` «Поступления»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `7: 11, 12, 13, 14, 16, 20, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 700, 800` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×2 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×9 — напр. `thead > tr > th` «WL»
- **эмодзи в кнопке/ссылке/табе/заголовке** (2)
  - `✅` — 375px×129 — напр. `tr > td > a.num` «✅ CNV-0001»
  - `🔄` — 375px×1 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (3)
  - `💰` — 375px×81 — напр. `tr > td > span.rx-pill` «💰 Оплачено»
  - `📥` — 375px×11 — напр. `tr > td > span.rx-pill` «📥 Обеспечено»
  - `⚠` — 375px×4 — напр. `tr > td > span.rx-pill` «⚠️ Аванс»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (2)
  - `USDT от` — 375px×1 — напр. `input#rxFltSf` «USDT от»
  - `USDT до` — 375px×1 — напр. `input#rxFltSt` «USDT до»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (2)
  - `#16A34A на #FFFFFF = 3.30:1 (14px/400)` — 375px×224 — напр. `tr > td.num > span` «$ 25,11»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 375px×4 — напр. `div#rxSummary > div.rx-card > div.sub` «224 сделок»
- **контраст ниже 3:1** (1)
  - `#F59E0B на #FFFFFF = 2.15:1 (20px/800)` — 375px×1 — напр. `div#rxSummary > div.rx-card > div.val.num` «607 599,11»

### Гейт 4. Ширины: 375px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (5)
  - `32px` — 375px×5 — напр. `section#exchangers > div.rx-subtabs > button.rx-subtab.active` «Поступления»
  - `35px` — 375px×3 — напр. `select#rxFltMer` «Все мерчанты
1000
FiatEX
Four exchange
RUBLEV
grusha
Михаил »
  - `33px` — 375px×2 — напр. `input#rxFltSf`
  - `37px` — 375px×1 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
  - … и ещё 1 (полный список в JSON)

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (11)
  - `0,00 $ × 7` — 375px×7 — напр. `tr > td.num > span` «$ 0,00»
  - `241,71 $ × 3` — 375px×3 — напр. `tr > td.num > span` «$ 241,71»
  - `679,81 $ × 3` — 375px×3 — напр. `tbody#rx-deals-body > tr > td.num` «$ 679,81»
  - `241,89 $ × 2` — 375px×2 — напр. `tr > td.num > span` «$ 241,89»
  - … и ещё 7 (полный список в JSON)

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 3312, контраст проверен у 2302, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (9)
  - `padding 10px` — 1280px×238 — напр. `select#rxFltMer` «Все мерчанты»
  - `padding 3px` — 1280px×224 — напр. `tr > td > span.rx-pill` «✅ Закрыто»
  - `padding 14px` — 1280px×12 — напр. `div#rxSummary > div.rx-card`
  - `margin-вертикаль 2px` — 1280px×4 — напр. `div#rxSummary > div.rx-card > div.sub` «224 сделок»
  - `gap 6px` — 1280px×2 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
  - `padding 6px` — 1280px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `margin-вертикаль 14px` — 1280px×1 — напр. `section#exchangers > div.rx-subtabs`
  - `padding 32px` — 1280px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 1280px×10 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×5 — напр. `div#rxSummary > div.rx-card`
- **кегль вне шкалы** (3)
  - `11px` — 1280px×229 — напр. `div#rxSummary > div.rx-card > div.sub` «224 сделок»
  - `13px` — 1280px×5 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
  - `20px` — 1280px×4 — напр. `div#rxSummary > div.rx-card > div.val.num` «836 255,61»
- **вес вне шкалы** (1)
  - `800` — 1280px×4 — напр. `div#rxSummary > div.rx-card > div.val.num` «836 255,61»
- **цвет текста вне палитры** (3)
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 1280px×226 — напр. `div#rxSummary > div.rx-card > div.val` «8»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 1280px×1 — напр. `div#rxSummary > div.rx-card > div.val.num` «607 599,11»
  - `#0000EE (ближайший navy-700 #334155, ΔE 19.3)` — 1280px×1 — напр. `tr > td > a.num` «✅ CNV-0001»
- **фон вне палитры** (2)
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 1280px×139 — напр. `tr > td > span.rx-pill` «✅ Закрыто»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 1280px×1 — напр. `section#exchangers > div.rx-subtabs > button.rx-subtab.active` «Поступления»

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `7: 11, 12, 13, 14, 16, 20, 22` — 1280px×1
- **весов на экране больше 3** (1)
  - `4: 400, 600, 700, 800` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×2 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 1280px×9 — напр. `thead > tr > th` «WL»
- **эмодзи в кнопке/ссылке/табе/заголовке** (2)
  - `✅` — 1280px×129 — напр. `tr > td > a.num` «✅ CNV-0001»
  - `🔄` — 1280px×1 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (3)
  - `💰` — 1280px×81 — напр. `tr > td > span.rx-pill` «💰 Оплачено»
  - `📥` — 1280px×11 — напр. `tr > td > span.rx-pill` «📥 Обеспечено»
  - `⚠` — 1280px×4 — напр. `tr > td > span.rx-pill` «⚠️ Аванс»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (2)
  - `USDT от` — 1280px×1 — напр. `input#rxFltSf` «USDT от»
  - `USDT до` — 1280px×1 — напр. `input#rxFltSt` «USDT до»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (2)
  - `#16A34A на #FFFFFF = 3.30:1 (14px/400)` — 1280px×224 — напр. `tr > td.num > span` «$ 25,11»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 1280px×4 — напр. `div#rxSummary > div.rx-card > div.sub` «224 сделок»
- **контраст ниже 3:1** (1)
  - `#F59E0B на #FFFFFF = 2.15:1 (20px/800)` — 1280px×1 — напр. `div#rxSummary > div.rx-card > div.val.num` «607 599,11»

### Гейт 4. Ширины: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **в ряду поля/кнопки разной высоты или смещены** (2)
  - `32px и 37px (Δверха 2px)` — 1280px×5 — напр. `section#exchangers > div.rx-subtabs > button.rx-subtab.active` «Поступления»
  - `33px и 36px (Δверха 1px)` — 1280px×2 — напр. `input#rxFltSf`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (5)
  - `32px` — 1280px×5 — напр. `section#exchangers > div.rx-subtabs > button.rx-subtab.active` «Поступления»
  - `35px` — 1280px×3 — напр. `select#rxFltMer` «Все мерчанты
1000
FiatEX
Four exchange
RUBLEV
grusha
Михаил »
  - `33px` — 1280px×2 — напр. `input#rxFltSf`
  - `37px` — 1280px×1 — напр. `button#rxSyncBtn` «🔄 Обновить из бота»
  - … и ещё 1 (полный список в JSON)

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (11)
  - `0,00 $ × 7` — 1280px×7 — напр. `tr > td.num > span` «$ 0,00»
  - `241,71 $ × 3` — 1280px×3 — напр. `tr > td.num > span` «$ 241,71»
  - `679,81 $ × 3` — 1280px×3 — напр. `tbody#rx-deals-body > tr > td.num` «$ 679,81»
  - `241,89 $ × 2` — 1280px×2 — напр. `tr > td.num > span` «$ 241,89»
  - … и ещё 7 (полный список в JSON)

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-exchangers/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-exchangers/before-karim-1280.png`
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

## Дополнительно (Don't из DESIGN.md)
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×9, 1280px×9 — напр. `thead > tr > th` «WL»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
