# Как воспроизвести QA-прогоны (только официальные фенс-раннеры)

Python 3.11 с pytest 9.0.2 (в этой работе `/tmp/s27-venv311/bin/python`), macOS с `sandbox-exec`, из корня репозитория.
Прямой `pytest`/`node` для приёмки не годятся (см. docs/test-network-fence.md).

```sh
PY=/tmp/s27-venv311/bin/python
# 1. Полный Python (бейзлайн на 328178f и финал: те же аргументы)
$PY scripts/run_fenced_pytest.py -q --disable-warnings --tb=short -p no:cacheprovider --junitxml=<out>/pytest.xml
# 2. Полный JS (Node ≥25, Playwright 1.59.1/Chromium 1217)
NODE_PATH="<путь к node_modules>" PLAYWRIGHT_BROWSERS_PATH=~/Library/Caches/ms-playwright $PY scripts/run_fenced_js.py
# 3. Сравнение имён с бейзлайном (пишет regression-comparison.md/json рядом).
#    Работает из чекаута без /tmp: сохранённые артефакты лежат в docs/wallet-roles/qa/artifacts/
A=docs/wallet-roles/qa/artifacts
python3 docs/wallet-roles/qa/compare_runs.py $A/baseline-pytest.xml $A/final-pytest.xml $A/fence-js-baseline.json $A/fence-js-final.json
# 4. Мутации на временных копиях (каталог результатов должен существовать)
mkdir -p <outdir> && $PY docs/wallet-roles/qa/mutation/run_mutations.py "$PWD" <outdir>
# 5. Манифест артефактов: пары <исходный_путь>::<путь_в_репозитории>, хеши копий сверяются с оригиналами
python3 docs/wallet-roles/qa/make_manifest.py <orig>::$A/<copy> ... > docs/wallet-roles/qa/final-manifest.json
```

Критерии приёмки: `NETWORK_FENCE unexpected=0` для каждого Python-прогона; для JS — только ОС-барьер (журнала попыток нет);
`compare_runs.py` печатает вердикт «ДА»; мутации — каждый мутант убит ожидаемым свидетелем при чистом фенсе либо отнесён
в отчёте к избыточным защитам с доказательством.
