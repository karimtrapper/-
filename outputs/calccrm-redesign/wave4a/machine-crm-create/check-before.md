# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59104/crm`
DESIGN: `/Users/karimamirov/Desktop/untitled folder/outputs/calccrm-redesign/DESIGN.md`
Ширины: запрошено [375, 768, 1280, 1920], обязательны для PASS [375, 768, 1280, 1920]
Роль: karim

_Вердикт машинный: проверена автоматическая часть гейтов. Вкус, иерархия и пункты «MANUAL» ниже остаются человеку._

**Причины вердикта:**
- FAIL в гейтах: 1. Токены, 2. Гардрейлы, 3. Контраст WCAG AA, 4. Ширины
- 375px: снимок «после» не снят
- 1280px: снимок «после» не снят

| Гейт | Вердикт | 375 | 768 | 1280 | 1920 |
|---|---|---|---|---|---|
| 1. Токены | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 2. Гардрейлы | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 3. Контраст WCAG AA | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 4. Ширины | **FAIL** | FAIL | FAIL | FAIL | FAIL |
| 5. Текст | **PASS** | PASS | PASS | PASS | PASS |
| 6. Снимки | **BLOCKED** | PASS | PASS | PASS | PASS |

## Телефон (≤700px)
- 375px: элементов 175, контраст проверен у 90, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (10)
  - `padding 14px` — 375px×27 — напр. `div.container`
  - `margin-вертикаль 6px` — 375px×24 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `margin-вертикаль 14px` — 375px×21 — напр. `section#create > div.card`
  - `gap 6px` — 375px×9 — напр. `div#sberReqsGroup > div`
  - `padding 36px` — 375px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
  - `padding 6px` — 375px×3 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 20px` — 375px×3 — напр. `div#payinExtraBox > button.btn.btn-secondary` «+ ещё приход»
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `margin-вертикаль 10px` — 375px×1 — напр. `div#standardDealSection > div > div`
  - `padding 9px` — 375px×1 — напр. `div#standardDealSection > div > button` «＋ Добавить агента»
- **шрифт вне токенов** (1)
  - `arial` — 375px×5 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×1 — напр. `section#create > div.card`
- **кегль вне шкалы** (5)
  - `13px` — 375px×26 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `15px` — 375px×11 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
  - `18.72px` — 375px×4 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `13.3333px` — 375px×4 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `14.4px` — 375px×2 — напр. `div#cashBalanceInfo` «Загрузка...»
- **вес вне шкалы** (1)
  - `500` — 375px×22 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
- **цвет рамки вне палитры** (3)
  - `#86EFAC (ближайший money-border #BBF7D0, ΔE 8.4)` — 375px×12 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `#EEEEEE (ближайший page-mist #F8FAFC, ΔE 2.7)` — 375px×4 — напр. `form#createDealForm > hr`
  - `#BAE6FD (ближайший navy-300 #CBD5E1, ΔE 9.8)` — 375px×4 — напр. `div#sberReqsGroup`
- **цвет текста вне палитры** (8)
  - `#166534 (ближайший money-ink #065F46, ΔE 7.4)` — 375px×4 — напр. `div > div > strong` «👥 Агенты сделки»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 375px×2 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×2 — напр. `div#standardDealSection > p` «Если партнер помог со сделкой и получает часть прибыли»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 375px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#6B7280 (ближайший navy-500 #64748B, ΔE 4.1)` — 375px×1 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `#0369A1 (ближайший navy-500 #64748B, ΔE 12.9)` — 375px×1 — напр. `div#sberReqsGroup > div > strong` «🏦 Приходы Сбера»
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 375px×1 — напр. `div#payoutSectionStd > h3` «Pay-Out (Выдача)»
  - `#667EEA (ближайший navy-500 #64748B, ΔE 13.2)` — 375px×1 — напр. `h3#profitCalcTitle` «Расчет прибыли»
- **фон вне палитры** (2)
  - `#F0F9FF (ближайший navy-100 #F1F5F9, ΔE 2.2)` — 375px×1 — напр. `div#sberReqsGroup`
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 375px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
- **радиус вне шкалы 8/12/999** (1)
  - `6px` — 375px×1 — напр. `div#cashBalanceInfo` «Загрузка...»

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `9: 12, 13, 13.3333, 14, 14.4, 15, 16, 18.72, 22` — 375px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **transition: all** (1)
  - `all` — 375px×29 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
