"""Opt-in runner: python scripts/run_fenced_pytest.py -q tests/check_stand_javascript.py.

Browser-only mobile navigation runs separately with mocked APIs; Chrome needs
macOS process privileges unavailable inside the native network fence.
"""
import subprocess
from pathlib import Path
import pytest

@pytest.mark.parametrize('script', sorted(Path('tests').glob('test_*.js')))
def test_javascript(script):
    if script.name == 'test_stand_mobile_tasks_nav.js':
        pytest.skip('Run separately in Chrome with mocked API and external requests blocked')
    result = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
