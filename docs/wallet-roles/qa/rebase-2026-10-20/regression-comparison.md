# Сравнение с бейзлайном (генерируется compare_runs.py)

Вердикт «ноль новых падений, ничего не пропало, ни одного нового пропуска, пропуски те же»: **ДА**

## Python (fenced pytest)

- бейзлайн: {'passed': 2899, 'failed': 0, 'skipped': 77, 'total': 2976}
- финал: {'passed': 3235, 'failed': 0, 'skipped': 77, 'total': 3312}
- финал, только старые тесты: {'passed': 2899, 'failed': 0, 'skipped': 77, 'total': 2976}
- новые падения (имена): нет
- решённые падения бейзлайна: нет (в бейзлайне падений не было)
- тесты бейзлайна, отсутствующие в финале: нет
- пропуски бейзлайна: 77; остались пропущенными: 77; изменили статус: нет
- новые пропуски вне списка бейзлайна: нет
- новых тестов: 336 (QA: 336; не QA: нет)
- новые QA-тесты не в статусе passed: нет

## JS (fenced node)

- бейзлайн: {'passed': 66, 'failed': 5, 'skipped': 0, 'total': 71}
- финал: {'passed': 66, 'failed': 5, 'skipped': 0, 'total': 71}
- падали в бейзлайне: ['test_stand_crm_labels.js', 'test_stand_hash_split.js', 'test_stand_mobile_tasks_nav.js', 'test_stand_owner_summary.js', 'test_t34_wallet_cards_dropdown.js']
- падают в финале: ['test_stand_crm_labels.js', 'test_stand_hash_split.js', 'test_stand_mobile_tasks_nav.js', 'test_stand_owner_summary.js', 'test_t34_wallet_cards_dropdown.js']
- новые падения: нет
- решённые: нет
- файлы бейзлайна, не запущенные в финале: нет
