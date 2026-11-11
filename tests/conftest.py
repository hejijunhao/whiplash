"""Load the repo root as package 'whiplash' the same way Hermes does."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    if "whiplash" in sys.modules:
        return sys.modules["whiplash"]
    spec = importlib.util.spec_from_file_location("whiplash", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["whiplash"] = mod
    spec.loader.exec_module(mod)
    return mod


_load()


@pytest.fixture(autouse=True)
def _default_transport_env(monkeypatch):
    """Tests run with the shipped transport default unless they set WHIPLASH_SEND_TRANSPORT."""
    monkeypatch.delenv("WHIPLASH_SEND_TRANSPORT", raising=False)
