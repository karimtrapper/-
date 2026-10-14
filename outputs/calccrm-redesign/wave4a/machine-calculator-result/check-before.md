# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/`
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
- 375px: элементов 218, контраст проверен у 130, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (16)
  - `padding 14px` — 375px×11 — напр. `div#ratesCard`
  - `gap 10px` — 375px×5 — напр. `div.container > header.header > div.logo`
  - `gap 6px` — 375px×5 — напр. `div#ratesCard > div.rates-grid`
  - `padding 10px` — 375px×4 — напр. `div.container > div.scenarios-grid > button.scenario-btn.active`
  - `margin-вертикаль 20px` — 375px×4 — напр. `div.input-section > div.calculator-settings > div.partner-section`
  - `padding 6px` — 375px×2 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `margin-вертикаль 6px` — 375px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `padding 5px` — 375px×2 — напр. `button#srcBitazza` «Bitazza»
  - `padding 40px` — 375px×2 — напр. `input#amount` «100 000»
  - `padding 20px` — 375px×2 — напр. `div#exchangeCard > div.input-section > div.calculator-settings`
  - … и ещё 6 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 375px×3 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **кегль вне шкалы** (9)
  - `13px` — 375px×51 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `11px` — 375px×4 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `9px` — 375px×4 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `15px` — 375px×4 — напр. `div#resultsSection > div.result-main > div.result-rate` «Курс:»
  - `18px` — 375px×3 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `12.8px` — 375px×2 — напр. `div.detail-section.full-table > div.detail-row.detail-hint > span.detail-label` «= базовый курс + 0.00% комиссия»
  - `32px` — 375px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
  - `30px` — 375px×1 — напр. `div#resultValue` «36 578.55 ฿»
  - `20px` — 375px×1 — напр. `div#detailsContent > div.commission-indicator.level-high > span.indicator-icon` «📊»
- **вес вне шкалы** (2)
  - `500` — 375px×23 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `800` — 375px×2 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
- **цвет текста вне палитры** (6)
  - `#6366F1 (ближайший navy-500 #64748B, ΔE 13.2)` — 375px×5 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight` «100 000.00 ₽»
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 375px×4 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight-final` «36 578.55 ฿»
  - `#888888 (ближайший navy-400 #94A3B8, ΔE 12.9)` — 375px×2 — напр. `div.detail-section.full-table > div.detail-row.detail-hint > span.detail-label` «= базовый курс + 0.00% комиссия»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×1 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `#BCBFC4 (ближайший navy-300 #CBD5E1, ΔE 6.3)` — 375px×1 — напр. `div.rates-grid > div.rate-item.highlight > div.rate-label` «Примерный курс»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 375px×1 — напр. `div#resultProfit` «Прибыль: 5.00% (54.53 USDT)»
- **фон вне палитры** (5)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×7 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×2 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `#1B4649 (ближайший navy-700 #334155, ΔE 14.8)` — 375px×1 — напр. `div#resultProfit` «Прибыль: 5.00% (54.53 USDT)»
  - `#4F46E5 (ближайший navy-600 #475569, ΔE 16.1)` — 375px×1 — напр. `button#copyClientBtn` «📋 Копировать»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 375px×1 — напр. `div#detailsContent > div.commission-indicator.level-high`
- **цвет рамки вне палитры** (4)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×8 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×4 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 375px×4 — напр. `div#detailsContent > div.commission-indicator.level-high`
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 375px×4 — напр. `div#detailsContent > div.detail-section.profitability-section`
- **тень вне словаря** (2)
  - `rgba(0, 0, 0, 0.05) 0px 1px 2px 0px` — 375px×3 — напр. `div#ratesCard`
  - `rgba(249, 115, 22, 0.25) 0px 4px 12px 0px` — 375px×3 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»
- **радиус вне шкалы 8/12/999** (1)
  - `16px` — 375px×3 — напр. `div#ratesCard`

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `13: 9, 11, 12, 12.8, 13, 14, 15, 16, 18, 20, 22, 30, 32` — 375px×1
- **весов на экране больше 3** (1)
  - `5: 400, 500, 600, 700, 800` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
- **transition: all** (1)
  - `all` — 375px×19 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **кнопка/чип-«сосиска» (полностью скруглённый кликабельный)** (1)
  - `radius 999px, h 25px` — 375px×2 — напр. `button#srcBitazza` «Bitazza»
- **анимация появления (keyframes)** (2)
  - `fadeIn` — 375px×1 — напр. `div#resultsSection`
  - `slideIn` — 375px×1 — напр. `div#detailsContent > div.commission-indicator.level-high`
- **синий фон (синих плашек нет)** (1)
  - `#4F46E5` — 375px×1 — напр. `button#copyClientBtn` «📋 Копировать»
