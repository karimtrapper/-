# Волна 4a — инвентаризация текущего интерфейса

Машинный прогон вычисленных стилей на 375 и 1280 px: [сводка design-gate](machine-summary.md) и отдельные отчёты по всем разделам.

Дата: 14.10.2026. Источник: `static/crm/crm.html`, `static/calculator/index.html`, `static/calculator/styles.css`, `static/nav-shell.css` на базе `3566c92`. Это инвентаризация исходного состояния; правки интерфейса не внесены.

Метод: разобраны статическая HTML-разметка, встроенные/подключённые CSS и inline-стили. Селекторы сопоставлены с элементами каждого раздела, включая media rules. Состояния `:hover`, `:focus` и динамическая разметка JS учитываются отдельно; количество элементов ниже — в исходном DOM, до загрузки данных. Запись `var(...)` ниже означает фактическую CSS-переменную; её hex раскрыт в общей палитре.

## Общая палитра и типографика

Базовый `body` CRM: `Inter, sans-serif`, цвет `--text` = `--navy-900` = `#0F172A`, фон `--bg-page` = `--navy-50` = `#F8FAFC`; базовый размер браузера 16px, явный `font-size` на `body` не задан. Базовый `body` калькулятора: `Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif`, те же текст и фон. `rem` ниже пересчитаны при стандартном корневом размере 16px; `em` зависит от родителя.

### CRM: переменные цвета

| Переменная | Значение |
|---|---|
| `--navy-900` | `#0F172A` |
| `--navy-800` | `#1E293B` |
| `--navy-700` | `#334155` |
| `--navy-600` | `#475569` |
| `--navy-500` | `#64748B` |
| `--navy-400` | `#94A3B8` |
| `--navy-300` | `#CBD5E1` |
| `--navy-200` | `#E2E8F0` |
| `--navy-100` | `#F1F5F9` |
| `--navy-50` | `#F8FAFC` |
| `--coral` | `#F97316` |
| `--coral-hover` | `#EA580C` |
| `--coral-light` | `#FFF7ED` |
| `--green` | `#22C55E` |
| `--green-light` | `#F0FDF4` |
| `--green-dark` | `#16A34A` |
| `--green-darker` | `#065F46` |
| `--red` | `#EF4444` |
| `--red-light` | `#FEF2F2` |
| `--blue` | `#3B82F6` |
| `--blue-light` | `#EFF6FF` |
| `--amber` | `#F59E0B` |
| `--amber-light` | `#FEF3C7` |
| `--indigo` | `#6366F1` |
| `--indigo-light` | `#EEF2FF` |
| `--bg` | `#FFFFFF` |

### Калькулятор: переменные цвета

| Переменная | Значение |
|---|---|
| `--navy-900` | `#0F172A` |
| `--navy-800` | `#1E293B` |
| `--navy-700` | `#334155` |
| `--navy-600` | `#475569` |
| `--navy-500` | `#64748B` |
| `--navy-400` | `#94A3B8` |
| `--navy-300` | `#CBD5E1` |
| `--navy-200` | `#E2E8F0` |
| `--navy-100` | `#F1F5F9` |
| `--navy-50` | `#F8FAFC` |
| `--coral` | `#F97316` |
| `--coral-hover` | `#EA580C` |
| `--coral-light` | `#FFF7ED` |
| `--green` | `#22C55E` |
| `--green-light` | `#F0FDF4` |
| `--green-dark` | `#16A34A` |
| `--green-darker` | `#065F46` |
| `--red` | `#EF4444` |
| `--red-light` | `#FEF2F2` |
| `--blue` | `#3B82F6` |
| `--blue-light` | `#EFF6FF` |
| `--amber` | `#F59E0B` |
| `--amber-light` | `#FEF3C7` |
| `--indigo` | `#6366F1` |
| `--indigo-light` | `#EEF2FF` |
| `--bg` | `#FFFFFF` |
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` |
| `--shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.07)` |
| `--shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.08)` |

## Сделки

Источник: `static/crm/crm.html`, `<section id="deals">`.

**Элементы в исходной разметке:** кнопок 4, полей `input` 3, `select` 2, `textarea` 0, таблиц 1, `.card` 2, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Таблицы: классы `—`.

Поля: `form-control` × 5.

**Вариантов кнопок по классам/inline: 3** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary` | 1 | Применить |
| `btn btn-primary nav-create-btn` | 1 | + Создать сделку |
| `btn btn-sm btn-secondary` | 2 | ← Назад; Вперёд → |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 12px, 13px, 14px, 14px [inline], 15px, 16px, 22px; **font-weight**: 500, 600, 700

