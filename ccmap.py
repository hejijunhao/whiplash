"""Digitakt II per-track parameter map.

Source of truth: Elektron Digitakt II User Manual, Appendix B: MIDI (OS 1.15A, pp. 109-113;
the OS 1.17 manual keeps the same values), cross-checked with midi.guide/d/elektron/digitakt-ii.
Every CC number below agrees between the two sources. Named params are sent on the track's own
MIDI channel as 7-bit CC only.

Why no NRPN for named params: several NRPN addresses disagree between the two sources
(manual vs midi.guide: mute 1:101 vs 1:108, track level 1:100 vs 1:110, filter env depth
1:23 vs 1:26 (1:23 is also env delay in midi.guide), filter base 1:51 vs 1:24, width 1:52 vs 1:25).
The `nrpn` field is documentation only (midi.guide addresses); Whiplash never sends it.
Raw NRPN stays available on whiplash_set_param for anyone who has checked their unit.

Sample select (v0.4). Only the sample SLOT is exposed, as the named param `sample_slot`:
- Manual, Appendix B, B.3 SOURCE PARAMETERS (p. 109): "Sample Slot Select" CC 19, NRPN 1:8, and
  "Sample Bank Select" CC 24, NRPN 1:9; repeated in B.9 MISC PARAMETERS (p. 113) as "Sample Slot"
  19 / 1:8 and "Sample Bank" 24 / 1:9. No CC LSB is listed for either (7-bit, not high-res; the
  high-res list in B.8 names only the LFO speed/depth params). The manual gives no value range.
- midi.guide (updated Oct 12 2026), Source section: Sample Slot Select CC 19 [0-127], NRPN 1:8
  [0-16256] (data MSB only); Sample Bank Select CC 24 [0-7], NRPN 1:9 [0-896]; "Sample" NRPN 1:3
  [0-1023] = bank x 128 + slot (A0 = 0 .. H127 = 1023), with the note that turning SMP sends only
  the slot in the selected bank.
- The project pool holds up to 1016 sample slots (manual 5.2.6, p. 17); the SMP list's first
  entry is OFF, which plays no sample (Appendix A.2, p. 94). Neither source says whether CC 19
  value 0 is OFF or the first sample: that needs checking on the unit.
CC 19 agrees in both sources, so `sample_slot` sends CC 19 (7-bit, 0-127) on the track's channel:
a slot within the RAM bank currently selected on the unit. It only picks among samples already
loaded into the project; it can't list, preview or load anything. Raw cc=19 stays refused so the
one path is the validated named param. Sample BANK select (CC 24, NRPN 1:9) and the absolute
"sample" NRPN 1:3 (midi.guide only, absent from the manual) stay blocked, as do NRPN 1:8 raw.
Machine type (Oneshot/Werp/Stretch/...): neither source lists a CC or NRPN for it (it is only
reached via the MACHINE menu, [FUNC] + [SRC], Appendix A.1), so Whiplash can't switch machines.
Amp hold (v0.5.2): CC 80 values 0-126 are hold times, but 127 switches HOLD to NOTE, so `amp_hold`
has range 0-126: clamping and ramps (raw cc 80 ramps too) never reach 127. set_param sends 127 only
for an explicit value 'note' or exactly 127, and labels the result "HOLD = NOTE".
Amp mode (v0.5): manual B.5 AMP PARAMETERS (p. 110) "Mode" CC 87, NRPN 1:40; midi.guide "Amp: Mode 87
[0-1] 0: AHD; 1: ADSR". Manual 11.7 AMP PAGE (p. 56): in AHD a fixed HOLD (0-126) ignores Note Off, and
HOLD = NOTE follows Note On/Off; midi.guide gives amp hold CC 80 value 127 = Note. So a MIDI note length
only shortens a sound in ADSR mode, or in AHD with HOLD = NOTE.
FX-channel and global parameters (delay time, reverb decay, ...) live on the FX channel and are
out of scope for named params; raw cc can still reach them.

Full device reference (data model, machines, note mapping, channels, the whole CC/NRPN map with
every manual vs midi.guide discrepancy): docs/digitakt-ii/reference.md. Check it before changing
anything here.
"""
import difflib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Param:
    name: str
    cc: int
    group: str
    description: str
    min: int = 0
    max: int = 127
    default: int = None  # only where the manual states one (centred params: 64)
    centered: bool = False
    lsb_cc: int = None  # high-res params: CC carrying the low 7 bits (Whiplash sends MSB only)
    discrete: bool = False  # switch-like: out-of-range values are rejected, never clamped or ramped
    aliases: tuple = field(default_factory=tuple)
    nrpn: tuple = None  # documentation only, see module docstring

    def summary(self):
        out = {"name": self.name, "cc": self.cc, "range": [self.min, self.max], "centered": self.centered,
               "description": self.description}
        if self.default is not None:
            out["default"] = self.default
        if self.aliases:
            out["aliases"] = list(self.aliases)
        if self.discrete:
            out["discrete"] = True
        return out


