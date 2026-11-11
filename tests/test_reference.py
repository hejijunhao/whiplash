"""docs/digitakt-ii/reference.md is the device reference agents read; keep it and ccmap in step."""
import re
from pathlib import Path

from whiplash import ccmap
from test_whiplash import make_engine

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "docs" / "digitakt-ii" / "reference.md"
ROW = re.compile(r"^\| `(\w+)` \| (\w+) \| (\d+) \| (\d*) ?\| (\d+)-(\d+) \| (\d*) ?\|$")


def _glance_table():
    text = REFERENCE.read_text()
    section = text.split("### 8.0 ", 1)[1].split("\n### ", 1)[0]
    rows = {}
    for line in section.splitlines():
        m = ROW.match(line.strip())
        if m:
            name, group, cc, lsb, lo, hi, centre = m.groups()
            rows[name] = (group, int(cc), int(lsb) if lsb else None, int(lo), int(hi), bool(centre))
    return rows


def test_reference_named_param_table_matches_ccmap():
    expected = {p.name: (p.group, p.cc, p.lsb_cc, p.min, p.max, p.centered) for p in ccmap._TABLE}
    assert _glance_table() == expected


def test_loop_pos_is_0_120_like_start_and_length():
    # midi.guide: Oneshot Loop Pos CC 22, 0-120 (same scale as Start/Length); see reference.md §4.1, §15.1 #5.
    p = ccmap.PARAMS["loop_pos"]
    assert (p.cc, p.min, p.max) == (22, 0, 120)
    assert ccmap.PARAMS["sample_start"].max == ccmap.PARAMS["sample_length"].max == p.max


def test_loop_pos_clamps_at_120_on_the_wire():
    eng, port = make_engine()
    try:
        eng.ensure_port()
        out = eng.set_param(1, 127, param="loop_pos")
        assert out["value"] == 120 and out.get("clamped") is True
        msg = [m for m in port.messages if m.type == "control_change"][-1]
        assert (msg.channel, msg.control, msg.value) == (0, 22, 120)
    finally:
        eng.shutdown()


def test_lfo3_speed_documents_its_nrpn():
    # Manual Appendix B.8 (p. 111) and midi.guide agree on 1:58. Documentation only, never sent.
    assert ccmap.PARAMS["lfo3_speed"].nrpn == (1, 58)


def test_safety_blocks_unchanged():
    # reference.md §15.2: these stay blocked. Relaxing any of them needs an explicit decision.
    assert {0, 32, 24, 6, 38, 98, 99, 100, 101} <= ccmap.BLOCKED_CCS
    assert {(1, 3), (1, 8), (1, 9)} <= ccmap.BLOCKED_NRPNS


def test_claude_md_and_readme_point_at_the_reference():
    for doc in ("CLAUDE.md", "README.md"):
        assert "docs/digitakt-ii/reference.md" in (ROOT / doc).read_text(), doc