- **синий фон (синих плашек нет)** (1)
  - `#F0F9FF` — 375px×1 — напр. `div#sberReqsGroup`
- **эмодзи в кнопке/ссылке/табе/заголовке** (3)
  - `🔄` — 375px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `⬇` — 375px×1 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `🟰` — 375px×1 — напр. `button#saPreFlat` «🟰 В долю»
- **кнопка-иконка без видимой подписи** (1)
  - `🔄` — 375px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
- **плейсхолдер не помещается в поле (обрезан)** (2)
  - `Сумма ₽ вручную` — 375px×1 — напр. `input#sberManualAmount` «Сумма ₽ вручную»
  - `Комментарий` — 375px×1 — напр. `input#sberManualNote` «Комментарий»
- **ошибка в консоли** (18)
  - `Не удалось обновить счётчик заявок на выплату: {stack: "TypeError: Failed to fetch
    at refreshPayoutAttention (http:/` — 375px×7
  - `Не удалось загрузить курс: {stack: "TypeError: Failed to fetch
    at loadCurrentRate (http://127.0.0.1:59104/crm:3720:3` — 375px×3
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
  - `Ошибка загрузки партнёров: {stack: "TypeError: Failed to fetch
    at loadPartners (ht….0.0.1:59104/crm:3768:38)
    at ` — 375px×1
  - `Ошибка загрузки рефереров: {stack: "TypeError: Failed to fetch
    at loadReferrers (h….0.0.1:59104/crm:3769:39)
    at ` — 375px×1
  - … и ещё 8 (полный список в JSON)
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
  - `#0F172A` — 375px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
- **контраст ниже 3:1** (2)
  - `#10B981 на #FFFFFF = 2.54:1 (18.72px/700)` — 375px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#F59E0B на #FFFFFF = 2.15:1 (18.72px/700)` — 375px×1 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
- **контраст ниже 4.5:1** (3)
  - `#94A3B8 на #F0F9FF = 2.41:1 (13px/400)` — 375px×1 — напр. `div#sberIncomesAvail > div` «Нет незабранных приходов»
  - `#F59E0B на #F8FAFC = 2.05:1 (15px/600)` — 375px×1 — напр. `input#netProfit` «Ждём курс прихода»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 375px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
- **контраст плейсхолдера ниже 4.5:1** (1)
  - `#757575 на #F8FAFC = 4.40:1` — 375px×5 — напр. `input#cashBatchCostUsdt` «Авто»

### Гейт 4. Ширины: 375px FAIL
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `48px и 36px (Δверха 6px)` — 375px×2 — напр. `input#sberManualAmount`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `36px` — 375px×3 — напр. `div#sberReqsGroup > div > button.btn.btn-secondary` «＋ Добавить»
  - `37px` — 375px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `41px` — 375px×1 — напр. `div#standardDealSection > div > button` «＋ Добавить агента»

### Гейт 5. Текст: 375px PASS
находок нет

## Компьютер (>700px)
- 768px: элементов 173, контраст проверен у 85, главных кнопок 0, адресов 0
- 1280px: элементов 178, контраст проверен у 90, главных кнопок 0, адресов 0
- 1920px: элементов 178, контраст проверен у 90, главных кнопок 0, адресов 0

### Гейт 1. Токены: 768px FAIL · 1280px FAIL · 1920px FAIL
- **отступ вне шкалы 4/8/12/16/24** (12)
  - `padding 14px` — 768px×26, 1280px×26, 1920px×26 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
  - `margin-вертикаль 6px` — 768px×24, 1280px×24, 1920px×24 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `margin-вертикаль 14px` — 768px×20, 1280px×20, 1920px×20 — напр. `form#createDealForm > div.form-row > div.form-group`
  - `gap 6px` — 768px×9, 1280px×9, 1920px×9 — напр. `div#sberReqsGroup > div`
  - `padding 36px` — 768px×8, 1280px×8, 1920px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
  - `padding 20px` — 768px×5, 1280px×4, 1920px×4 — напр. `div.container`
  - `padding 6px` — 768px×3, 1280px×3, 1920px×3 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `margin-вертикаль 10px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > div > div`
  - `padding 9px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > div > button` «＋ Добавить агента»
  - `padding 32px` — 1280px×1, 1920px×1 — напр. `div.container`
  - … и ещё 2 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 768px×5, 1280px×5, 1920px×5 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 768px×1, 1280px×1, 1920px×1 — напр. `section#create > div.card`
