# design-gate · check — **FAIL**

URL: `http://127.0.0.1:59105/crm?section=dashboard`
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
- 375px: элементов 431, контраст проверен у 265, главных кнопок 0, адресов 0

### Гейт 1. Токены: 375px FAIL
- **отступ вне шкалы 4/8/12/16/24** (11)
  - `padding 10px` — 375px×127 — напр. `thead > tr > th.ue-group.fin` «Показатель»
  - `margin-вертикаль 2px` — 375px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `padding 14px` — 375px×12 — напр. `div.container`
  - `padding 20px` — 375px×8 — напр. `section#dashboard > div.card`
  - `margin-вертикаль 10px` — 375px×5 — напр. `div#marginsNote` «Две маржи расходятся не по ошибке: «по сделкам» — простое ср»
  - `margin-вертикаль 14px` — 375px×5 — напр. `section#dashboard > div > div.card`
  - `padding 6px` — 375px×3 — напр. `div.site-shell.site-shell-mobile-head > span.site-shell-bell > a`
  - `padding 120px` — 375px×1 — напр. `div.container`
  - `gap 6px` — 375px×1 — напр. `div#periodSelector`
  - `margin-вертикаль 20px` — 375px×1 — напр. `div#statsGrid`
  - … и ещё 1 (полный список в JSON)
- **шрифт вне токенов** (1)
  - `arial` — 375px×10 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **кегль вне шкалы** (6)
  - `15px` — 375px×52 — напр. `tr > td > span.ue-val` «1»
  - `10px` — 375px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `13px` — 375px×22 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `11px` — 375px×9 — напр. `div#statsGrid > div.stat-card > div` «по деньгам 0,7% · после рефералов 0,7%»
  - `28px` — 375px×4 — напр. `div#convTotals > div > div` «100%»
  - `32px` — 375px×3 — напр. `div#buyersNew` «1»
- **вес вне шкалы** (2)
  - `500` — 375px×19 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `800` — 375px×11 — напр. `div#statsGrid > div.stat-card > div.stat-value` «1»
- **цвет текста вне палитры** (14)
  - `#333333 (ближайший navy-700 #334155, ΔE 11.4)` — 375px×39 — напр. `tbody > tr > th.ue-name` «Сделок»
  - `#222222 (ближайший ink-navy #0F172A, ΔE 11.6)` — 375px×37 — напр. `tr > td > span.ue-val` «1»
  - `#888888 (ближайший navy-400 #94A3B8, ΔE 12.9)` — 375px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 375px×19 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 375px×13 — напр. `div#statsGrid > div.stat-card.success > div.stat-value` «$1000»
  - `#BBBBBB (ближайший navy-300 #CBD5E1, ΔE 8.8)` — 375px×10 — напр. `tr > td > span.ue-val.na` «—»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 375px×8 — напр. `div#statsGrid > div.stat-card > div.stat-value` «1»
  - `#555555 (ближайший navy-600 #475569, ΔE 10.2)` — 375px×8 — напр. `thead > tr > th.ue-group.fin` «Показатель»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 375px×4 — напр. `div#statsGrid > div.stat-card.warning > div.stat-value` «$0»
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 375px×3 — напр. `div#convTotals > div > div` «100%»
  - … и ещё 4 (полный список в JSON)
- **цвет рамки вне палитры** (4)
  - `#E5E7EB (ближайший navy-200 #E2E8F0, ΔE 2.2)` — 375px×476 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `#FF6B35 (ближайший action-coral #C2410C, ΔE 16.6)` — 375px×4 — напр. `div#periodSelector > button.period-btn.active` «30 дней»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 375px×2 — напр. `div#statsGrid > div.stat-card.warning`
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 375px×1 — напр. `div#statsGrid > div.stat-card.success`
- **фон вне палитры** (4)
  - `#F6EEFB (ближайший blocker-surface #FEF2F2, ΔE 5.8)` — 375px×2 — напр. `thead > tr > th.ue-group.fin` «Показатель»
  - `#FF6B35 (ближайший action-coral #C2410C, ΔE 16.6)` — 375px×1 — напр. `div#periodSelector > button.period-btn.active` «30 дней»
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 375px×1 — напр. `tr > td > span.badge.badge-completed` «Завершена»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 375px×1 — напр. `tr > td > span.badge.badge-pending` «Ожидает»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 375px×20 — напр. `div#statsGrid > div.stat-card`

### Гейт 2. Гардрейлы: 375px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **кеглей на экране больше 4** (1)
  - `10: 10, 11, 12, 13, 14, 15, 16, 22, 28, 32` — 375px×1
