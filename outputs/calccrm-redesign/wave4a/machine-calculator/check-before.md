# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59104/`
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
- 375px: элементов 121, контраст проверен у 71, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (14)
  - `padding 14px` — 375px×6 — напр. `div#ratesCard`
  - `padding 10px` — 375px×4 — напр. `div.container > div.scenarios-grid > button.scenario-btn.active`
  - `gap 10px` — 375px×3 — напр. `div.container > header.header > div.logo`
  - `margin-вертикаль 6px` — 375px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `padding 5px` — 375px×2 — напр. `button#srcBitazza` «Bitazza»
  - `gap 6px` — 375px×2 — напр. `div#ratesCard > div.rates-grid`
  - `padding 6px` — 375px×1 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 3px` — 375px×1 — напр. `div#rateSourceToggle`
  - `gap 2px` — 375px×1 — напр. `div#rateSourceToggle`
  - `margin-вертикаль 3px` — 375px×1 — напр. `div#usdtThbSub` «VWAP 33.65 · −0.15% · −20฿/сделку»
  - … и ещё 4 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 375px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **кегль вне шкалы** (5)
  - `13px` — 375px×10 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `11px` — 375px×4 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `9px` — 375px×4 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `18px` — 375px×2 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `32px` — 375px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
- **вес вне шкалы** (2)
  - `500` — 375px×6 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `800` — 375px×1 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
- **цвет текста вне палитры** (2)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×1 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `#BCBFC4 (ближайший navy-300 #CBD5E1, ΔE 6.3)` — 375px×1 — напр. `div.rates-grid > div.rate-item.highlight > div.rate-label` «Примерный курс»
- **фон вне палитры** (2)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×5 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×2 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **цвет рамки вне палитры** (2)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×8 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×4 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **тень вне словаря** (2)
  - `rgba(0, 0, 0, 0.05) 0px 1px 2px 0px` — 375px×3 — напр. `div#ratesCard`
  - `rgba(249, 115, 22, 0.25) 0px 4px 12px 0px` — 375px×1 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»
- **радиус вне шкалы 8/12/999** (1)
  - `16px` — 375px×3 — напр. `div#ratesCard`

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `9: 9, 11, 12, 13, 14, 16, 18, 22, 32` — 375px×1
- **весов на экране больше 3** (1)
  - `5: 400, 500, 600, 700, 800` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
- **transition: all** (1)
  - `all` — 375px×16 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **кнопка/чип-«сосиска» (полностью скруглённый кликабельный)** (1)
  - `radius 999px, h 25px` — 375px×2 — напр. `button#srcBitazza` «Bitazza»
- **анимируется не transform/opacity** (1)
  - `background` — 375px×1 — напр. `div#exchangeCard > div.info-card > div.info-header`
- **эмодзи в кнопке/ссылке/табе/заголовке** (13)
  - `💱` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `🏠` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «🏠 Фрихолд»
  - `📜` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «📜 Лизхолд»
  - `✏` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «✏️ Другое»
  - `🏦` — 375px×1 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `💼` — 375px×1 — напр. `div#methodSwitcher > button.method-btn` «💼 Брокер»
  - `🎨` — 375px×1 — напр. `div#methodSwitcher > button.method-btn` «🎨 Кастом»
  - `💰` — 375px×1 — напр. `div.scenarios-grid > button.scenario-btn.active > span.scenario-icon` «💰»
  - `💸` — 375px×1 — напр. `div.scenarios-grid > button.scenario-btn > span.scenario-icon` «💸»
  - `💵` — 375px×1 — напр. `div.scenarios-grid > button.scenario-btn > span.scenario-icon` «💵»
  - … и ещё 3 (полный список в JSON)
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (5)
  - `🧮` — 375px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
  - `↔↔` — 375px×1 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `📊` — 375px×1 — напр. `div#ratesCard > div.rates-header > span.rates-title` «📊 Актуальные курсы»
  - `🎁` — 375px×1 — напр. `div.discount-header > label.checkbox-label > span.checkbox-text` «🎁 Сделать скидку (изменить прибыль)»
  - … и ещё 1 (полный список в JSON)
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (1)
  - `.amount-input` — 375px×1 — напр. `.amount-input`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (7)
  - `#94A3B8 на #F8FAFC = 2.45:1 (11px/600)` — 375px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `#94A3B8 на #F8FAFC = 2.45:1 (9px/500)` — 375px×2 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 375px×2 — напр. `div#ratesUpdated` «Обновлено:»
  - `#FFFFFF на #F97316 = 2.80:1 (13px/600)` — 375px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `#64748B на #F1F5F9 = 4.34:1 (12px/600)` — 375px×1 — напр. `button#srcBinance` «Binance»
  - `#94A3B8 на #F8FAFC = 2.45:1 (9px/400)` — 375px×1 — напр. `div#usdtThbSub` «VWAP 33.65 · −0.15% · −20฿/сделку»
  - `#94A3B8 на #FFFFFF = 2.56:1 (18px/600)` — 375px×1 — напр. `span#inputCurrency` «₽»
