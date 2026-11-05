"""Digitakt II per-track parameter map (CC / NRPN), from midi.guide/d/elektron/digitakt-ii.

Sent on the track's own MIDI channel. Only performance parameters are listed.
Sample/bank select (CC 19/24, NRPN 1:3, 1:8, 1:9) is deliberately excluded so
Whiplash can never reassign samples.
"""

# friendly name -> (cc, (nrpn_msb, nrpn_lsb), max_value)
PARAMS = {
    "mute": (94, (1, 108), 1),
    "level": (95, (1, 110), 127),
    "volume": (89, (1, 39), 127),
    "pan": (90, (1, 38), 127),
    "tune": (16, (1, 0), 127),
    "sample_level": (23, (1, 7), 127),
    "filter_cutoff": (74, (1, 20), 127),
    "cutoff": (74, (1, 20), 127),
    "filter_resonance": (75, (1, 21), 127),
    "resonance": (75, (1, 21), 127),
    "filter_env_depth": (77, (1, 26), 127),
    "filter_attack": (70, (1, 16), 127),
    "filter_decay": (71, (1, 17), 127),
    "amp_attack": (79, (1, 30), 127),
    "amp_hold": (80, (1, 31), 127),
    "decay": (81, (1, 32), 127),
    "amp_decay": (81, (1, 32), 127),
    "amp_release": (83, (1, 34), 127),
    "overdrive": (57, (1, 14), 127),
    "bit_reduction": (54, (1, 11), 127),
    "sample_rate_reduction": (55, (1, 12), 127),
    "delay_send": (84, (1, 36), 127),
    "reverb_send": (85, (1, 37), 127),
    "chorus_send": (12, (1, 35), 127),
}

# CCs that must never be sent: sample slot/bank select, and NRPN/data-entry
# controllers (sent only by the NRPN helper). Bank select 0/32 also blocked.
BLOCKED_CCS = {0, 32, 19, 24, 6, 38, 98, 99, 100, 101}
BLOCKED_NRPNS = {(1, 3), (1, 8), (1, 9)}
