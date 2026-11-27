# Сравнение с бейзлайном (генерируется compare_runs.py)

Вердикт «ноль новых падений, ничего не пропало, ни одного нового пропуска, пропуски те же»: **ДА**

## Python (fenced pytest)

- бейзлайн: {'passed': 2813, 'failed': 0, 'skipped': 77, 'total': 2890}
- финал: {'passed': 3133, 'failed': 0, 'skipped': 77, 'total': 3210}
- финал, только старые тесты: {'passed': 2813, 'failed': 0, 'skipped': 77, 'total': 2890}
- новые падения (имена): нет
- решённые падения бейзлайна: нет (в бейзлайне падений не было)
- тесты бейзлайна, отсутствующие в финале: нет
- пропуски бейзлайна: 77; остались пропущенными: 77; изменили статус: нет
- новые пропуски вне списка бейзлайна: нет
- новых тестов: 320 (QA: 320; не QA: нет)
- новые QA-тесты не в статусе passed: нет

## JS (fenced node)

- бейзлайн: {'passed': 55, 'failed': 6, 'skipped': 0, 'total': 61}
- финал: {'passed': 55, 'failed': 6, 'skipped': 0, 'total': 61}
- падали в бейзлайне: ['test_stand_crm_close_race.js', 'test_stand_crm_labels.js', 'test_stand_hash_split.js', 'test_stand_mobile_tasks_nav.js', 'test_stand_owner_summary.js', 'test_t34_wallet_cards_dropdown.js']
- падают в финале: ['test_stand_crm_close_race.js', 'test_stand_crm_labels.js', 'test_stand_hash_split.js', 'test_stand_mobile_tasks_nav.js', 'test_stand_owner_summary.js', 'test_t34_wallet_cards_dropdown.js']
- новые падения: нет
- решённые: нет
- файлы бейзлайна, не запущенные в финале: нет