- **контраст ниже 3:1** (1)
  - `#FFFFFF на #F97316 = 2.80:1 (16px/700)` — 375px×1 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»

### Гейт 4. Ширины: 375px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `25px` — 375px×2 — напр. `button#srcBitazza` «Bitazza»
  - `36px` — 375px×1 — напр. `button#refreshBtn` «↻
Обновить»

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: элементов 119, контраст проверен у 66, главных кнопок 0, адресов 0
- 1280px: элементов 124, контраст проверен у 71, главных кнопок 0, адресов 0
- 1920px: элементов 124, контраст проверен у 71, главных кнопок 0, адресов 0

### Гейт 1. Токены: 768px FAIL · 1280px FAIL · 1920px FAIL
- **отступ вне шкалы 4/8/12/16/24** (15)
  - `padding 14px` — 768px×7, 1280px×7, 1920px×7 — напр. `div#ratesCard`
  - `padding 10px` — 768px×7, 1280px×7, 1920px×7 — напр. `div#ratesCard > div.rates-grid > div.rate-item`
  - `gap 10px` — 768px×3, 1280px×3, 1920px×3 — напр. `div.container > header.header > div.logo`
  - `margin-вертикаль 6px` — 768px×2, 1280px×2, 1920px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `padding 5px` — 768px×2, 1280px×2, 1920px×2 — напр. `button#srcBitazza` «Bitazza»
  - `padding 6px` — 768px×1, 1280px×1, 1920px×1 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 3px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#rateSourceToggle`
  - `gap 2px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#rateSourceToggle`
  - `gap 6px` — 768px×1, 1280px×1, 1920px×1 — напр. `div.container > div.scenarios-grid`
  - `margin-вертикаль 3px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#usdtThbSub` «VWAP 33.65 · −0.15% · −20฿/сделку»
  - … и ещё 5 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 768px×2, 1280px×2, 1920px×2 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **кегль вне шкалы** (7)
  - `13px` — 768px×6, 1280px×6, 1920px×6 — напр. `div.scenarios-grid > button.scenario-btn.active > div.scenario-title` «RUB → THB»
  - `11px` — 768px×4, 1280px×4, 1920px×4 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `10px` — 768px×3, 1280px×3, 1920px×3 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `15px` — 768px×3, 1280px×3, 1920px×3 — напр. `div#usdtThbRate` «33.60 ฿»
  - `20px` — 768px×2, 1280px×2, 1920px×2 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `32px` — 768px×1, 1280px×1, 1920px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
  - `9px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#usdtThbSub` «VWAP 33.65 · −0.15% · −20฿/сделку»
- **вес вне шкалы** (2)
  - `500` — 768px×6, 1280px×6, 1920px×6 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `800` — 768px×1, 1280px×1, 1920px×1 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
- **цвет текста вне палитры** (2)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 768px×1, 1280px×1, 1920px×1 — напр. `header.header > div.logo > h1` «Калькулятор обмена»
  - `#BCBFC4 (ближайший navy-300 #CBD5E1, ΔE 6.3)` — 768px×1, 1280px×1, 1920px×1 — напр. `div.rates-grid > div.rate-item.highlight > div.rate-label` «Примерный курс»
- **фон вне палитры** (2)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 768px×5, 1280px×5, 1920px×5 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 768px×2, 1280px×2, 1920px×2 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **цвет рамки вне палитры** (2)
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 768px×8, 1280px×8, 1920px×8 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 768px×4, 1280px×4, 1920px×4 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **тень вне словаря** (2)
  - `rgba(0, 0, 0, 0.05) 0px 1px 2px 0px` — 768px×3, 1280px×3, 1920px×3 — напр. `div#ratesCard`
  - `rgba(249, 115, 22, 0.25) 0px 4px 12px 0px` — 768px×1, 1280px×1, 1920px×1 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»
- **радиус вне шкалы 8/12/999** (1)
  - `16px` — 768px×3, 1280px×3, 1920px×3 — напр. `div#ratesCard`

### Гейт 2. Гардрейлы: 768px FAIL · 1280px FAIL · 1920px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **весов на экране больше 3** (1)
  - `5: 400, 500, 600, 700, 800` — 768px×1, 1280px×1, 1920px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 768px×1, 1280px×1, 1920px×1
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 768px×2, 1280px×2, 1920px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
- **transition: all** (1)
  - `all` — 768px×16, 1280px×16, 1920px×16 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
- **кнопка/чип-«сосиска» (полностью скруглённый кликабельный)** (1)
  - `radius 999px, h 25px` — 768px×2, 1280px×2, 1920px×2 — напр. `button#srcBitazza` «Bitazza»