def _c(name, cc, group, description, **kw):
    if kw.get("centered"):
        kw.setdefault("default", 64)
    return Param(name, cc, group, description, **kw)


_TABLE = (
    # track
    _c("mute", 94, "track", "Unit's own track mute: 1 = muted, 0 = unmuted", max=1, default=0, discrete=True,
       nrpn=(1, 108)),
    _c("track_level", 95, "track", "Track level (post-FX fader)", aliases=("level",), nrpn=(1, 110)),
    # source (SRC page)
    _c("tune", 16, "src", "Sample pitch in semitones; 64 = original pitch, 4-124 = -60..+60",
       min=4, max=124, centered=True, nrpn=(1, 0)),
    _c("play_mode", 17, "src", "0 reverse, 1 reverse loop, 2 forward loop, 3 forward", max=3, discrete=True,
       nrpn=(1, 1)),
    _c("sample_start", 20, "src", "SRC knob E: sample start on Oneshot/Repitch/Stretch (0-120); "
       "other machines map this knob to something else (machine dependent)", max=120, aliases=("start",),
       nrpn=(1, 4)),
    _c("sample_length", 21, "src", "SRC knob F: sample length on Oneshot/Repitch/Stretch (0-120); "
       "machine dependent", max=120, aliases=("length",), nrpn=(1, 5)),
    _c("loop_pos", 22, "src", "SRC knob G: loop position on Oneshot (0-120); Bars on Werp/Stretch/Repitch, "
       "slice grid on Grid (machine dependent)", max=120, aliases=("loop_position",), nrpn=(1, 6)),
    _c("sample_slot", 19, "src", "Sample slot (0-127) within the RAM bank selected on the unit; picks a sample "
       "already loaded in the project pool. Can't list, preview or load samples; the SMP list starts with "
       "OFF (no sound)", discrete=True, aliases=("sample", "sample_select", "smp", "slot"), nrpn=(1, 8)),
    _c("sample_level", 23, "src", "Sample level into the filter", nrpn=(1, 7)),
    # filter
    _c("filter_freq", 74, "filter", "Filter cutoff frequency", aliases=("filter_cutoff", "cutoff", "filter"),
       nrpn=(1, 20)),
    _c("filter_reso", 75, "filter", "Filter knob F: resonance on Multi-Mode/LP4/Legacy, feedback on Comb, "
       "gain on EQ (machine dependent)", aliases=("filter_resonance", "resonance", "reso"), nrpn=(1, 21)),
    _c("filter_env_depth", 77, "filter", "Filter envelope depth; 64 = none, below 64 inverts",
       centered=True, aliases=("env_depth",), nrpn=(1, 26)),
    _c("filter_attack", 70, "filter", "Filter envelope attack", nrpn=(1, 16)),
    _c("filter_decay", 71, "filter", "Filter envelope decay", nrpn=(1, 17)),
    _c("filter_sustain", 72, "filter", "Filter envelope sustain", nrpn=(1, 18)),
    _c("filter_release", 73, "filter", "Filter envelope release", nrpn=(1, 19)),
    _c("filter_env_delay", 91, "filter", "Filter envelope delay", nrpn=(1, 23)),
    _c("filter_key_tracking", 92, "filter", "Filter key tracking (0-100)", max=100,
       aliases=("key_tracking",), nrpn=(1, 69)),
    # amp
    _c("amp_attack", 79, "amp", "Amp envelope attack", aliases=("attack",), nrpn=(1, 30)),
    _c("amp_hold", 80, "amp", "Amp envelope hold (AHD mode): 0-126 fixed hold that ignores note-off. Clamps and "
       "ramps stay in 0-126. 127 = NOTE (the midi.guide default, hold until note-off) is a mode switch: only sent "
       "for an explicit value 'note' or exactly 127, and the result says HOLD = NOTE", max=126, aliases=("hold",),
       nrpn=(1, 31)),
    _c("amp_decay", 81, "amp", "Amp envelope decay: how long each hit rings", aliases=("decay",), nrpn=(1, 32)),
    _c("amp_sustain", 82, "amp", "Amp envelope sustain", aliases=("sustain",), nrpn=(1, 33)),
    _c("amp_release", 83, "amp", "Amp envelope release", aliases=("release",), nrpn=(1, 34)),
    _c("amp_mode", 87, "amp", "Amp envelope mode: 0 = AHD, 1 = ADSR. Note length (note-off) only shortens a sound "
       "in ADSR, or in AHD with amp_hold 127 (NOTE)", max=1, discrete=True, aliases=("envelope_mode",),
       nrpn=(1, 40)),
    _c("amp_volume", 89, "amp", "Amp volume (pre-FX)", aliases=("volume",), nrpn=(1, 39)),
    _c("pan", 90, "amp", "Stereo pan; 64 = centre, 0 = hard left, 127 = hard right", centered=True,
       nrpn=(1, 38)),
    # fx (per-track sends and insert FX)
    _c("delay_send", 84, "fx", "Send to the delay", aliases=("delay",), nrpn=(1, 36)),
    _c("reverb_send", 85, "fx", "Send to the reverb", aliases=("reverb",), nrpn=(1, 37)),
    _c("chorus_send", 12, "fx", "Send to the chorus", aliases=("chorus",), nrpn=(1, 35)),
    _c("overdrive", 57, "fx", "Track overdrive", aliases=("drive",), nrpn=(1, 14)),
    _c("bit_reduction", 54, "fx", "Bit reduction (bitcrush)", aliases=("bitcrush", "bit_crush"), nrpn=(1, 11)),
    _c("sample_rate_reduction", 55, "fx", "Sample-rate reduction", aliases=("srr",), nrpn=(1, 12)),
    # lfo (high-res, centred: 64 = 0)
    _c("lfo1_speed", 102, "lfo", "LFO 1 speed; 64 = stopped, below runs backwards", centered=True, lsb_cc=58,
       nrpn=(1, 42)),
    _c("lfo1_depth", 109, "lfo", "LFO 1 depth; 64 = none, below inverts", centered=True, lsb_cc=59,
       nrpn=(1, 49)),
    _c("lfo2_speed", 112, "lfo", "LFO 2 speed; 64 = stopped", centered=True, lsb_cc=60, nrpn=(1, 50)),
    _c("lfo2_depth", 119, "lfo", "LFO 2 depth; 64 = none", centered=True, lsb_cc=61, nrpn=(1, 57)),
    _c("lfo3_speed", 78, "lfo", "LFO 3 speed; 64 = stopped", centered=True, lsb_cc=62, nrpn=(1, 58)),
    _c("lfo3_depth", 86, "lfo", "LFO 3 depth; 64 = none", centered=True, lsb_cc=63, nrpn=(1, 72)),
)

