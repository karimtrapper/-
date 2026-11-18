"""Run the functional manager document-review UI regression in the fenced suite."""
from pathlib import Path
import subprocess


def test_s27_document_review_navigation():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(['node', str(root / 'tests/test_stand_s27_document_review.js')],
                   cwd=root, check=True, capture_output=True, text=True, timeout=30)
