# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59110/crm?section=create`
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
- 375px: элементов 957, контраст проверен у 740, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (15)
  - `padding 14px` — 375px×157 — напр. `div.container`
  - `gap 6px` — 375px×139 — напр. `div#sberReqsGroup > div`
  - `padding 6px` — 375px×133 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 1px` — 375px×130 — напр. `div > span > span` «СБП»
  - `padding 5px` — 375px×130 — напр. `div > span > span` «СБП»
  - `margin-вертикаль 6px` — 375px×24 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `margin-вертикаль 14px` — 375px×21 — напр. `section#create > div.card`
  - `padding 36px` — 375px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
  - `padding 20px` — 375px×3 — напр. `div#payinExtraBox > button.btn.btn-secondary` «+ ещё приход»
  - `padding 120px` — 375px×1 — напр. `div.container`
  - … и ещё 5 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 375px×5 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (2)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#create > div.card`
  - `rgba(0, 0, 0, 0.28) 0px 10px 30px 0px` — 375px×1 — напр. `div.toast-container > div.toast.error` «Курс USDT-THB не загружен/устарел — расчёт приблизительный, »
- **кегль вне шкалы** (7)
  - `13px` — 375px×545 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `11px` — 375px×130 — напр. `div > span > span` «СБП»
  - `15px` — 375px×11 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
  - `18.72px` — 375px×4 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `13.3333px` — 375px×4 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `14.4px` — 375px×2 — напр. `div#cashBalanceInfo > span` «Касса пуста»
  - `17px` — 375px×1 — напр. `div.toast-container > div.toast.error` «Курс USDT-THB не загружен/устарел — расчёт приблизительный, »
- **вес вне шкалы** (1)
  - `500` — 375px×22 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
- **цвет рамки вне палитры** (4)
  - `#E0F2FE (ближайший navy-200 #E2E8F0, ΔE 4.7)` — 375px×130 — напр. `div#sberIncomesAvail > div`
  - `#86EFAC (ближайший money-border #BBF7D0, ΔE 8.4)` — 375px×12 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `#EEEEEE (ближайший page-mist #F8FAFC, ΔE 2.7)` — 375px×4 — напр. `form#createDealForm > hr`
  - `#BAE6FD (ближайший navy-300 #CBD5E1, ΔE 9.8)` — 375px×4 — напр. `div#sberReqsGroup`
- **цвет текста вне палитры** (9)
  - `#1D4ED8 (ближайший navy-600 #475569, ΔE 14.5)` — 375px×130 — напр. `div > span > span` «СБП»
  - `#166534 (ближайший money-ink #065F46, ΔE 7.4)` — 375px×4 — напр. `div > div > strong` «👥 Агенты сделки»
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 375px×2 — напр. `div#payoutSectionStd > h3` «Pay-Out (Выдача)»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 375px×2 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×2 — напр. `div#standardDealSection > p` «Если партнер помог со сделкой и получает часть прибыли»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 375px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#6B7280 (ближайший navy-500 #64748B, ΔE 4.1)` — 375px×1 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `#0369A1 (ближайший navy-500 #64748B, ΔE 12.9)` — 375px×1 — напр. `div#sberReqsGroup > div > strong` «🏦 Приходы Сбера»
  - `#667EEA (ближайший navy-500 #64748B, ΔE 13.2)` — 375px×1 — напр. `h3#profitCalcTitle` «Расчет прибыли»
- **фон вне палитры** (5)
  - `#DBEAFE (ближайший navy-200 #E2E8F0, ΔE 5.0)` — 375px×130 — напр. `div > span > span` «СБП»
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 375px×130 — напр. `div#sberIncomesAvail > div > button.btn.btn-success` «Забрать»
  - `#F0F9FF (ближайший navy-100 #F1F5F9, ΔE 2.2)` — 375px×1 — напр. `div#sberReqsGroup`
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 375px×1 — напр. `div.toast-container > div.toast.error` «Курс USDT-THB не загружен/устарел — расчёт приблизительный, »
- **радиус вне шкалы 8/12/999** (2)
  - `4px` — 375px×130 — напр. `div > span > span` «СБП»
  - `6px` — 375px×1 — напр. `div#cashBalanceInfo`

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `11: 11, 12, 13, 13.3333, 14, 14.4, 15, 16, 17, 18.72, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×159 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
- **синий фон (синих плашек нет)** (2)
  - `#DBEAFE` — 375px×130 — напр. `div > span > span` «СБП»
  - `#F0F9FF` — 375px×1 — напр. `div#sberReqsGroup`