- **градиент** (1)
  - `linear/radial-gradient` — 375px×2 — напр. `button#createPaymentBtn` «💳 СОЗДАТЬ ПЛАТЕЖ»
- **анимируется не transform/opacity** (1)
  - `background` — 375px×2 — напр. `div#resultsSection > div.details-section > div.details-header`
- **эмодзи в кнопке/ссылке/табе/заголовке** (15)
  - `📋` — 375px×3 — напр. `button#copyClientBtn` «📋 Копировать»
  - `💰` — 375px×2 — напр. `div.scenarios-grid > button.scenario-btn.active > span.scenario-icon` «💰»
  - `💱` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `🏠` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «🏠 Фрихолд»
  - `📜` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «📜 Лизхолд»
  - `✏` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «✏️ Другое»
  - `🏦` — 375px×1 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `💼` — 375px×1 — напр. `div#methodSwitcher > button.method-btn` «💼 Брокер»
  - `🎨` — 375px×1 — напр. `div#methodSwitcher > button.method-btn` «🎨 Кастом»
  - `💸` — 375px×1 — напр. `div.scenarios-grid > button.scenario-btn > span.scenario-icon` «💸»
  - … и ещё 5 (полный список в JSON)
- **плейсхолдер не помещается в поле (обрезан)** (1)
  - `Имя клиента, номер заказа и т.д.` — 375px×1 — напр. `input#paymentComment` «Имя клиента, номер заказа и т.д.»
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (6)
  - `📊` — 375px×4 — напр. `div#ratesCard > div.rates-header > span.rates-title` «📊 Актуальные курсы»
  - `🧮` — 375px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
  - `↔↔` — 375px×1 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `🎁` — 375px×1 — напр. `div.discount-header > label.checkbox-label > span.checkbox-text` «🎁 Сделать скидку (изменить прибыль)»
  - … и ещё 2 (полный список в JSON)
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Имя клиента, номер заказа и т.д.` — 375px×1 — напр. `input#paymentComment` «Имя клиента, номер заказа и т.д.»
- (warn) **outline:none — проверь кольцо фокуса** (1)
  - `.amount-input` — 375px×1 — напр. `.amount-input`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (14)
  - `#6366F1 на #F8FAFC = 4.27:1 (13px/600)` — 375px×4 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight` «100 000.00 ₽»
  - `#94A3B8 на #F8FAFC = 2.45:1 (11px/600)` — 375px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `#94A3B8 на #F8FAFC = 2.45:1 (9px/500)` — 375px×2 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 375px×2 — напр. `div#ratesUpdated` «Обновлено:»
  - `#888888 на #F8FAFC = 3.39:1 (12.8px/500)` — 375px×2 — напр. `div.detail-section.full-table > div.detail-row.detail-hint > span.detail-label` «= базовый курс + 0.00% комиссия»
  - `#16A34A на #F8FAFC = 3.15:1 (14px/700)` — 375px×2 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight-final` «36 578.55 ฿»
  - `#FFFFFF на #F97316 = 2.80:1 (13px/600)` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `#64748B на #F1F5F9 = 4.34:1 (12px/600)` — 375px×1 — напр. `button#srcBinance` «Binance»
  - `#94A3B8 на #F8FAFC = 2.45:1 (9px/400)` — 375px×1 — напр. `div#usdtThbSub` «VWAP 33.61 · −0.15% · −20฿/сделку»
  - `#94A3B8 на #FFFFFF = 2.56:1 (18px/600)` — 375px×1 — напр. `span#inputCurrency` «₽»
  - … и ещё 4 (полный список в JSON)
- **контраст ниже 3:1** (1)
  - `#FFFFFF на #F97316 = 2.80:1 (16px/700)` — 375px×1 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#FFFFFF` — 375px×2 — напр. `button#createPaymentBtn` «💳 СОЗДАТЬ ПЛАТЕЖ»

### Гейт 4. Ширины: 375px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `25px` — 375px×2 — напр. `button#srcBitazza` «Bitazza»
  - `36px` — 375px×1 — напр. `button#refreshBtn` «↻
