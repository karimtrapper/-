"""Сравнение регрессионных прогонов с бейзлайном (HEAD 328178f) по именам тестов.

  python3 compare_runs.py <baseline_pytest.xml> <final_pytest.xml> \
      <baseline_js_report.json> <final_js_report.json> [outdir]

Пишет regression-comparison.json и regression-comparison.md: счётчики, новые падения,
решённые падения, судьба 77 пропущенных тестов бейзлайна, пропавшие тесты, новые тесты QA.
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def load_xml(path):
    result = {}
    for tc in ET.parse(path).getroot().iter('testcase'):
        name = tc.get('classname') + '::' + tc.get('name')
        err = tc.find('failure') if tc.find('failure') is not None else tc.find('error')
        if err is not None:
            result[name] = 'failed'
        elif tc.find('skipped') is not None:
            result[name] = 'skipped'
        else:
            result[name] = 'passed'
    return result


def load_js(path):
    return {r['test']: ('failed' if r['exit'] else 'passed')
            for r in json.load(open(path))['results']}


def count(d):
    return {s: sum(v == s for v in d.values()) for s in ('passed', 'failed', 'skipped')} | {'total': len(d)}


def main():
    base_py, fin_py, base_js, fin_js = sys.argv[1:5]
    out = Path(sys.argv[5]) if len(sys.argv) > 5 else Path(__file__).parent
    bp, fp = load_xml(base_py), load_xml(fin_py)
    bj, fj = load_js(base_js), load_js(fin_js)
    qa = lambda n: 'wallet_roles' in n
    old_final = {n: v for n, v in fp.items() if not qa(n)}
    report = {
        'python': {
            'baseline': count(bp), 'final': count(fp), 'final_old_tests_only': count(old_final),
            'new_failing_names': sorted(n for n, v in fp.items() if v == 'failed' and bp.get(n) != 'failed'),
            'resolved_failing_names': sorted(n for n, v in bp.items() if v == 'failed' and fp.get(n) != 'failed'),
            'baseline_tests_missing_in_final': sorted(set(bp) - set(fp)),
            'baseline_skipped_total': sum(v == 'skipped' for v in bp.values()),
            'baseline_skipped_still_skipped': sorted(n for n, v in bp.items() if v == 'skipped' and fp.get(n) == 'skipped'),
            'baseline_skipped_changed': sorted(n for n, v in bp.items() if v == 'skipped' and fp.get(n) != 'skipped'),
            'final_skipped_not_in_baseline_skips': sorted(n for n, v in fp.items() if v == 'skipped' and bp.get(n) != 'skipped'),
            'new_tests_count': len(set(fp) - set(bp)),
            'new_qa_tests_count': sum(qa(n) for n in set(fp) - set(bp)),
            'new_non_qa_tests': sorted(n for n in set(fp) - set(bp) if not qa(n)),
            'new_qa_tests_not_passed': sorted(n for n in set(fp) - set(bp) if qa(n) and fp[n] != 'passed'),
        },
        'js': {
            'baseline': count(bj), 'final': count(fj),
            'baseline_failing': sorted(n for n, v in bj.items() if v == 'failed'),
            'final_failing': sorted(n for n, v in fj.items() if v == 'failed'),
            'new_failing_names': sorted(n for n, v in fj.items() if v == 'failed' and bj.get(n) != 'failed'),
            'resolved_failing_names': sorted(n for n, v in bj.items() if v == 'failed' and fj.get(n) != 'failed'),
            'tests_missing_in_final': sorted(set(bj) - set(fj)),
        },
    }
    p, j = report['python'], report['js']
    report['verdict_regression'] = (not p['new_failing_names'] and not p['baseline_tests_missing_in_final']
                                    and not p['baseline_skipped_changed'] and not p['final_skipped_not_in_baseline_skips']
                                    and not p['new_qa_tests_not_passed']
                                    and not j['new_failing_names'] and not j['tests_missing_in_final'])
    (out / 'regression-comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=1))
    lines = ['# Сравнение с бейзлайном (генерируется compare_runs.py)', '',
             f"Вердикт «ноль новых падений, ничего не пропало, ни одного нового пропуска, пропуски те же»: **{'ДА' if report['verdict_regression'] else 'НЕТ'}**", '',
             '## Python (fenced pytest)', '', f"- бейзлайн: {p['baseline']}", f"- финал: {p['final']}",
             f"- финал, только старые тесты: {p['final_old_tests_only']}",
             f"- новые падения (имена): {p['new_failing_names'] or 'нет'}",
             f"- решённые падения бейзлайна: {p['resolved_failing_names'] or 'нет (в бейзлайне падений не было)'}",
             f"- тесты бейзлайна, отсутствующие в финале: {p['baseline_tests_missing_in_final'] or 'нет'}",
             f"- пропуски бейзлайна: {p['baseline_skipped_total']}; остались пропущенными: {len(p['baseline_skipped_still_skipped'])}; "
             f"изменили статус: {p['baseline_skipped_changed'] or 'нет'}",
             f"- новые пропуски вне списка бейзлайна: {p['final_skipped_not_in_baseline_skips'] or 'нет'}",
             f"- новых тестов: {p['new_tests_count']} (QA: {p['new_qa_tests_count']}; не QA: {p['new_non_qa_tests'] or 'нет'})",
             f"- новые QA-тесты не в статусе passed: {p['new_qa_tests_not_passed'] or 'нет'}", '',
             '## JS (fenced node)', '', f"- бейзлайн: {j['baseline']}", f"- финал: {j['final']}",
             f"- падали в бейзлайне: {j['baseline_failing']}", f"- падают в финале: {j['final_failing']}",
             f"- новые падения: {j['new_failing_names'] or 'нет'}", f"- решённые: {j['resolved_failing_names'] or 'нет'}",
             f"- файлы бейзлайна, не запущенные в финале: {j['tests_missing_in_final'] or 'нет'}"]
    (out / 'regression-comparison.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 0 if report['verdict_regression'] else 1


if __name__ == '__main__':
    sys.exit(main())