- **анимация появления (keyframes)** (1)
  - `toastIn` — 375px×1 — напр. `div.toast-container > div.toast.error` «Курс USDT-THB не загружен/устарел — расчёт приблизительный, »
- **эмодзи в кнопке/ссылке/табе/заголовке** (3)
  - `🔄` — 375px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `⬇` — 375px×1 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `🟰` — 375px×1 — напр. `button#saPreFlat` «🟰 В долю»
- **кнопка-иконка без видимой подписи** (1)
  - `🔄` — 375px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
- **плейсхолдер не помещается в поле (обрезан)** (2)
  - `Сумма ₽ вручную` — 375px×1 — напр. `input#sberManualAmount` «Сумма ₽ вручную»
  - `Комментарий` — 375px×1 — напр. `input#sberManualNote` «Комментарий»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `🏦` — 375px×1 — напр. `div#sberReqsGroup > div > strong` «🏦 Приходы Сбера»
  - `👥` — 375px×1 — напр. `div > div > strong` «👥 Агенты сделки»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (13)
  - `Авто` — 375px×2 — напр. `input#cashBatchCostUsdt` «Авто»
  - `Поиск или новый клиент...` — 375px×1 — напр. `input#clientSearchInput` «Поиск или новый клиент...»
  - `100000` — 375px×1 — напр. `div#payinRubGroup > input.form-control` «100000»
  - `1000` — 375px×1 — напр. `div.form-row > div.form-group > input.form-control` «1000»
  - … и ещё 9 (полный список в JSON)
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 375px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
- **контраст ниже 3:1** (2)
  - `#10B981 на #FFFFFF = 2.54:1 (18.72px/700)` — 375px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#F59E0B на #FFFFFF = 2.15:1 (18.72px/700)` — 375px×1 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
- **контраст ниже 4.5:1** (6)
  - `#64748B на #F0F9FF = 4.46:1 (13px/400)` — 375px×130 — напр. `div > span > span` «(зачислено 536 274,36 + комиссия 3 780,38)»
  - `#FFFFFF на #22C55E = 2.28:1 (13px/600)` — 375px×130 — напр. `div#sberIncomesAvail > div > button.btn.btn-success` «Забрать»
  - `#EF4444 на #F0FDF4 = 3.59:1 (14.4px/400)` — 375px×1 — напр. `div#cashBalanceInfo > span` «Касса пуста»
  - `#F59E0B на #F8FAFC = 2.05:1 (15px/600)` — 375px×1 — напр. `input#netProfit` «Ждём курс прихода»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 375px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
  - `#FFFFFF на #EF4444 = 3.76:1 (17px/600)` — 375px×1 — напр. `div.toast-container > div.toast.error` «Курс USDT-THB не загружен/устарел — расчёт приблизительный, »
- **контраст плейсхолдера ниже 4.5:1** (1)
  - `#757575 на #F8FAFC = 4.40:1` — 375px×5 — напр. `input#cashBatchCostUsdt` «Авто»

### Гейт 4. Ширины: 375px FAIL
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `48px и 36px (Δверха 6px)` — 375px×2 — напр. `input#sberManualAmount`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `36px` — 375px×133 — напр. `div#sberIncomesAvail > div > button.btn.btn-success` «Забрать»
  - `37px` — 375px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `41px` — 375px×1 — напр. `div#standardDealSection > div > button` «＋ Добавить агента»

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (14)
  - `1,00 ₽ × 8` — 375px×8 — напр. `div > span > b` «1,00 ₽»
  - `35000,00 ₽ × 7` — 375px×7 — напр. `div > span > b` «35 000,00 ₽»
  - `40000,00 ₽ × 4` — 375px×4 — напр. `div > span > b` «40 000,00 ₽»
  - `999999,00 ₽ × 4` — 375px×4 — напр. `div > span > b` «999 999,00 ₽»
  - … и ещё 10 (полный список в JSON)

## Компьютер (>700px)
- 768px: **BLOCKED** — ширина не снята (не запрашивалась)
- 1280px: элементов 959, контраст проверен у 739, главных кнопок 0, адресов 0
- 1920px: **BLOCKED** — ширина не снята (не запрашивалась)

