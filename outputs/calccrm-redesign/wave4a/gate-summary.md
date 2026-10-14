# Волна 4a — итог design-gate

Роль: Карим. Каждый `check` выполнен на 375, 768, 1280 и 1920px. 1 — токены, 2 — гардрейлы, 3 — контраст WCAG AA, 4 — ширины, 5 — текст, 6 — снимки «до/после».

| Экран | 1 | 2 | 3 | 4 | 5 | 6 | Итог | Отчёт |
|---|---|---|---|---|---|---|---|---|
| Калькулятор — форма | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-calculator/check-after.md) |
| Калькулятор — результат | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-calculator-result/check-after.md) |
| Сделки | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-deals/check-after.md) |
| Документы | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-documents/check-after.md) |
| Закрытие | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-closing/check-after.md) |
| Обменники | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-exchangers/check-after.md) |
| Баланс | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-balance/check-after.md) |
| Поступления | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-incomes/check-after.md) |
| Конвертации | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-conversions/check-after.md) |
| Возмещения | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-reimbursements/check-after.md) |
| Транзакции | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-transactions/check-after.md) |
| Менеджеры | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-managers/check-after.md) |
| Сверка | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-verification/check-after.md) |
| KYC | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-kyc/check-after.md) |
| Партнёры | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-partners/check-after.md) |
| Рефереры | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-referrers/check-after.md) |
| Заявки на выплату | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-payoutRequests/check-after.md) |
| Сотрудники | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-admins/check-after.md) |
| Аналитика CRM | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-dashboard/check-after.md) |
| Создание сделки | PASS | PASS | PASS | PASS | PASS | PASS | **PASS** | [MD](machine-crm-create/check-after.md) |

## Ключевые пары снимков

| Экран | 375 до / после | 1280 до / после |
|---|---|---|
| Калькулятор — результат | [до](machine-calculator-result/before-karim-375.png) / [после](machine-calculator-result/after-karim-375.png) | [до](machine-calculator-result/before-karim-1280.png) / [после](machine-calculator-result/after-karim-1280.png) |
| Сделки | [до](machine-crm-deals/before-karim-375.png) / [после](machine-crm-deals/after-karim-375.png) | [до](machine-crm-deals/before-karim-1280.png) / [после](machine-crm-deals/after-karim-1280.png) |
| Документы | [до](machine-crm-documents/before-karim-375.png) / [после](machine-crm-documents/after-karim-375.png) | [до](machine-crm-documents/before-karim-1280.png) / [после](machine-crm-documents/after-karim-1280.png) |
| Аналитика CRM | [до](machine-crm-dashboard/before-karim-375.png) / [после](machine-crm-dashboard/after-karim-375.png) | [до](machine-crm-dashboard/before-karim-1280.png) / [после](machine-crm-dashboard/after-karim-1280.png) |
| Обменники | [до](machine-crm-exchangers/before-karim-375.png) / [после](machine-crm-exchangers/after-karim-375.png) | [до](machine-crm-exchangers/before-karim-1280.png) / [после](machine-crm-exchangers/after-karim-1280.png) |

На снимках «Сделок» сохранена одна и та же тестовая запись `#2`: исходно `$140242.69` и зелёная `$1000.00`, после — `140 242,69 USDT` и нейтральная `$1 000,00`; заголовки таблицы в обычном регистре. На «Аналитике» графики используют navy-палитру, суммы и заголовки таблиц приведены к общему стилю. В рассчитанном состоянии калькулятора одна главная кнопка, карточка результата белая и контрастная.

После исправления селектора у «Документов» кнопка «Новый договор» окрашена в `#C2410C`; повторный `check` показал ровно одну главную кнопку на 375, 768, 1280 и 1920px.

Автоматический PASS не отменяет ручных оговорок по данным стенда и существующему поведению редактора: см. [ручной QA](manual-qa.md).