- **весов на экране больше 3** (1)
  - `5: 400, 500, 600, 700, 800` — 375px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 375px×1
- **кнопка/чип-«сосиска» (полностью скруглённый кликабельный)** (2)
  - `radius 20px, h 33px` — 375px×5 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `radius 20px, h 35px` — 375px×3 — напр. `select#dashMonth` «Месяц…»
- **transition: all** (1)
  - `all` — 375px×10 — напр. `div#periodSelector > button.period-btn` «Сегодня»
- **цветная полоса слева (border-left)** (2)
  - `3px #F59E0B` — 375px×2 — напр. `div#statsGrid > div.stat-card.warning`
  - `3px #22C55E` — 375px×1 — напр. `div#statsGrid > div.stat-card.success`
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 375px×91 — напр. `thead > tr > th.ue-group.fin` «Показатель»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 375px×1 — напр. `.kyc-review-photo img:hover`
- (warn) **длинный текст 12px — если его надо читать, нужен Body 14px** (1)
  - `12px >120 симв.` — 375px×4 — напр. `div#marginsNote` «Две маржи расходятся не по ошибке: «по сделкам» — простое ср»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 375px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 375px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 375px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 375px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 375px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 375px FAIL
- **контраст ниже 4.5:1** (14)
  - `#888888 на #FAFAFA = 3.40:1 (10px/400)` — 375px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `#16A34A на #FFFFFF = 3.30:1 (15px/700)` — 375px×10 — напр. `tr > td > span.ue-val.good` «0,7%»
  - `#BBBBBB на #FFFFFF = 1.92:1 (15px/400)` — 375px×5 — напр. `tr > td > span.ue-val.na` «—»
  - `#BBBBBB на #FFFFFF = 1.92:1 (13px/400)` — 375px×5 — напр. `tr > td > span` «—»
  - `#FFFFFF на #FF6B35 = 2.84:1 (13px/500)` — 375px×1 — напр. `div#periodSelector > button.period-btn.active` «30 дней»
  - `#999999 на #F8FAFC = 2.72:1 (16px/400)` — 375px×1 — напр. `div#periodSelector > span > span` «—»
  - `#16A34A на #FFFFFF = 3.30:1 (13px/400)` — 375px×1 — напр. `tr > td > span` «(1 нов.)»
  - `#16A34A на #FFFFFF = 3.30:1 (13px/600)` — 375px×1 — напр. `tbody > tr > td` «$1 000»
  - `#22C55E на #FFFFFF = 2.28:1 (14px/600)` — 375px×1 — напр. `tbody#convBody > tr > td` «100%»
  - `#3B82F6 на #FFFFFF = 3.68:1 (14px/400)` — 375px×1 — напр. `tbody#convBody > tr > td` «—»
  - … и ещё 4 (полный список в JSON)
- **контраст ниже 3:1** (4)
  - `#F59E0B на #FFFFFF = 2.15:1 (22px/800)` — 375px×2 — напр. `div#statsGrid > div.stat-card.warning > div.stat-value` «$0»
  - `#22C55E на #FFFFFF = 2.28:1 (28px/700)` — 375px×1 — напр. `div#convTotals > div > div` «100%»
  - `#F59E0B на #FFFFFF = 2.15:1 (28px/700)` — 375px×1 — напр. `div#convTotals > div > div` «$0»
  - `#22C55E на #FFFFFF = 2.28:1 (32px/700)` — 375px×1 — напр. `div#buyersNew` «1»

### Гейт 4. Ширины: 375px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `33px` — 375px×5 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `35px` — 375px×3 — напр. `select#dashMonth` «Месяц…
октябрь 2026
сентябрь 2026
август 2026
июль 2026
июнь»
  - `31px` — 375px×2 — напр. `input#dashFrom`

### Гейт 5. Текст: 375px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `1000 $ × 14` — 375px×14 — напр. `div#statsGrid > div.stat-card.success > div.stat-value` «$1000»
  - `140243 $ × 10` — 375px×10 — напр. `div#statsGrid > div.stat-card > div.stat-value` «$140 243»
  - `139243 $ × 2` — 375px×2 — напр. `div#statsGrid > div.stat-card > div.stat-value` «$139 243»
  - `1000,00 $ × 2` — 375px×2 — напр. `tbody#recentDealsTable > tr > td` «$1000.00»

## Компьютер (>700px)
- 768px: элементов 429, контраст проверен у 260, главных кнопок 0, адресов 0
- 1280px: элементов 434, контраст проверен у 265, главных кнопок 0, адресов 0
- 1920px: элементов 434, контраст проверен у 265, главных кнопок 0, адресов 0