**Цвета из применимых CSS/inline правил:** **color**: var(--navy-500) [inline], var(--navy-600), var(--navy-700), var(--navy-800), var(--text), var(--text-sec), white; **background**: var(--bg), var(--coral), var(--coral-hover), var(--navy-100), var(--navy-200), var(--navy-50); **border**: 1.5px solid var(--border), 1px solid var(--border-light), none; **border-color**: var(--coral)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.btn-secondary` → background: var(--navy-100), color: var(--navy-700); `.btn-secondary:hover` → background: var(--navy-200).

## Документы

Источник: `static/crm/crm.html`, `<section id="documents">`.

**Элементы в исходной разметке:** кнопок 11, полей `input` 7, `select` 0, `textarea` 1, таблиц 0, `.card` 3, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Поля: `(без класса)` × 7, `form-input` × 1.

**Вариантов кнопок по классам/inline: 5** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn + inline` | 3 | Отмена; Заполнить вручную; Закрыть |
| `btn btn-primary` | 2 | Распознать; Создать пакет документов |
| `btn btn-primary + inline` | 1 | Новый договор |
| `docs-pair` | 4 | Фрихолд; Лизхолд; Аренда; Перевод / обмен |
| `docs-relink` | 1 | Собрать заново |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: .72rem (1rem = 16px: 11.52px), .75rem (1rem = 16px: 12px), .76rem (1rem = 16px: 12.16px), .78rem (1rem = 16px: 12.48px), .82rem (1rem = 16px: 13.12px), .84rem (1rem = 16px: 13.44px), .85rem (1rem = 16px: 13.6px), .85rem [inline] (1rem = 16px: 13.6px), .875rem (1rem = 16px: 14px), .88rem (1rem = 16px: 14.08px), .8rem (1rem = 16px: 12.8px), .8rem [inline] (1rem = 16px: 12.8px), .9rem (1rem = 16px: 14.4px), .9rem [inline] (1rem = 16px: 14.4px), 1.4rem (1rem = 16px: 22.4px), 14px, 16px; **font-weight**: 400, 500, 600, 600 [inline], 650, 700

**Цвета из применимых CSS/inline правил:** **color**: var(--coral), var(--coral-hover), var(--green-darker), var(--navy-500), var(--navy-600), var(--navy-600) [inline], var(--navy-700), var(--navy-800), var(--red), var(--text), var(--text-sec), white; **background**: none, transparent, var(--bg), var(--coral), var(--coral-hover), var(--navy-100), var(--navy-50); **border**: 0, 1px dashed var(--navy-300), 1px solid var(--border), 1px solid var(--border-light), 1px solid var(--navy-300), none; **border-color**: var(--coral), var(--navy-400), var(--navy-500); **border-left**: 1px solid var(--border)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.docs-money` → background: var(--navy-50); `.docs-amount` → background: var(--bg); `.docs-amount input` → background: transparent, color: var(--text); `.docs-amount input::placeholder` → color: var(--navy-500); `.docs-status` → color: var(--text-sec); `.docs-empty` → color: var(--text-sec).

## Закрытие

Источник: `static/crm/crm.html`, `<section id="closing">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 0, `select` 0, `textarea` 0, таблиц 0, `.card` 2, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 1.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-secondary` | 1 | ↻ Обновить |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #1E40AF, #64748b [inline], var(--navy-700), var(--text); **background**: var(--bg), var(--blue-light), var(--navy-100), var(--navy-200); **border**: 1px solid var(--border-light), none; **border-left**: 3px solid var(--blue)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-secondary` → background: var(--navy-100), color: var(--navy-700); `.btn-secondary:hover` → background: var(--navy-200).

## Обменники

Источник: `static/crm/crm.html`, `<section id="exchangers">`.

**Элементы в исходной разметке:** кнопок 9, полей `input` 2, `select` 3, `textarea` 0, таблиц 4, `.card` 4, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Таблицы: классы `—`; классы `—`; классы `—`; классы `—`.

Поля: `rx-inp` × 3, `rx-inp num` × 2.

**Вариантов кнопок по классам/inline: 5** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary btn-sm` | 1 | + Добавить приход |
| `btn btn-secondary btn-sm` | 1 | Сброс |
| `btn btn-secondary btn-sm + inline` | 2 | 🔄 Обновить из бота; 🔗 Объединить выбранные |
| `rx-subtab` | 4 | Конвертация от брокеров; Запросы; Мерчанты; Кошельки |
| `rx-subtab active` | 1 | Поступления |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit, ui-monospace,"SF Mono",Menlo,monospace; **font-size**: 12px, 12px [inline], 13px, 14px; **font-weight**: 600, 700 [inline]

**Цвета из применимых CSS/inline правил:** **color**: #fff, var(--navy-700), var(--text), var(--text-sec), white; **background**: #fff, none, var(--bg), var(--coral), var(--coral-hover), var(--navy-100), var(--navy-200), var(--navy-50), var(--navy-50) [inline], var(--navy-800); **border**: 1px solid var(--border), 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.btn-secondary` → background: var(--navy-100), color: var(--navy-700); `.btn-secondary:hover` → background: var(--navy-200).