Обновить»
  - `33px` — 375px×1 — напр. `button#copyClientBtn` «📋 Копировать»

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `87,3300 ₽ × 3` — 375px×3 — напр. `div#rubUsdtRate` «87.3300 ₽»
  - `36578,55 ฿ × 3` — 375px×3 — напр. `div#resultValue` «36 578.55 ฿»
  - `54,53 USDT × 2` — 375px×2 — напр. `div#resultProfit` «Прибыль: 5.00% (54.53 USDT)»
  - `1145,08 USDT × 2` — 375px×2 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight` «1 145.08 USDT»

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 221, контраст проверен у 130, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (17)
  - `padding 14px` — 1280px×13 — напр. `div#ratesCard`
  - `padding 10px` — 1280px×7 — напр. `div#ratesCard > div.rates-grid > div.rate-item`
  - `gap 10px` — 1280px×5 — напр. `div.container > header.header > div.logo`
  - `gap 6px` — 1280px×4 — напр. `div.container > div.scenarios-grid`
  - `margin-вертикаль 20px` — 1280px×4 — напр. `div.input-section > div.calculator-settings > div.partner-section`
  - `padding 6px` — 1280px×2 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `margin-вертикаль 6px` — 1280px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `padding 5px` — 1280px×2 — напр. `button#srcBitazza` «Bitazza»
  - `padding 20px` — 1280px×2 — напр. `div#exchangeCard > div.input-section > div.calculator-settings`
  - `padding 48px` — 1280px×2 — напр. `input#amount` «100 000»
  - … и ещё 7 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 1280px×3 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **кегль вне шкалы** (9)
  - `13px` — 1280px×47 — напр. `div.scenarios-grid > button.scenario-btn.active > div.scenario-title` «RUB → THB»
  - `15px` — 1280px×7 — напр. `div#usdtThbRate` «33.56 ฿»
  - `11px` — 1280px×4 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `20px` — 1280px×4 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `10px` — 1280px×3 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `12.8px` — 1280px×2 — напр. `div.detail-section.full-table > div.detail-row.detail-hint > span.detail-label` «= базовый курс + 0.00% комиссия»
  - `32px` — 1280px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
  - `9px` — 1280px×1 — напр. `div#usdtThbSub` «VWAP 33.61 · −0.15% · −20฿/сделку»
  - `36px` — 1280px×1 — напр. `div#resultValue` «36 578.55 ฿»
- **вес вне шкалы** (2)
  - `500` — 1280px×23 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `800` — 1280px×2 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
- **цвет текста вне палитры** (6)
  - `#6366F1 (ближайший navy-500 #64748B, ΔE 13.2)` — 1280px×5 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight` «100 000.00 ₽»
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 1280px×4 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight-final` «36 578.55 ฿»
  - `#888888 (ближайший navy-400 #94A3B8, ΔE 12.9)` — 1280px×2 — напр. `div.detail-section.full-table > div.detail-row.detail-hint > span.detail-label` «= базовый курс + 0.00% комиссия»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 1280px×1 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `#BCBFC4 (ближайший navy-300 #CBD5E1, ΔE 6.3)` — 1280px×1 — напр. `div.rates-grid > div.rate-item.highlight > div.rate-label` «Примерный курс»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 1280px×1 — напр. `div#resultProfit` «Прибыль: 5.00% (54.53 USDT)»
- **фон вне палитры** (5)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 1280px×7 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×2 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `#1B4649 (ближайший navy-700 #334155, ΔE 14.8)` — 1280px×1 — напр. `div#resultProfit` «Прибыль: 5.00% (54.53 USDT)»
  - `#4F46E5 (ближайший navy-600 #475569, ΔE 16.1)` — 1280px×1 — напр. `button#copyClientBtn` «📋 Копировать»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 1280px×1 — напр. `div#detailsContent > div.commission-indicator.level-high`
- **цвет рамки вне палитры** (4)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 1280px×8 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×4 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 1280px×4 — напр. `div#detailsContent > div.commission-indicator.level-high`
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 1280px×4 — напр. `div#detailsContent > div.detail-section.profitability-section`
- **тень вне словаря** (2)
  - `rgba(0, 0, 0, 0.05) 0px 1px 2px 0px` — 1280px×3 — напр. `div#ratesCard`
  - `rgba(249, 115, 22, 0.25) 0px 4px 12px 0px` — 1280px×3 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»
- **радиус вне шкалы 8/12/999** (1)
  - `16px` — 1280px×3 — напр. `div#ratesCard`

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **весов на экране больше 3** (1)
  - `5: 400, 500, 600, 700, 800` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 1280px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
- **transition: all** (1)
  - `all` — 1280px×19 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **кнопка/чип-«сосиска» (полностью скруглённый кликабельный)** (1)
  - `radius 999px, h 25px` — 1280px×2 — напр. `button#srcBitazza` «Bitazza»
- **анимация появления (keyframes)** (2)
  - `fadeIn` — 1280px×1 — напр. `div#resultsSection`
  - `slideIn` — 1280px×1 — напр. `div#detailsContent > div.commission-indicator.level-high`
- **синий фон (синих плашек нет)** (1)
  - `#4F46E5` — 1280px×1 — напр. `button#copyClientBtn` «📋 Копировать»
- **градиент** (1)
  - `linear/radial-gradient` — 1280px×2 — напр. `button#createPaymentBtn` «💳 СОЗДАТЬ ПЛАТЕЖ»
- **анимируется не transform/opacity** (1)
  - `background` — 1280px×2 — напр. `div#resultsSection > div.details-section > div.details-header`