GROUPS = ("track", "src", "filter", "amp", "fx", "lfo")
PARAMS = {p.name: p for p in _TABLE}
ALIASES = {alias: p.name for p in _TABLE for alias in p.aliases}
BY_CC = {p.cc: p for p in _TABLE}
MUTE_CC = PARAMS["mute"].cc

# CCs that must never be sent: bank select 0/32, sample bank select 24, and the NRPN/data-entry
# controllers (sent only by the NRPN helper).
BLOCKED_CCS = {0, 32, 24, 6, 38, 98, 99, 100, 101}
# Sent only through the named param (validated, documented), never as raw cc.
NAMED_ONLY_CCS = {19: "sample_slot"}
BLOCKED_NRPNS = {(1, 3), (1, 8), (1, 9)}  # sample, sample slot, sample bank


def normalize(name):
    return str(name).strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def lookup(name):
    """Resolve a friendly name or alias to a Param. Raises ValueError with close matches."""
    key = normalize(name)
    key = ALIASES.get(key, key)
    if key in PARAMS:
        return PARAMS[key]
    close = difflib.get_close_matches(key, list(PARAMS) + list(ALIASES), n=4, cutoff=0.5)
    close = list(dict.fromkeys(ALIASES.get(c, c) for c in close))
    hint = f"did you mean {', '.join(close)}? " if close else ""
    raise ValueError(f"unknown param {name!r}; {hint}whiplash_list_params lists them all")


def table():
    """The map grouped for whiplash_list_params."""
    return {group: [p.summary() for p in _TABLE if p.group == group] for group in GROUPS}