## Баланс

Источник: `static/crm/crm.html`, `<section id="balance">`.

**Элементы в исходной разметке:** кнопок 8, полей `input` 4, `select` 2, `textarea` 0, таблиц 1, `.card` 3, `.stat-card` 4, `.badge` 0, `.pill` 0, `.alert` 0.

Таблицы: классы `table`.

Поля: `form-control` × 6.

**Вариантов кнопок по классам/inline: 6** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-outline-danger` | 1 | - Списать (-) |
| `btn btn-primary` | 1 | + Добавить карту |
| `btn btn-primary + inline` | 1 | + Добавить кошелек |
| `btn btn-sm btn-light balance-subtab-btn` | 2 | Наличные (THB); Карты (THB) |
| `btn btn-sm btn-light balance-subtab-btn active` | 1 | Binance (USDT) |
| `btn btn-success` | 2 | + Пополнить (+); Добавить партию |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 12px, 12px [(max-width: 640px)], 13px, 14px, 15px, 16px, 22px [(max-width: 640px)], 24px; **font-weight**: 500, 600, 700, 800

**Цвета из применимых CSS/inline правил:** **color**: var(--green-dark), var(--navy-600), var(--navy-800), var(--text), var(--text-sec), white; **background**: #f1f5f9 [inline], #fff [inline], var(--bg), var(--coral), var(--coral-hover), var(--green), var(--green-dark), var(--navy-50); **border**: 1.5px solid var(--border), 1px solid #e2e8f0 [inline], 1px solid #eee [inline], 1px solid var(--border-light), none; **border-color**: var(--coral); **border-left**: 3px solid var(--green)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.stat-card` → background: var(--bg); `.stat-value` → color: var(--navy-800); `.stat-card.success .stat-value` → color: var(--green-dark); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.btn-success` → background: var(--green), color: white; `.btn-success:hover` → background: var(--green-dark); `.balance-subtab-btn.active` → background: var(--coral), color: white.

## Поступления

Источник: `static/crm/crm.html`, `<section id="incomes">`.

**Элементы в исходной разметке:** кнопок 5, полей `input` 2, `select` 1, `textarea` 0, таблиц 1, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Таблицы: классы `table`.

Поля: `(без класса)` × 3.

**Вариантов кнопок по классам/inline: 3** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary` | 1 | Конвертировать выбранное |
| `btn btn-secondary` | 2 | Исключить выбранное; Отсечь историю до даты |
| `btn btn-secondary + inline` | 2 | ← Назад; Вперёд → |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 0.85rem [inline] (1rem = 16px: 13.6px), 0.9rem [inline] (1rem = 16px: 14.4px), 1.05rem [inline] (1rem = 16px: 16.8px), 12px, 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #64748b [inline], var(--navy-700), var(--text), var(--text-sec), white; **background**: var(--bg), var(--coral), var(--coral-hover), var(--navy-100), var(--navy-200), var(--navy-50); **border**: 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.btn-secondary` → background: var(--navy-100), color: var(--navy-700); `.btn-secondary:hover` → background: var(--navy-200).

## Конвертации

Источник: `static/crm/crm.html`, `<section id="conversions">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 0, `select` 0, `textarea` 0, таблиц 1, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Таблицы: классы `table`.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary + inline` | 1 | + Новая пачка |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 12px, 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: var(--text), var(--text-sec), white; **background**: var(--bg), var(--coral), var(--coral-hover), var(--navy-50); **border**: 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover).

## Возмещения

Источник: `static/crm/crm.html`, `<section id="reimbursements">`.

**Элементы в исходной разметке:** кнопок 0, полей `input` 0, `select` 0, `textarea` 0, таблиц 0, `.card` 2, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

**Вариантов кнопок по классам/inline: 0** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| — | 0 | Кнопки создаются JavaScript или отсутствуют |

**Шрифт из применимых CSS/inline правил:** **font-size**: 16px; **font-weight**: 700

**Цвета из применимых CSS/inline правил:** **color**: #666 [inline], var(--text); **background**: var(--bg); **border**: 1px solid var(--border-light)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text).

## Транзакции

Источник: `static/crm/crm.html`, `<section id="transactions">`.

**Элементы в исходной разметке:** кнопок 3, полей `input` 7, `select` 1, `textarea` 0, таблиц 0, `.card` 3, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Поля: `form-control` × 6, `(без класса)` × 2.

