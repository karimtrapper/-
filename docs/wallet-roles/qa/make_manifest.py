"""Манифест QA-артефактов: sha256, размер, исходный путь и путь внутри репозитория.

  python3 make_manifest.py <исходный_путь>::<путь_в_репозитории> [...]  > final-manifest.json

Для каждой пары хеш исходного файла и копии в репозитории должен совпасть (иначе завершение с ошибкой).
Копии лежат в docs/wallet-roles/qa/artifacts/, поэтому сравнение воспроизводится и после очистки /tmp.
"""
import hashlib
import json
import subprocess
import sys

files = []
for pair in sys.argv[1:]:
    original, repo = pair.split('::')
    a, b = open(original, 'rb').read(), open(repo, 'rb').read()
    if hashlib.sha256(a).hexdigest() != hashlib.sha256(b).hexdigest():
        sys.exit(f'хеш копии не совпал с оригиналом: {original} != {repo}')
    files.append({'original_path': original, 'repo_path': repo, 'bytes': len(a),
                  'sha256': hashlib.sha256(a).hexdigest()})
head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
print(json.dumps({'app_head': head, 'artifacts': files}, ensure_ascii=False, indent=1))
