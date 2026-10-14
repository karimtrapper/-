# Волна 4a — итог design-gate

Роль: Карим. Все снимки «после» сделаны на локально восстановленном дампе `stand_prodcopy_20260928-before-hotfix4-20261014-1909.sql.gz`; снимки «до» — на отдельной локальной копии того же дампа и исходном `origin/stage`. В копии 25 рефереров, 496 сделок, 192 возмещения, 13 договоров. Живая база не использовалась. Каждый итоговый `check` выполнен на 375, 768, 1280 и 1920px. 1 — токены, 2 — гардрейлы, 3 — контраст WCAG AA, 4 — ширины, 5 — текст, 6 — снимки «до/после».

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
| Возмещения | [до](machine-crm-reimbursements/before-karim-375.png) / [после](machine-crm-reimbursements/after-karim-375.png) | [до](machine-crm-reimbursements/before-karim-1280.png) / [после](machine-crm-reimbursements/after-karim-1280.png) |
| Рефереры | [до](machine-crm-referrers/before-karim-375.png) / [после](machine-crm-referrers/after-karim-375.png) | [до](machine-crm-referrers/before-karim-1280.png) / [после](machine-crm-referrers/after-karim-1280.png) |
| Аналитика CRM | [до](machine-crm-dashboard/before-karim-375.png) / [после](machine-crm-dashboard/after-karim-375.png) | [до](machine-crm-dashboard/before-karim-1280.png) / [после](machine-crm-dashboard/after-karim-1280.png) |
| Обменники | [до](machine-crm-exchangers/before-karim-375.png) / [после](machine-crm-exchangers/after-karim-375.png) | [до](machine-crm-exchangers/before-karim-1280.png) / [после](machine-crm-exchangers/after-karim-1280.png) |

Дополнительно: [карточка реферера с реальными суммами и раскрытым меню «⋯» — 375px](real-data-focus/referrers-menu-karim-375.png), [1280px](real-data-focus/referrers-menu-karim-1280.png); [денежные колонки Сделок на 375px](real-data-focus/deals-money-karim-375.png); [строки Возмещений на 375px](real-data-focus/reimbursements-list-karim-375.png). Заголовок раздела измерен как 22px/700; у неактивных ссылок appbar прозрачная нижняя граница и радиус 0, белые «хвосты» исчезли. В сделках полночь у даты без значимого времени больше не показывается как `00:00`. В результате калькулятора на копии дампа показаны `100 000,00 ₽ → 36 578,55 ฿`.

У «Документов» кнопка «Новый договор» окрашена в `#C2410C`; итоговый `check` на загруженных договорах показал ровно одну главную кнопку на всех четырёх ширинах. История возмещений проверена со всеми 192 записями, а не с состоянием «Загрузка».

После ребейза на `origin/stage@d37993c` все 20 экранов повторно получили PASS по гейтам 1–6 на 375, 768, 1280 и 1920px. Снимки «после» обновлены на локальной копии реальных данных. Во второй панели разделов «Задачника» больше нет; переход в него остался только в глобальной навигации. Подробности — [проверка после ребейза](post-rebase-qa.md). Автоматический PASS не отменяет ручных оговорок по поведению редактора и внешним интеграциям стенда: см. [ручной QA](manual-qa.md).