- **кегль вне шкалы** (5)
  - `13px` — 768px×26, 1280px×26, 1920px×26 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
  - `15px` — 768px×11, 1280px×11, 1920px×11 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
  - `18.72px` — 768px×4, 1280px×4, 1920px×4 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `13.3333px` — 768px×4, 1280px×4, 1920px×4 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `14.4px` — 768px×2, 1280px×2, 1920px×2 — напр. `div#cashBalanceInfo` «Загрузка...»
- **вес вне шкалы** (1)
  - `500` — 768px×22, 1280px×22, 1920px×22 — напр. `div.form-row > div.form-group > label.form-label` «Менеджер»
- **цвет рамки вне палитры** (3)
  - `#86EFAC (ближайший money-border #BBF7D0, ΔE 8.4)` — 768px×12, 1280px×12, 1920px×12 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `#EEEEEE (ближайший page-mist #F8FAFC, ΔE 2.7)` — 768px×4, 1280px×4, 1920px×4 — напр. `form#createDealForm > hr`
  - `#BAE6FD (ближайший navy-300 #CBD5E1, ΔE 9.8)` — 768px×4, 1280px×4, 1920px×4 — напр. `div#sberReqsGroup`
- **цвет текста вне палитры** (8)
  - `#166534 (ближайший money-ink #065F46, ΔE 7.4)` — 768px×4, 1280px×4, 1920px×4 — напр. `div > div > strong` «👥 Агенты сделки»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#standardDealSection > p` «Если партнер помог со сделкой и получает часть прибыли»
  - `#10B981 (ближайший money-border #BBF7D0, ΔE 20.1)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#6B7280 (ближайший navy-500 #64748B, ΔE 4.1)` — 768px×1, 1280px×1, 1920px×1 — напр. `div.form-row > div.form-group > small` «введи сколько USDT реально пришло — курс посчитается из рубл»
  - `#0369A1 (ближайший navy-500 #64748B, ΔE 12.9)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#sberReqsGroup > div > strong` «🏦 Приходы Сбера»
  - `#EF4444 (ближайший action-coral #C2410C, ΔE 14.7)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#payoutSectionStd > h3` «Pay-Out (Выдача)»
  - `#667EEA (ближайший navy-500 #64748B, ΔE 13.2)` — 768px×1, 1280px×1, 1920px×1 — напр. `h3#profitCalcTitle` «Расчет прибыли»
- **фон вне палитры** (2)
  - `#F0F9FF (ближайший navy-100 #F1F5F9, ΔE 2.2)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#sberReqsGroup`
  - `#F97316 (ближайший action-coral #C2410C, ΔE 18.0)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
- **радиус вне шкалы 8/12/999** (1)
  - `6px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#cashBalanceInfo` «Загрузка...»

### Гейт 2. Гардрейлы: 768px FAIL · 1280px FAIL · 1920px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `9: 12, 13, 13.3333, 14, 14.4, 15, 16, 18.72, 22` — 768px×1, 1280px×1, 1920px×1
- **весов на экране больше 3** (1)
  - `4: 400, 500, 600, 700` — 768px×1, 1280px×1, 1920px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 768px×1, 1280px×1, 1920px×1
- **transition: all** (1)
  - `all` — 768px×29, 1280px×29, 1920px×29 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
- **синий фон (синих плашек нет)** (1)
  - `#F0F9FF` — 768px×1, 1280px×1, 1920px×1 — напр. `div#sberReqsGroup`
- **эмодзи в кнопке/ссылке/табе/заголовке** (3)
  - `🔄` — 768px×1, 1280px×1, 1920px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `⬇` — 768px×1, 1280px×1, 1920px×1 — напр. `button#saPreCascade` «⬇️ Каскадом»
  - `🟰` — 768px×1, 1280px×1, 1920px×1 — напр. `button#saPreFlat` «🟰 В долю»
- **кнопка-иконка без видимой подписи** (1)
  - `🔄` — 768px×1, 1280px×1, 1920px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