- **анимируется не transform/opacity** (1)
  - `background` — 768px×1, 1280px×1, 1920px×1 — напр. `div#exchangeCard > div.info-card > div.info-header`
- **эмодзи в кнопке/ссылке/табе/заголовке** (13)
  - `💱` — 768px×1, 1280px×1, 1920px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `🏠` — 768px×1, 1280px×1, 1920px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «🏠 Фрихолд»
  - `📜` — 768px×1, 1280px×1, 1920px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «📜 Лизхолд»
  - `✏` — 768px×1, 1280px×1, 1920px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn` «✏️ Другое»
  - `🏦` — 768px×1, 1280px×1, 1920px×1 — напр. `div#methodSwitcher > button.method-btn.active` «🏦 СБП»
  - `💼` — 768px×1, 1280px×1, 1920px×1 — напр. `div#methodSwitcher > button.method-btn` «💼 Брокер»
  - `🎨` — 768px×1, 1280px×1, 1920px×1 — напр. `div#methodSwitcher > button.method-btn` «🎨 Кастом»
  - `💰` — 768px×1, 1280px×1, 1920px×1 — напр. `div.scenarios-grid > button.scenario-btn.active > span.scenario-icon` «💰»
  - `💸` — 768px×1, 1280px×1, 1920px×1 — напр. `div.scenarios-grid > button.scenario-btn > span.scenario-icon` «💸»
  - `💵` — 768px×1, 1280px×1, 1920px×1 — напр. `div.scenarios-grid > button.scenario-btn > span.scenario-icon` «💵»
  - … и ещё 3 (полный список в JSON)
- **кеглей на экране больше 4** (1)
  - `11: 9, 10, 11, 12, 13, 14, 15, 16, 20, 22, 32` — 768px×1, 1280px×1, 1920px×1
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (5)
  - `🧮` — 768px×1, 1280px×1, 1920px×1 — напр. `header.header > div.logo > span.logo-icon` «🧮»
  - `↔↔` — 768px×1, 1280px×1, 1920px×1 — напр. `div.container > header.header > div.subtitle` «RUB ↔ THB ↔ USDT | v5 ТОЧНЫЕ КУРСЫ»
  - `📊` — 768px×1, 1280px×1, 1920px×1 — напр. `div#ratesCard > div.rates-header > span.rates-title` «📊 Актуальные курсы»
  - `🎁` — 768px×1, 1280px×1, 1920px×1 — напр. `div.discount-header > label.checkbox-label > span.checkbox-text` «🎁 Сделать скидку (изменить прибыль)»
  - … и ещё 1 (полный список в JSON)
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (1)
  - `.amount-input` — 768px×1, 1280px×1, 1920px×1 — напр. `.amount-input`

### Гейт 3. Контраст WCAG AA: 768px FAIL · 1280px FAIL · 1920px FAIL
- **контраст ниже 4.5:1** (7)
  - `#94A3B8 на #F8FAFC = 2.45:1 (11px/600)` — 768px×2, 1280px×2, 1920px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»
  - `#94A3B8 на #FFFFFF = 2.56:1 (11px/400)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#ratesUpdated` «Обновлено:»
  - `#94A3B8 на #F8FAFC = 2.45:1 (10px/500)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#usdtThbLabel` «USDT-THB (Bitazza)»
  - `#64748B на #F1F5F9 = 4.34:1 (12px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `button#srcBinance` «Binance»
  - `#94A3B8 на #F8FAFC = 2.45:1 (9px/400)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#usdtThbSub` «VWAP 33.65 · −0.15% · −20฿/сделку»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `div.container > div.dealtype-switcher > button.dealtype-btn.active` «💱 Обмен»
  - `#94A3B8 на #FFFFFF = 2.56:1 (20px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `span#inputCurrency` «₽»
- **контраст ниже 3:1** (1)
  - `#FFFFFF на #F97316 = 2.80:1 (16px/700)` — 768px×1, 1280px×1, 1920px×1 — напр. `button#calculateBtn` «🚀 РАССЧИТАТЬ»

### Гейт 4. Ширины: 768px PASS · 1280px PASS · 1920px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (2)
  - `25px` — 768px×2, 1280px×2, 1920px×2 — напр. `button#srcBitazza` «Bitazza»
  - `36px` — 768px×1, 1280px×1, 1920px×1 — напр. `button#refreshBtn` «↻
Обновить»

### Гейт 5. Текст: 768px PASS · 1280px PASS · 1920px PASS
находок нет

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-calculator/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-calculator/before-karim-1280.png`
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
  - `uppercase` — 375px×2, 768px×2, 1280px×2, 1920px×2 — напр. `div.container > div.switcher-caption` «Тип сделки»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