**Вариантов кнопок по классам/inline: 2** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary` | 1 | Добавить |
| `btn btn-secondary` | 2 | Проверить; Обновить |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 13px, 14px, 15px, 16px; **font-weight**: 500, 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #666 [inline], var(--navy-600), var(--navy-700), var(--text), white; **background**: var(--bg), var(--coral), var(--coral-hover), var(--navy-100), var(--navy-200); **border**: 1.5px solid var(--border), 1px solid var(--border-light), none; **border-color**: var(--coral)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.btn-secondary` → background: var(--navy-100), color: var(--navy-700); `.btn-secondary:hover` → background: var(--navy-200).

## Менеджеры

Источник: `static/crm/crm.html`, `<section id="managers">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 1, `select` 0, `textarea` 0, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Поля: `form-control` × 1.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary` | 1 | Добавить |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 13px, 14px, 15px, 16px; **font-weight**: 500, 600, 700

**Цвета из применимых CSS/inline правил:** **color**: var(--navy-600), var(--text), white; **background**: var(--bg), var(--coral), var(--coral-hover); **border**: 1.5px solid var(--border), 1px solid var(--border-light), none; **border-color**: var(--coral)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover).

## Сверка

Источник: `static/crm/crm.html`, `<section id="verification">`.

**Элементы в исходной разметке:** кнопок 3, полей `input` 3, `select` 0, `textarea` 0, таблиц 0, `.card` 2, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Поля: `form-control` × 3.

**Вариантов кнопок по классам/inline: 2** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary` | 2 | Загрузить сверку; Сохранить |
| `btn btn-secondary` | 1 | Тест |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 0.9rem [inline] (1rem = 16px: 14.4px), 13px, 14px, 15px, 16px; **font-weight**: 500, 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #666 [inline], var(--navy-600), var(--navy-700), var(--text), white; **background**: var(--bg), var(--coral), var(--coral-hover), var(--navy-100), var(--navy-200); **border**: 1.5px solid var(--border), 1px solid var(--border-light), none; **border-color**: var(--coral)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.btn-secondary` → background: var(--navy-100), color: var(--navy-700); `.btn-secondary:hover` → background: var(--navy-200).

## KYC

Источник: `static/crm/crm.html`, `<section id="kyc">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 0, `select` 0, `textarea` 0, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary + inline` | 1 | + Запросить KYC |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 0.95rem [inline] (1rem = 16px: 15.2px), 0.9rem [inline] (1rem = 16px: 14.4px), 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #666 [inline], #999 [inline], var(--text), white; **background**: var(--bg), var(--coral), var(--coral-hover); **border**: 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover).

## Партнёры

Источник: `static/crm/crm.html`, `<section id="partners">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 0, `select` 0, `textarea` 0, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary + inline` | 1 | + Добавить партнёра |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 0.9rem [inline] (1rem = 16px: 14.4px), 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #999 [inline], var(--text), white; **background**: var(--bg), var(--coral), var(--coral-hover); **border**: 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover).

## Рефереры

Источник: `static/crm/crm.html`, `<section id="referrers">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 4, `select` 1, `textarea` 0, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Поля: `(без класса)` × 5.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary + inline` | 1 | + Добавить реферера |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 0.9rem [inline] (1rem = 16px: 14.4px), 12px [inline], 13px [inline], 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #475569 [inline], #64748b [inline], #999 [inline], var(--text), white; **background**: var(--bg), var(--coral), var(--coral-hover); **border**: 1px solid #e2e8f0 [inline], 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover).

## Заявки на выплату

Источник: `static/crm/crm.html`, `<section id="payoutRequests">`.

**Элементы в исходной разметке:** кнопок 5, полей `input` 0, `select` 0, `textarea` 0, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

**Вариантов кнопок по классам/inline: 2** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-sm btn-light payout-filter-btn` | 4 | Новые; В работе; Выплачено; Отменено |
| `btn btn-sm btn-light payout-filter-btn active` | 1 | Все |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 13px, 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #999 [inline], var(--text); **background**: var(--bg); **border**: 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text).

## Сотрудники

Источник: `static/crm/crm.html`, `<section id="admins">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 4, `select` 1, `textarea` 0, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Поля: `form-control` × 5.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary` | 1 | Добавить |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 13px, 13px [inline], 14px, 15px, 16px; **font-weight**: 500, 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #64748b [inline], #92400e [inline], var(--navy-600), var(--text), white; **background**: #fffbeb [inline], var(--bg), var(--coral), var(--coral-hover); **border**: 1.5px solid var(--border), 1px solid var(--border-light), none; **border-color**: var(--coral)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover).

## Аналитика / дашборд

Источник: `static/crm/crm.html`, `<section id="dashboard">`.

**Элементы в исходной разметке:** кнопок 5, полей `input` 2, `select` 3, `textarea` 0, таблиц 7, `.card` 10, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Таблицы: `#marginsTable`; `#unitEconTable`; `#channelsTable`; классы `—`; классы `—`; классы `—`; классы `—`.

Поля: `period-btn` × 5.