### Гейт 1. Токены: 768px FAIL · 1280px FAIL · 1920px FAIL
- **отступ вне шкалы 4/8/12/16/24** (10)
  - `padding 10px` — 768px×127, 1280px×127, 1920px×127 — напр. `thead > tr > th.ue-group.fin` «Показатель»
  - `margin-вертикаль 2px` — 768px×30, 1280px×30, 1920px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `padding 20px` — 768px×10, 1280px×9, 1920px×9 — напр. `div.container`
  - `margin-вертикаль 10px` — 768px×5, 1280px×5, 1920px×5 — напр. `div#marginsNote` «Две маржи расходятся не по ошибке: «по сделкам» — простое ср»
  - `padding 6px` — 768px×3, 1280px×3, 1920px×3 — напр. `div.site-shell-right > span.site-shell-bell > a`
  - `gap 6px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#periodSelector`
  - `margin-вертикаль 20px` — 768px×1, 1280px×1, 1920px×1 — напр. `div#statsGrid`
  - `padding 32px` — 1280px×1, 1920px×1 — напр. `div.container`
  - `padding 60px` — 1280px×1, 1920px×1 — напр. `div.container`
  - `padding 100px` — 768px×1 — напр. `div.container`
- **шрифт вне токенов** (1)
  - `arial` — 768px×10, 1280px×10, 1920px×10 — напр. `nav.site-shell-sections > button.site-shell-scroll` «‹»
- **кегль вне шкалы** (7)
  - `15px` — 768px×52, 1280px×52, 1920px×52 — напр. `tr > td > span.ue-val` «1»
  - `10px` — 768px×30, 1280px×30, 1920px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `13px` — 768px×22, 1280px×22, 1920px×22 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `24px` — 768px×11, 1280px×11, 1920px×11 — напр. `div#statsGrid > div.stat-card > div.stat-value` «1»
  - `11px` — 768px×9, 1280px×9, 1920px×9 — напр. `div#statsGrid > div.stat-card > div` «по деньгам 0,7% · после рефералов 0,7%»
  - `28px` — 768px×4, 1280px×4, 1920px×4 — напр. `div#convTotals > div > div` «100%»
  - `32px` — 768px×3, 1280px×3, 1920px×3 — напр. `div#buyersNew` «1»
- **вес вне шкалы** (2)
  - `500` — 768px×19, 1280px×19, 1920px×19 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `800` — 768px×11, 1280px×11, 1920px×11 — напр. `div#statsGrid > div.stat-card > div.stat-value` «1»
- **цвет текста вне палитры** (14)
  - `#333333 (ближайший navy-700 #334155, ΔE 11.4)` — 768px×39, 1280px×39, 1920px×39 — напр. `tbody > tr > th.ue-name` «Сделок»
  - `#222222 (ближайший ink-navy #0F172A, ΔE 11.6)` — 768px×37, 1280px×37, 1920px×37 — напр. `tr > td > span.ue-val` «1»
  - `#888888 (ближайший navy-400 #94A3B8, ΔE 12.9)` — 768px×30, 1280px×30, 1920px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `#666666 (ближайший navy-500 #64748B, ΔE 12.0)` — 768px×19, 1280px×19, 1920px×19 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `#16A34A (ближайший money-ink #065F46, ΔE 26.5)` — 768px×13, 1280px×13, 1920px×13 — напр. `div#statsGrid > div.stat-card.success > div.stat-value` «$1000»
  - `#BBBBBB (ближайший navy-300 #CBD5E1, ΔE 8.8)` — 768px×10, 1280px×10, 1920px×10 — напр. `tr > td > span.ue-val.na` «—»
  - `#1E293B (ближайший ink-navy #0F172A, ΔE 6.1)` — 768px×8, 1280px×8, 1920px×8 — напр. `div#statsGrid > div.stat-card > div.stat-value` «1»
  - `#555555 (ближайший navy-600 #475569, ΔE 10.2)` — 768px×8, 1280px×8, 1920px×8 — напр. `thead > tr > th.ue-group.fin` «Показатель»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 768px×4, 1280px×4, 1920px×4 — напр. `div#statsGrid > div.stat-card.warning > div.stat-value` «$0»
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 768px×3, 1280px×3, 1920px×3 — напр. `div#convTotals > div > div` «100%»
  - … и ещё 4 (полный список в JSON)