### Гейт 1. Токены: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **отступ вне шкалы 4/8/12/16/24** (14)
  - `padding 14px` — 1280px×156 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
  - `gap 6px` — 1280px×139 — напр. `div#sberReqsGroup > div`
  - `padding 6px` — 1280px×133 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `padding 1px` — 1280px×130 — напр. `div > span > span` «СБП»
  - `padding 5px` — 1280px×130 — напр. `div > span > span` «СБП»
  - `margin-вертикаль 6px` — 1280px×24 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `margin-вертикаль 14px` — 1280px×20 — напр. `form#createDealForm > div.form-row > div.form-group`
  - `padding 36px` — 1280px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
  - `padding 20px` — 1280px×4 — напр. `section#create > div.card`
  - `margin-вертикаль 10px` — 1280px×1 — напр. `div#standardDealSection > div > div`
  - … и ещё 4 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 1280px×5 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 1280px×1 — напр. `section#create > div.card`
- **кегль вне шкалы** (6)
  - `13px` — 1280px×545 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `11px` — 1280px×130 — напр. `div > span > span` «СБП»
  - `15px` — 1280px×11 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
  - `18.72px` — 1280px×4 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `13.3333px` — 1280px×4 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `14.4px` — 1280px×2 — напр. `div#cashBalanceInfo > span` «Касса пуста»
- **вес вне шкалы** (1)
  - `500` — 1280px×22 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
- **цвет рамки вне палитры** (4)
  - `#E0F2FE (ближайший navy-200 #E2E8F0, ΔE 4.7)` — 1280px×130 — напр. `div#sberIncomesAvail > div`
  - `#86EFAC (ближайший money-border #BBF7D0, ΔE 8.4)` — 1280px×12 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `#EEEEEE (ближайший page-mist #F8FAFC, ΔE 2.7)` — 1280px×4 — напр. `form#createDealForm > hr`
  - `#BAE6FD (ближайший navy-300 #CBD5E1, ΔE 9.8)` — 1280px×4 — напр. `div#sberReqsGroup`
- **цвет текста вне палитры** (9)
  - `#1D4ED8 (ближайший navy-600 #475569, ΔE 14.5)` — 1280px×130 — напр. `div > span > span` «СБП»
  - `#166534 (ближайший money-ink #065F46, ΔE 7.4)` — 1280px×4 — напр. `div > div > strong` «👥 Агенты сделки»
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 1280px×2 — напр. `div#payoutSectionStd > h3` «Pay-Out (Выдача)»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 1280px×2 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 1280px×2 — напр. `div#standardDealSection > p` «Если партнер помог со сделкой и получает часть прибыли»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 1280px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#6B7280 (ближайший navy-500 #64748B, ΔE 4.1)` — 1280px×1 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `#0369A1 (ближайший navy-500 #64748B, ΔE 12.9)` — 1280px×1 — напр. `div#sberReqsGroup > div > strong` «🏦 Приходы Сбера»
  - `#667EEA (ближайший navy-500 #64748B, ΔE 13.2)` — 1280px×1 — напр. `h3#profitCalcTitle` «Расчет прибыли»
- **фон вне палитры** (4)
  - `#DBEAFE (ближайший navy-200 #E2E8F0, ΔE 5.0)` — 1280px×130 — напр. `div > span > span` «СБП»
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 1280px×130 — напр. `div#sberIncomesAvail > div > button.btn.btn-success` «Забрать»
  - `#F0F9FF (ближайший navy-100 #F1F5F9, ΔE 2.2)` — 1280px×1 — напр. `div#sberReqsGroup`
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 1280px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
- **радиус вне шкалы 8/12/999** (2)
  - `4px` — 1280px×130 — напр. `div > span > span` «СБП»
  - `6px` — 1280px×1 — напр. `div#cashBalanceInfo`

### Гейт 2. Гардрейлы: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 1280px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 1280px×1
- **transition: all** (1)
  - `all` — 1280px×159 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
- **синий фон (синих плашек нет)** (2)
  - `#DBEAFE` — 1280px×130 — напр. `div > span > span` «СБП»
  - `#F0F9FF` — 1280px×1 — напр. `div#sberReqsGroup`
- **эмодзи в кнопке/ссылке/табе/заголовке** (3)
  - `🔄` — 1280px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `⬇` — 1280px×1 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `🟰` — 1280px×1 — напр. `button#saPreFlat` «🟰 В долю»