**Вариантов кнопок по классам/inline: 2** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `period-btn` | 4 | Сегодня; Неделя; Всё время; Показать |
| `period-btn active` | 1 | 30 дней |

**Шрифт из применимых CSS/inline правил:** **font-size**: 12px, 12px [inline], 13px, 13px [inline], 14px, 16px, 32px [inline]; **font-weight**: 500, 600, 700, 700 [inline]

**Цвета из применимых CSS/inline правил:** **color**: #22c55e [inline], #333 [inline], #3b82f6 [inline], #666, #666 [inline], #999 [inline], #FF6B35, #fff, var(--text), var(--text-sec); **background**: #FF6B35, #fff, var(--bg), var(--navy-50); **border**: 1px solid #e5e7eb, 1px solid var(--border-light); **border-color**: #FF6B35

Характерные селекторы сумм, статусов, ссылок/кнопок: `.period-btn` → background: #fff, color: #666; `.period-btn.active` → background: #FF6B35, color: #fff; `.period-btn:hover:not(.active)` → color: #FF6B35; `.card` → background: var(--bg); `.card-title` → color: var(--text).

## Создание сделки (общая CRM форма)

Источник: `static/crm/crm.html`, `<section id="create">`.

**Элементы в исходной разметке:** кнопок 21, полей `input` 65, `select` 22, `textarea` 1, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Поля: `form-control` × 80, `(без класса)` × 8.

**Вариантов кнопок по классам/inline: 10** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `(без класса) + inline` | 2 | ＋ Добавить агента |
| `btn btn-primary` | 2 | Добавить; Создать сделку |
| `btn btn-secondary` | 2 | ↻; Рассчитать прибыль |
| `btn btn-secondary + inline` | 3 | + ещё приход; 🎯 Подобрать процент; ➕ Выбрать переводы |
| `btn btn-secondary btn-sm` | 2 | 🔄 |
| `btn btn-secondary btn-sm + inline` | 2 | ＋ Добавить |
| `btn btn-sm btn-primary` | 1 | Добавить отмеченные |
| `btn btn-sm btn-secondary` | 2 | Все; Снять |
| `btn btn-success + inline` | 1 | Создать кастомную сделку |
| `ca-preset` | 4 | ⬇️ Каскадом; 🟰 В долю |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 0.82rem [inline] (1rem = 16px: 13.12px), 0.85rem [inline] (1rem = 16px: 13.6px), 0.88rem [inline] (1rem = 16px: 14.08px), 0.9rem [inline] (1rem = 16px: 14.4px), 1.1rem [inline] (1rem = 16px: 17.6px), 12px, 12px [inline], 13px, 13px [inline], 14px, 15px, 16px; **font-weight**: 400 [inline], 500, 600, 600 [inline], 700, 700 [inline]

**Цвета из применимых CSS/inline правил:** **color**: #0369a1 [inline], #0e7490 [inline], #10b981 [inline], #155e75 [inline], #166534, #166534 [inline], #1e40af [inline], #334155 [inline], #475569 [inline], #5b21b6 [inline], #64748b [inline], #666 [inline], #667eea [inline], #6b7280 [inline], #7c3aed [inline], #92400e [inline], #ef4444 [inline], #f59e0b [inline], var(--navy-600), var(--navy-700), var(--text), white; **background**: #e0f2fe [inline], #ecfeff [inline], #eff6ff [inline], #f0f9ff [inline], #f0fdf4 [inline], #f5f3ff [inline], #f8fafc [inline], #fafafa [inline], #fee2e2 [inline], #fef3c7 [inline], #fffbeb [inline], var(--bg), var(--coral), var(--coral-hover), var(--green), var(--green-dark), var(--navy-100), var(--navy-200), var(--navy-50), white, white [inline]; **border**: 1.5px solid var(--border), 1.5px solid var(--coral), 1px solid #a5f3fc [inline], 1px solid #bae6fd [inline], 1px solid #bbf7d0 [inline], 1px solid #ddd6fe [inline], 1px solid #e2e8f0 [inline], 1px solid #fde68a [inline], 1px solid var(--border-light), 2px dashed #86efac [inline], 2px solid #86efac, none, none [inline]; **border-color**: var(--coral)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover); `.btn-secondary` → background: var(--navy-100), color: var(--navy-700); `.btn-secondary:hover` → background: var(--navy-200); `.btn-success` → background: var(--green), color: white; `.btn-success:hover` → background: var(--green-dark).

## Мой Telegram (служебный раздел)

Источник: `static/crm/crm.html`, `<section id="myTelegram">`.

**Элементы в исходной разметке:** кнопок 1, полей `input` 0, `select` 0, `textarea` 0, таблиц 0, `.card` 1, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

**Вариантов кнопок по классам/inline: 1** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `btn btn-primary` | 1 | Подключить Telegram |