- **эмодзи в кнопке/ссылке/табе/заголовке** (15)
  - `📋` — 1280px×3 — напр. `button#copyClientBtn` «📋 Копировать»
  - `💰` — 1280px×2 — напр. `div.scenarios-grid > button.scenario-btn.active > span.scenario-icon` «💰»
  - `💱` — 1280px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `🏠` — 1280px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «🏠 Фрихолд»
  - `📜` — 1280px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «📜 Лизхолд»
  - `✏` — 1280px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «✏️ Другое»
  - `🏦` — 1280px×1 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `💼` — 1280px×1 — напр. `div#methodSwitcher > button.method-btn` «💼 Брокер»
  - `🎨` — 1280px×1 — напр. `div#methodSwitcher > button.method-btn` «🎨 Кастом»
  - `💸` — 1280px×1 — напр. `div.scenarios-grid > button.scenario-btn > span.scenario-icon` «💸»
  - … и ещё 5 (полный список в JSON)
- **кеглей на экране больше 4** (1)
  - `13: 9, 10, 11, 12, 12.8, 13, 14, 15, 16, 20, 22, 32, 36` — 1280px×1
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (6)
  - `📊` — 1280px×4 — напр. `div#ratesCard > div.rates-header > span.rates-title` «📊 Актуальные курсы»
  - `🧮` — 1280px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
  - `↔↔` — 1280px×1 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `🎁` — 1280px×1 — напр. `div.discount-header > label.checkbox-label > span.checkbox-text` «🎁 Сделать скидку (изменить прибыль)»
  - … и ещё 2 (полный список в JSON)
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (1)
  - `Имя клиента, номер заказа и т.д.` — 1280px×1 — напр. `input#paymentComment` «Имя клиента, номер заказа и т.д.»
- (warn) **outline:none — проверь кольцо фокуса** (1)
  - `.amount-input` — 1280px×1 — напр. `.amount-input`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **контраст ниже 4.5:1** (14)
  - `#6366F1 на #F8FAFC = 4.27:1 (13px/600)` — 1280px×4 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight` «100 000.00 ₽»
  - `#94A3B8 на #F8FAFC = 2.45:1 (11px/600)` — 1280px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 1280px×2 — напр. `div#ratesUpdated` «Обновлено:»
  - `#888888 на #F8FAFC = 3.39:1 (12.8px/500)` — 1280px×2 — напр. `div.detail-section.full-table > div.detail-row.detail-hint > span.detail-label` «= базовый курс + 0.00% комиссия»
  - `#16A34A на #F8FAFC = 3.15:1 (14px/700)` — 1280px×2 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight-final` «36 578.55 ฿»
  - `#94A3B8 на #F8FAFC = 2.45:1 (10px/500)` — 1280px×2 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `#64748B на #F1F5F9 = 4.34:1 (12px/600)` — 1280px×1 — напр. `button#srcBinance` «Binance»
  - `#94A3B8 на #F8FAFC = 2.45:1 (9px/400)` — 1280px×1 — напр. `div#usdtThbSub` «VWAP 33.61 · −0.15% · −20฿/сделку»
  - `#10B981 на #1B4649 = 4.10:1 (14px/600)` — 1280px×1 — напр. `div#resultProfit` «Прибыль: 5.00% (54.53 USDT)»
  - `#16A34A на #F0FDF4 = 3.15:1 (13px/700)` — 1280px×1 — напр. `div#detailsContent > div.detail-section.profitability-section > h4` «💰 Прибыльность»
  - … и ещё 4 (полный список в JSON)
- **контраст ниже 3:1** (1)
  - `#FFFFFF на #F97316 = 2.80:1 (16px/700)` — 1280px×1 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#FFFFFF` — 1280px×2 — напр. `button#createPaymentBtn` «💳 СОЗДАТЬ ПЛАТЕЖ»

### Гейт 4. Ширины: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `25px` — 1280px×2 — напр. `button#srcBitazza` «Bitazza»
  - `36px` — 1280px×1 — напр. `button#refreshBtn` «↻
Обновить»
  - `33px` — 1280px×1 — напр. `button#copyClientBtn` «📋 Копировать»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `87,3300 ₽ × 3` — 1280px×3 — напр. `div#rubUsdtRate` «87.3300 ₽»
  - `36578,55 ฿ × 3` — 1280px×3 — напр. `div#resultValue` «36 578.55 ฿»
  - `54,53 USDT × 2` — 1280px×2 — напр. `div#resultProfit` «Прибыль: 5.00% (54.53 USDT)»
  - `1145,08 USDT × 2` — 1280px×2 — напр. `div.detail-section.full-table > div.detail-row > span.detail-value.highlight` «1 145.08 USDT»

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-calculator-result/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-calculator-result/before-karim-1280.png`
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

## Дополнительно (Don't из DESIGN.md)
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×2, 1280px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
