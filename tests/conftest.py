"""Load the repo root as package 'whiplash' the same way Hermes does."""
import importlib.util
import os
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

# Wall-clock timing bounds (clock jitter, a tempo measured from real send times) depend on the machine. Shared CI
# runners, macOS especially, stall every process for 5-15 ms now and then (main's own runs 43015115037 and
# 43025375026 failed that way). On CI those bounds are reported but don't fail the run; locally, or with
# WHIPLASH_STRICT_TIMING=1, they do. The scheduling guarantees behind them are pinned deterministically on a
# virtual clock (tests/test_v070.py, "virtual clock"), which no runner stall can move.
STRICT_TIMING = os.environ.get("WHIPLASH_STRICT_TIMING") == "1" or not os.environ.get("CI")


@pytest.fixture(autouse=True)
def _default_transport_env(monkeypatch):
    """Tests run with the shipped transport default unless they set WHIPLASH_SEND_TRANSPORT."""
    monkeypatch.delenv("WHIPLASH_SEND_TRANSPORT", raising=False)