**Шрифт из применимых CSS/inline правил:** **font-family**: inherit; **font-size**: 13px [inline], 14px, 16px; **font-weight**: 600, 700

**Цвета из применимых CSS/inline правил:** **color**: #64748b [inline], var(--text), white; **background**: var(--bg), var(--coral), var(--coral-hover); **border**: 1px solid var(--border-light), none

Характерные селекторы сумм, статусов, ссылок/кнопок: `.card` → background: var(--bg); `.card-title` → color: var(--text); `.btn-primary` → background: var(--coral), color: white; `.btn-primary:hover` → background: var(--coral-hover).

## Калькулятор

Источник: `static/calculator/index.html + styles.css`.

**Элементы в исходной разметке:** кнопок 40, полей `input` 15, `select` 0, `textarea` 0, таблиц 0, `.card` 0, `.stat-card` 0, `.badge` 0, `.pill` 0, `.alert` 0.

Дополнительные блоки: ` .rates-card` × 1, ` .calculator-card` × 1, ` .custom-rate-card` × 2, ` .results-section` × 1, ` .rate-item` × 3.

Поля: `amount-input` × 9, `(без класса)` × 6.

**Вариантов кнопок по классам/inline: 18** (состояние `.active` показано отдельно).

| Классы / стиль | Шт. | Где / подписи |
|---|---:|---|
| `(без класса) + inline` | 2 | ⚡ Binance-парсер недоступен — использовать быстрый курс (~0.2% погрешнос; 📋 Копировать |
| `calculate-btn` | 1 | 🚀 РАССЧИТАТЬ |
| `calculate-btn + inline` | 2 | 💳 СОЗДАТЬ ПЛАТЕЖ; 📊 СОЗДАТЬ СДЕЛКУ В CRM |
| `commission-btn` | 11 | В ฿; Софт-счёт · 1,5% + 50$; 1.5%; 2%; 2.4%; 3%; 3.5%; 4%; 4.5%; 5%; ✏️ Своё |
| `commission-btn active` | 2 | В USD; Банк · 0,8% + 50$ |
| `dealtype-btn` | 3 | 🏠 Фрихолд; 📜 Лизхолд; ✏️ Другое |
| `dealtype-btn active` | 1 | 💱 Обмен |
| `direction-btn` | 1 | 🎯 Хочу получить |
| `direction-btn active` | 1 | 💰 Вношу сумму |
| `method-btn` | 2 | 💼 Брокер; 🎨 Кастом |
| `method-btn active` | 1 | 🏦 СБП |
| `refresh-btn` | 1 | ↻ Обновить |
| `refresh-btn + inline` | 2 | 📋 Копировать |
| `scenario-btn` | 3 | 💸 THB ← RUB; 💵 RUB → USDT; 💎 USDT ← RUB |
| `scenario-btn + inline` | 4 | 💰 RUB → THB; 💎 THB → USDT; 🔄 USDT → THB; 💵 RUB → USDT |
| `scenario-btn active` | 1 | 💰 RUB → THB |
| `src-btn` | 1 | Binance |
| `src-btn active` | 1 | Bitazza |

**Шрифт из применимых CSS/inline правил:** **font-family**: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif, "Inter", sans-serif, inherit; **font-size**: 0.85em [inline], 0.9rem [inline] (1rem = 16px: 14.4px), 10px, 11px, 12px, 12px [inline], 13px, 13px [(max-width: 520px)], 13px [inline], 14px, 14px [(max-width: 640px)], 14px [inline], 15px, 15px [inline], 16px, 16px [inline], 18px [(max-width: 640px)], 20px, 30px [(max-width: 640px)], 32px, 36px, 9px, 9px [(max-width: 640px)]; **font-weight**: 400, 500, 600, 600 [inline], 700, 800

**Цвета из применимых CSS/inline правил:** **color**: #0369a1 [inline], #166534 [inline], #1E40AF, #3730A3 [inline], #4F46E5 [inline], #92400E [inline], #92400e [inline], #C4B5FD, #CBD5E1, #E2E8F0 [inline], rgba(255,255,255,0.7), var(--coral), var(--indigo), var(--navy-800), var(--text), var(--text-muted), var(--text-sec), white, white [inline]; **background**: #10B981 [inline], #1E293B, #1E293B [inline], #4F46E5 [inline], #6366F1 [inline], #EEF2FF [inline], #F0FDF4 [inline], #F97316, #FEF3C7 [inline], #f0f9ff [inline], #fef3c7 [inline], linear-gradient(135deg, #10B981 0%, #059669 100%) [inline], linear-gradient(135deg, #4F46E5 0%, #3730A3 100%) [inline], rgba(139, 92, 246, 0.2), rgba(139, 92, 246, 0.35), rgba(255,255,255,0.08), transparent, var(--bg), var(--bg-page), var(--blue-light), var(--coral), var(--coral-hover), var(--indigo-light), var(--navy-100), var(--navy-300), var(--navy-50), var(--navy-700), var(--navy-800); **border**: 1.5px solid #C7D2FE, 1.5px solid var(--border), 1px solid #334155 [inline], 1px solid #BBF7D0 [inline], 1px solid #C7D2FE, 1px solid #C7D2FE [inline], 1px solid #FCD34D [inline], 1px solid #bae6fd [inline], 1px solid #e2e8f0 [inline], 1px solid #fbbf24 [inline], 1px solid rgba(139, 92, 246, 0.4), 1px solid var(--border-light), 2px solid var(--border), 2px solid var(--indigo), none, none [inline]; **border-color**: #8B5CF6, var(--coral), var(--indigo), var(--navy-700), var(--navy-800)

Характерные селекторы сумм, статусов, ссылок/кнопок: `.top-nav .instruction-btn` → background: rgba(139, 92, 246, 0.2), color: #C4B5FD; `.top-nav .instruction-btn:hover` → background: rgba(139, 92, 246, 0.35), color: white; `.method-btn` → background: var(--bg), color: var(--text-sec); `.method-btn.active` → background: var(--navy-800), color: white; `.custom-rate-card` → background: var(--bg); `.custom-rate-card .input-label` → color: var(--indigo); `.custom-rate-card .amount-input` → color: var(--indigo); `.custom-rate-card .amount-input::placeholder` → color: var(--text-muted); `.rates-card` → background: var(--bg); `.refresh-btn` → background: var(--navy-800), color: white; `.refresh-btn:hover` → background: var(--navy-700); `.rate-item.highlight` → background: var(--navy-800), color: white; `.rate-item.highlight .rate-label` → color: rgba(255,255,255,0.7); `.rate-item.highlight .rate-value` → color: white; `.scenario-btn` → background: var(--bg), color: var(--text-sec); `.scenario-btn.active` → background: var(--navy-800), color: white; `.calculator-card` → background: var(--bg); `.direction-btn` → background: var(--bg), color: var(--text-sec); `.direction-btn.active` → background: var(--navy-800), color: white; `.amount-input` → color: var(--text), background: var(--bg); `.calculate-btn` → background: var(--coral), color: white; `.calculate-btn:hover` → background: var(--coral-hover); `.calculate-btn:disabled` → background: var(--navy-300); `.commission-btn` → background: var(--bg), color: var(--text-sec).

## Динамическая разметка после загрузки данных

Счётчики выше относятся к исходному DOM. Следующие обработчики создают дополнительные карточки, строки, кнопки, бейджи и цвета через `innerHTML`/шаблонные строки; их количество зависит от ответа API. Это отдельные варианты текущего интерфейса, а не измеренные экземпляры конкретного набора данных.

| Раздел | Генератор в `crm.html` | Дополнительные варианты и признаки |
|---|---|---|
| Сделки | `loadDeals` (около 4679), `showDealDetails` (4791) | Строки таблицы, `.badge badge-${status}`, `.btn-sm.btn-secondary`, карточка детали, доход/прибыль `#10b981`, ожидаемая прибыль `#f59e0b`, сумма конвертации `#059669`; есть суммы через `.toFixed(2)` без разделителей. |
| Документы | `loadDocuments` (14756) | Строки пакетов и `.docs-empty`, действия документа появляются после ответа API; файловые статусы оформлены `.docs-status`, `.docs-slot.is-filled`, зелёный `--green-darker` / `--green-light`. |
| Закрытие | `loadBitrixDeals` (9116) | Разбор сделки и кнопки `.btn-primary`, `.btn-success`, `.btn-danger`, `.btn-light`; классы действий появляются по состоянию записи. |
| Обменники | `rxRenderDeals` (2827), `rxRenderBrokers`, `rxRenderRequests` | Четыре таблицы наполняются JS; `.rx-pill`, `.btn-secondary.btn-sm`, `.btn-primary.btn-sm`; маржа `--green-dark`, ожидание `#1E40AF`, ошибки/расходы `#DC2626`/`#92400E`. |
| Баланс | обработчики раздела баланс после строки 13300; исходные `.stat-card`, `.wallet-card`, `.batch-card` | Кошельки/партии/операции после загрузки, старые зелёные суммы `.batch-amount .thb`, `.wallet-card .balance` = `--green-dark`; статусы и кнопки операций зависят от записи. |
| Поступления | `renderIncomes` (11254) | Строки `#incomesTable`, действия конвертации; inline статусы `#94a3b8`, `#b45309`, `#059669` и др. |
| Конвертации | `loadConversions` (11452), `showConversion` (11693) | Строки `#conversionsTable`, детали, действия внутри детали; прямые inline значения цветов. |
| Возмещения | `loadReimbursements` (12004) | Карточки истории и действия `.btn-sm.btn-secondary`, `.btn-success.reimburse-btn`; янтарные заметки `#fef3c7`/`#92400e`. |
| Транзакции | `loadTransactions` (12671) | Карточки переводов, `.badge`, `.btn-sm.btn-danger`, `.btn-sm.btn-success`; зелёные `#f0fdf4`/`#065f46` и красный `#ef4444`. |
| Менеджеры | `loadManagers` (13267) | `.batch-card`, кнопки `.btn-sm` с цветом по активности, `.btn-sm.btn-danger`; зелёный `#10b981`. |
| Сверка | `loadVerificationSummary` (12935) | `.stats-grid`, `.stat-card.success`, крупные `.stat-value`; прямо заданы `#f59e0b`, `#10b981`, `#3b82f6`, `#ef4444`. |
| KYC | `loadKYCSection` (13849) | Списки ожидающих/проверенных, `.btn-primary.btn-sm` и `.btn-sm`, статусы через inline зелёный `#16a34a`/`#f0fdf4`, красный `#dc2626`. |
| Партнёры | `loadPartners` (13914) | Список партнёров и `.btn-sm`, информационный синий `#eff6ff`/`#3b82f6`. |
| Рефереры | `renderReferrers` (14233) | Карточки и `.btn-sm` плюс inline цветные действия: `#7c3aed`, `#0ea5e9`, `#ef4444`, `#22c55e`, `#f97316`; суммы/статусы оформлены отдельно. |
| Заявки на выплату | `loadPayoutRequests` (14080) | Карточки и `.btn-sm.btn-success`, `.btn-sm.btn-light`; синий `#2563EB`, зелёный `#16A34A`, красный `#DC2626`. |
| Сотрудники | `loadAdmins` (5663) | Список и кнопки `.btn-secondary`, `.btn-primary`, предупреждение `#C2410C`/`#FFF7ED`. |
| Аналитика | `loadDashboard` (4098), `loadConversion` (4280), `loadDashReferrers` (4084) | Динамические `.stat-card.success/.warning`, таблицы/графики; доходы `#059669`/`#16a34a`, CR `#22c55e`, столбцы таблиц и плитки имеют цветные суммы. |
| Калькулятор | `calculator.js`: `displayResults`/детали, `formatNumber` (1824) | Результаты и детали создаются JS. `.highlight-final` и `.profit-value` используют `--green-dark`; `formatNumber` вставляет пробелы разрядов, но сохраняет точку копеек (`toFixed(2)`). |

### Сквозные варианты, требующие нормализации на следующем этапе

- Общий `.btn`: 48px, 14px/600; `.btn-primary` = `--coral`, `.btn-secondary` = `--navy-100`, `.btn-success` = `--green`, `.btn-danger` = `--red`, `.btn-info` = `--blue`, `.btn-warning` = `--amber`; есть `.btn-outline`, `.btn-sm` (36px, 13px), `.btn-light` и многочисленные inline цвета. В калькуляторе отдельные `.calculate-btn`, `.refresh-btn`, `.scenario-btn`, `.method-btn`, `.commission-btn`, `.src-btn`.
- Общий `.form-control`: 48px, 15px, рамка `var(--border)` = `#E2E8F0`; рядом есть `.custom-select-btn`, `.rx-inp`, `.amount-input`, `form-input` с иными стилями. `select` и даты не везде используют один класс.
- Общие заголовки `th`: `text-transform: uppercase`, 12px/600. В юнит-экономике отдельно `.ue-group` = uppercase, 11px/600; строки/числа оформляются разными классами. Статусные `.badge-*` имеют семь цветовых вариантов, в Обменниках свой `.rx-pill`.
- Суммы прибыли без факта подтверждения зелёные уже в общем CSS: `.stat-card.success .stat-value`, `.deal-card-mobile .deal-profit`, `.unit-econ-table .ue-val.good`, `.batch-amount .thb`, `.wallet-card .balance`, `.profit-value`, `.detail-value.highlight-final`. В JS те же приёмы повторяются inline в Сделках, Аналитике, Обменниках, Сверке, Реферерах.
- У калькулятора `formatNumber` выдаёт `1 000.00`; у CRM `formatNumber` округляет до целого и ставит группировку. Другие участки CRM используют `ru-RU`, `en-US` и `.toFixed(2)` напрямую; встречаются `$` перед/после пробела и `฿` перед числом. Единого форматтера отображения для всех валют в исходном коде нет.
- Пустые состояния: `.docs-empty`, текстовые `—`/`Нет ...` в шаблонах и нули в `.stat-value`; единый паттерн с полезной ссылкой не найден.

Инвентаризация не является визуальной приёмкой: она фиксирует исходный код и HTML-шаблоны. Снимки, клики, фильтры, сохранение и гейты DESIGN.md выполняются после команды продолжать визуальные правки.
