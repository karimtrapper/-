"""Собирает INDEX.md из shots/run.json и JSON каждого кадра: экран x роль x ширина, ссылки и флаги.

Запуск (локально, без сети): python3 docs/wallet-roles/ui/build_index.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
SHOTS = HERE / 'shots'


def main():
    run = json.loads((SHOTS / 'run.json').read_text())
    rows = []
    for shot in run['shots']:
        stem = shot['file'][:-4]
        meta = json.loads((SHOTS / f'{stem}.json').read_text())
        flags = []
        if meta.get('hScroll'):
            flags.append('H-SCROLL')
        if meta.get('layoutViewportExpanded'):
            flags.append(f"VIEWPORT {meta['innerWidth']}≠{meta['expectedWidth']}")
        if meta.get('addrClipped'):
            flags.append('ADDR-CLIPPED')
        if meta.get('mfstrAddresses'):
            flags.append('MFSTR-ADDR')
        if meta.get('emoji'):
            flags.append('EMOJI')
        if (meta.get('toast') or {}).get('text'):
            flags.append('TOAST: ' + meta['toast']['text'][:40])
        rows.append((shot['name'], shot['role'], shot['width'], shot['file'],
                     meta.get('capture', {}).get('firstScreenFile'), ', '.join(flags) or '—'))
    lines = ['# Индекс снимков (автогенерация)', '',
             f"HEAD {run.get('source_freeze', {}).get('head', '?')} · чистое дерево: "
             f"{run.get('source_freeze', {}).get('clean')}", '',
             '| Экран | Роль | Ширина | Кадр целиком | Первый экран | Флаги |', '|---|---|---|---|---|---|']
    for name, role, width, file, first, flags in sorted(rows):
        first_link = f'[первый экран](shots/{first})' if first else '—'
        lines.append(f'| {name} | {role} | {width} | [png](shots/{file}) | {first_link} | {flags} |')
    (HERE / 'INDEX.md').write_text('\n'.join(lines) + '\n')
    print(f'INDEX.md: {len(rows)} кадров')


if __name__ == '__main__':
    main()
