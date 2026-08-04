"""Guards against the failure that broke CI three times in a row.

Every previous CI run died at collection because a module imported a package
that was installed locally but absent from requirements.txt (google.api_core in
brain.py, langchain_anthropic in the old tests/test_setup.py). Nothing caught it
because the failure happened before any test ran.

These tests import every shipped module directly, so a missing dependency fails
as a normal test failure with a readable message.
"""

import importlib

import pytest

# Every module that must import cleanly from a fresh requirements.txt install.
MODULES = ["brain", "execution", "logger", "risk", "telegram_bot", "main"]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None


def test_scripts_import():
    """Helper scripts must not drag undeclared dependencies into the repo."""
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "scripts"))
    assert importlib.import_module("check_connections") is not None


def test_no_stray_test_modules_hit_the_network():
    """tests/ must not contain modules that call live APIs on import.

    scripts/check_connections.py used to live here as tests/test_setup.py and
    posted a real Telegram message every time the suite ran.
    """
    import os
    import pathlib

    tests_dir = pathlib.Path(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for path in tests_dir.glob("test_*.py"):
        src = path.read_text(encoding="utf-8")
        # A module-level load_dotenv() means the file expects real credentials.
        for line in src.splitlines():
            if line.startswith("load_dotenv("):
                offenders.append(path.name)
                break
    assert not offenders, f"tests calling load_dotenv() at module level: {offenders}"