- **цвет рамки вне палитры** (4)
  - `#E5E7EB (ближайший navy-200 #E2E8F0, ΔE 2.2)` — 768px×476, 1280px×476, 1920px×476 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `#FF6B35 (ближайший action-coral #C2410C, ΔE 16.6)` — 768px×4, 1280px×4, 1920px×4 — напр. `div#periodSelector > button.period-btn.active` «30 дней»
  - `#F59E0B (ближайший decision-border #FDE68A, ΔE 21.6)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#statsGrid > div.stat-card.warning`
  - `#22C55E (ближайший money-border #BBF7D0, ΔE 20.4)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#statsGrid > div.stat-card.success`
- **фон вне палитры** (4)
  - `#F6EEFB (ближайший blocker-surface #FEF2F2, ΔE 5.8)` — 768px×2, 1280px×2, 1920px×2 — напр. `thead > tr > th.ue-group.fin` «Показатель»
  - `#FF6B35 (ближайший action-coral #C2410C, ΔE 16.6)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#periodSelector > button.period-btn.active` «30 дней»
  - `#D1FAE5 (ближайший money-border #BBF7D0, ΔE 6.2)` — 768px×1, 1280px×1, 1920px×1 — напр. `tr > td > span.badge.badge-completed` «Завершена»
  - `#FEF3C7 (ближайший decision-surface #FFFBEB, ΔE 8.8)` — 768px×1, 1280px×1, 1920px×1 — напр. `tr > td > span.badge.badge-pending` «Ожидает»
- **тень вне словаря** (1)
  - `rgba(0, 0, 0, 0.04) 0px 1px 3px 0px` — 768px×20, 1280px×20, 1920px×20 — напр. `div#statsGrid > div.stat-card`

### Гейт 2. Гардрейлы: 768px FAIL · 1280px FAIL · 1920px FAIL
_Гардрейлы 1–2, 7, 8, 11 дублируют гейты 1, 3, 4, 5 — их находки там._
- **весов на экране больше 3** (1)
  - `5: 400, 500, 600, 700, 800` — 768px×1, 1280px×1, 1920px×1
- **больше одного текстового шрифта** (1)
  - `inter, arial` — 768px×1, 1280px×1, 1920px×1
- **кнопка/чип-«сосиска» (полностью скруглённый кликабельный)** (2)
  - `radius 20px, h 33px` — 768px×5, 1280px×5, 1920px×5 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `radius 20px, h 35px` — 768px×3, 1280px×3, 1920px×3 — напр. `select#dashMonth` «Месяц…»
- **transition: all** (1)
  - `all` — 768px×10, 1280px×10, 1920px×10 — напр. `div#periodSelector > button.period-btn` «Сегодня»
- **цветная полоса слева (border-left)** (2)
  - `3px #F59E0B` — 768px×2, 1280px×2, 1920px×2 — напр. `div#statsGrid > div.stat-card.warning`
  - `3px #22C55E` — 768px×1, 1280px×1, 1920px×1 — напр. `div#statsGrid > div.stat-card.success`
- **text-transform: uppercase (капслок)** (1)
  - `uppercase` — 768px×91, 1280px×91, 1920px×91 — напр. `thead > tr > th.ue-group.fin` «Показатель»
- **hover-зум** (1)
  - `.kyc-review-photo img:hover` — 768px×1, 1280px×1, 1920px×1 — напр. `.kyc-review-photo img:hover`
- **кеглей на экране больше 4** (1)
  - `11: 10, 11, 12, 13, 14, 15, 16, 22, 24, 28, 32` — 768px×1, 1280px×1, 1920px×1
- (warn) **длинный текст 12px — если его надо читать, нужен Body 14px** (1)
  - `12px >120 симв.` — 768px×4, 1280px×4, 1920px×4 — напр. `div#marginsNote` «Две маржи расходятся не по ошибке: «по сделкам» — простое ср»
- (warn) **кнопка-иконка без видимой подписи (есть aria-label)** (2)
  - `‹` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Предыдущие разделы»
  - `›` — 768px×1, 1280px×1, 1920px×1 — напр. `nav.site-shell-sections > button.site-shell-scroll` «Следующие разделы»
- (warn) **outline:none — проверь кольцо фокуса** (4)
  - `.form-control:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.form-control:focus`
  - `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn` — 768px×1, 1280px×1, 1920px×1 — напр. `.custom-select-btn:focus, .custom-select-wrap.open .custom-select-btn`
  - `.docs-amount input:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-amount input:focus`
  - `.docs-purpose textarea:focus` — 768px×1, 1280px×1, 1920px×1 — напр. `.docs-purpose textarea:focus`