- **кнопка-иконка без видимой подписи** (1)
  - `🔄` — 1280px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 1280px×1 — напр. `.kyc-review-photo img:hover`
- **кеглей на экране больше 4** (1)
  - `10: 11, 12, 13, 13.3333, 14, 14.4, 15, 16, 18.72, 22` — 1280px×1
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `🏦` — 1280px×1 — напр. `div#sberReqsGroup > div > strong` «🏦 Приходы Сбера»
  - `👥` — 1280px×1 — напр. `div > div > strong` «👥 Агенты сделки»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 1280px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (13)
  - `Авто` — 1280px×2 — напр. `input#cashBatchCostUsdt` «Авто»
  - `Поиск или новый клиент...` — 1280px×1 — напр. `input#clientSearchInput` «Поиск или новый клиент...»
  - `100000` — 1280px×1 — напр. `div#payinRubGroup > input.form-control` «100000»
  - `1000` — 1280px×1 — напр. `div.form-row > div.form-group > input.form-control` «1000»
  - … и ещё 9 (полный список в JSON)
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 1280px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 1280px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 1280px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 1280px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 1280px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Карим»
- **контраст ниже 3:1** (2)
  - `#10B981 на #FFFFFF = 2.54:1 (18.72px/700)` — 1280px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#F59E0B на #FFFFFF = 2.15:1 (18.72px/700)` — 1280px×1 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
- **контраст ниже 4.5:1** (5)
  - `#64748B на #F0F9FF = 4.46:1 (13px/400)` — 1280px×130 — напр. `div > span > span` «(зачислено 536 274,36 + комиссия 3 780,38)»
  - `#FFFFFF на #22C55E = 2.28:1 (13px/600)` — 1280px×130 — напр. `div#sberIncomesAvail > div > button.btn.btn-success` «Забрать»
  - `#EF4444 на #F0FDF4 = 3.59:1 (14.4px/400)` — 1280px×1 — напр. `div#cashBalanceInfo > span` «Касса пуста»
  - `#F59E0B на #F8FAFC = 2.05:1 (15px/600)` — 1280px×1 — напр. `input#netProfit` «Ждём курс прихода»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 1280px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
- **контраст плейсхолдера ниже 4.5:1** (1)
  - `#757575 на #F8FAFC = 4.40:1` — 1280px×5 — напр. `input#cashBatchCostUsdt` «Авто»

### Гейт 4. Ширины: 768px BLOCKED · 1280px FAIL · 1920px BLOCKED
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `48px и 36px (Δверха 6px)` — 1280px×2 — напр. `input#sberManualAmount`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `36px` — 1280px×133 — напр. `div#sberIncomesAvail > div > button.btn.btn-success` «Забрать»
  - `37px` — 1280px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `41px` — 1280px×1 — напр. `div#standardDealSection > div > button` «＋ Добавить агента»

### Гейт 5. Текст: 768px BLOCKED · 1280px PASS · 1920px BLOCKED
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (14)
  - `1,00 ₽ × 8` — 1280px×8 — напр. `div > span > b` «1,00 ₽»
  - `35000,00 ₽ × 7` — 1280px×7 — напр. `div > span > b` «35 000,00 ₽»
  - `40000,00 ₽ × 4` — 1280px×4 — напр. `div > span > b` «40 000,00 ₽»
  - `999999,00 ₽ × 4` — 1280px×4 — напр. `div > span > b` «999 999,00 ₽»
  - … и ещё 10 (полный список в JSON)

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-create/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-create/before-karim-1280.png`
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

## Гардрейлы (18)

| № | Запрет | Охват | Вердикт |
|---|---|---|---|
| 1 | Один шрифт + моно, 4 кегля, 3 веса | auto | FAIL |
| 2 | Цвета/отступы/радиусы/тени только из токенов | auto | FAIL |
| 3 | Сосиски, градиенты, hover-зум, анимации появления | partial | FAIL |
| 4 | Кнопки без глагола, две главные, иконка без подписи | partial | FAIL |
| 5 | Эмодзи вместо иконок; один размер иконок | partial | FAIL |
| 6 | Цветные полосы слева, синие подсказки, оранжевый вне кнопки | partial | FAIL |
| 7 | Адрес/хеш в одну строку; ничего шире экрана | auto | PASS |
| 8 | Внутренние названия и коды на экране | partial | PASS* |
| 9 | Плейсхолдер вместо подписи / обрезанный плейсхолдер | partial | FAIL |
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