- **ошибка в консоли** (18)
  - `Не удалось обновить счётчик заявок на выплату: {stack: "TypeError: Failed to fetch
    at refreshPayoutAttention (http:/` — 768px×7, 1280px×7, 1920px×7
  - `Не удалось загрузить курс: {stack: "TypeError: Failed to fetch
    at loadCurrentRate (http://127.0.0.1:59104/crm:3720:3` — 768px×3, 1280px×3, 1920px×3
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
  - `Ошибка загрузки партнёров: {stack: "TypeError: Failed to fetch
    at loadPartners (ht….0.0.1:59104/crm:3768:38)
    at ` — 768px×1, 1280px×1, 1920px×1
  - `Ошибка загрузки рефереров: {stack: "TypeError: Failed to fetch
    at loadReferrers (h….0.0.1:59104/crm:3769:39)
    at ` — 768px×1, 1280px×1, 1920px×1
  - … и ещё 8 (полный список в JSON)
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 768px×1, 1280px×1, 1920px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **эмодзи в тексте (если это не контент пользователя — заменить иконкой)** (2)
  - `🏦` — 768px×1, 1280px×1, 1920px×1 — напр. `div#sberReqsGroup > div > strong` «🏦 Приходы Сбера»
  - `👥` — 768px×1, 1280px×1, 1920px×1 — напр. `div > div > strong` «👥 Агенты сделки»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **у поля нет подписи (label/aria-label) — плейсхолдер вместо подписи?** (13)
  - `Авто` — 768px×2, 1280px×2, 1920px×2 — напр. `input#cashBatchCostUsdt` «Авто»
  - `Поиск или новый клиент...` — 768px×1, 1280px×1, 1920px×1 — напр. `input#clientSearchInput` «Поиск или новый клиент...»
  - `100000` — 768px×1, 1280px×1, 1920px×1 — напр. `div#payinRubGroup > input.form-control` «100000»
  - `1000` — 768px×1, 1280px×1, 1920px×1 — напр. `div.form-row > div.form-group > input.form-control` «1000»
  - … и ещё 9 (полный список в JSON)
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 768px×1, 1280px×1, 1920px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px FAIL · 1280px FAIL · 1920px FAIL
- **фон под текстом — картинка/градиент, контраст не посчитать** (1)
  - `#0F172A` — 768px×8, 1280px×8, 1920px×8 — напр. `div.form-group > div.custom-select-wrap > button.custom-select-btn` «Выберите...»
- **контраст ниже 3:1** (2)
  - `#10B981 на #FFFFFF = 2.54:1 (18.72px/700)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > h3` «Pay-In (Получение)»
  - `#F59E0B на #FFFFFF = 2.15:1 (18.72px/700)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > h3` «Партнер-реферер (опционально)»
- **контраст ниже 4.5:1** (3)
  - `#94A3B8 на #F0F9FF = 2.41:1 (13px/400)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#sberIncomesAvail > div` «Нет незабранных приходов»
  - `#F59E0B на #F8FAFC = 2.05:1 (15px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `input#netProfit` «Ждём курс прихода»
  - `#FFFFFF на #F97316 = 2.80:1 (14px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > div > button.btn.btn-primary` «Создать сделку»
- **контраст плейсхолдера ниже 4.5:1** (1)
  - `#757575 на #F8FAFC = 4.40:1` — 768px×5, 1280px×5, 1920px×5 — напр. `input#cashBatchCostUsdt` «Авто»

### Гейт 4. Ширины: 768px FAIL · 1280px FAIL · 1920px FAIL
- **в ряду поля/кнопки разной высоты или смещены** (1)
  - `48px и 36px (Δверха 6px)` — 768px×2, 1280px×2, 1920px×2 — напр. `input#sberManualAmount`
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `36px` — 768px×3, 1280px×3, 1920px×3 — напр. `div#sberReqsGroup > div > button.btn.btn-secondary` «＋ Добавить»
  - `37px` — 768px×1, 1280px×1, 1920px×1 — напр. `div > div > button.btn.btn-secondary` «🔄»
  - `41px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#standardDealSection > div > button` «＋ Добавить агента»

### Гейт 5. Текст: 768px PASS · 1280px PASS · 1920px PASS
находок нет

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