### Гейт 3. Контраст WCAG AA: 768px FAIL · 1280px FAIL · 1920px FAIL
- **контраст ниже 4.5:1** (14)
  - `#888888 на #FAFAFA = 3.40:1 (10px/400)` — 768px×30, 1280px×30, 1920px×30 — напр. `tr > th.ue-name > span.ue-sub` «приход клиентов в USDT»
  - `#16A34A на #FFFFFF = 3.30:1 (15px/700)` — 768px×10, 1280px×10, 1920px×10 — напр. `tr > td > span.ue-val.good` «0,7%»
  - `#BBBBBB на #FFFFFF = 1.92:1 (15px/400)` — 768px×5, 1280px×5, 1920px×5 — напр. `tr > td > span.ue-val.na` «—»
  - `#BBBBBB на #FFFFFF = 1.92:1 (13px/400)` — 768px×5, 1280px×5, 1920px×5 — напр. `tr > td > span` «—»
  - `#FFFFFF на #FF6B35 = 2.84:1 (13px/500)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#periodSelector > button.period-btn.active` «30 дней»
  - `#999999 на #F8FAFC = 2.72:1 (16px/400)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#periodSelector > span > span` «—»
  - `#16A34A на #FFFFFF = 3.30:1 (13px/400)` — 768px×1, 1280px×1, 1920px×1 — напр. `tr > td > span` «(1 нов.)»
  - `#16A34A на #FFFFFF = 3.30:1 (13px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `tbody > tr > td` «$1 000»
  - `#22C55E на #FFFFFF = 2.28:1 (14px/600)` — 768px×1, 1280px×1, 1920px×1 — напр. `tbody#convBody > tr > td` «100%»
  - `#3B82F6 на #FFFFFF = 3.68:1 (14px/400)` — 768px×1, 1280px×1, 1920px×1 — напр. `tbody#convBody > tr > td` «—»
  - … и ещё 4 (полный список в JSON)
- **контраст ниже 3:1** (4)
  - `#F59E0B на #FFFFFF = 2.15:1 (24px/800)` — 768px×2, 1280px×2, 1920px×2 — напр. `div#statsGrid > div.stat-card.warning > div.stat-value` «$0»
  - `#22C55E на #FFFFFF = 2.28:1 (28px/700)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#convTotals > div > div` «100%»
  - `#F59E0B на #FFFFFF = 2.15:1 (28px/700)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#convTotals > div > div` «$0»
  - `#22C55E на #FFFFFF = 2.28:1 (32px/700)` — 768px×1, 1280px×1, 1920px×1 — напр. `div#buyersNew` «1»

### Гейт 4. Ширины: 768px PASS · 1280px PASS · 1920px PASS
- (warn) **нажимаемая цель ниже 44px (Thumb Rule)** (3)
  - `33px` — 768px×5, 1280px×5, 1920px×5 — напр. `div#periodSelector > button.period-btn` «Сегодня»
  - `35px` — 768px×3, 1280px×3, 1920px×3 — напр. `select#dashMonth` «Месяц…
октябрь 2026
сентябрь 2026
август 2026
июль 2026
июнь»
  - `31px` — 768px×2, 1280px×2, 1920px×2 — напр. `input#dashFrom`

### Гейт 5. Текст: 768px PASS · 1280px PASS · 1920px PASS
- (warn) **одна и та же сумма встречается на экране несколько раз (эвристика)** (4)
  - `1000 $ × 14` — 768px×14, 1280px×14, 1920px×14 — напр. `div#statsGrid > div.stat-card.success > div.stat-value` «$1000»
  - `140243 $ × 10` — 768px×10, 1280px×10, 1920px×10 — напр. `div#statsGrid > div.stat-card > div.stat-value` «$140 243»
  - `139243 $ × 2` — 768px×2, 1280px×2, 1920px×2 — напр. `div#statsGrid > div.stat-card > div.stat-value` «$139 243»
  - `1000,00 $ × 2` — 768px×2, 1280px×2, 1920px×2 — напр. `tbody#recentDealsTable > tr > td` «$1000.00»

## Гейт 6. Снимки — BLOCKED
_авто: наличие и непустота пар «до/после»; сравнение — глазами_
- 375px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-dashboard/before-karim-375.png`
- 1280px: после `None`, до `/private/tmp/calccrm-wave4a/outputs/calccrm-redesign/wave4a/machine-crm-dashboard/before-karim-1280.png`
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
  - `uppercase` — 375px×91, 768px×91, 1280px×91, 1920px×91 — напр. `thead > tr > th.ue-group.fin` «Показатель»

## Что остаётся человеку
Вкус и иерархия; «глагол в заголовке», фразы из переписки; сравнение снимков «до/после»; гардрейлы 13, 14, 17 целиком и непроверенная часть пунктов 3, 4, 5, 6, 8, 9, 10, 12, 16, 18.
