# Whiplash visualiser restyle: design brief (from Phil's inspiration, 11 Nov 2026)
Reference: https://x.com/parhelion318/status/2120212304809918827 (44s "tape ambient setup" clip).
Goal: restyle the existing whiplash_open_view page (127.0.0.1:7341, SSE) in this look. No new deps, no network fonts/CDNs, keep it a single self-contained page. Do not change tool contracts.

## Look
- Flat skeuomorphic pixel art: hardware-rack metaphor (modules, knobs, jacks, patch cables) rendered flat, no gradients/3D/shading.
- Strict grayscale: bg #171717, module panels #333333, mid #808080-#8A8A8A (knobs, borders), highlight/text/cables #F0F0F0.
- Background: pegboard dot grid (small dark-gray dots on near-black), via CSS radial-gradient or canvas.
- Font: uppercase monospaced bitmap style, unanti-aliased look (bundle a small pixel font or use system monospace with image-rendering: pixelated / crisp scaling). Terse labels: TRK 1, SPD, LEN, FLT, SWG, BPM.
- Modules: rectangular boxes freely laid on the grid, 1-2px light borders.
- Cables: 1-2px white SVG bezier curves with a catenary sag, connecting OUT/IN jacks (eg each track module into a master OUT module).
- Controls drawn flat: gray circle knobs with a white position dot/line, bat toggles, vertical faders with rectangular thumbs, jacks as dark-centre/light-rim circles, 2x2px LEDs.

## Motion (tie to real Whiplash state)
- Per-track module: knob positions = real param values (filter, level, etc.); LED blinks on each trig; current note label flips (eg E3, F#4) when notes play.
- Mute = LED off + dimmed module; drop/fill = brief invert flash.
- A transport/tape module: cassette with reels rotating at speed proportional to BPM, stopped when transport is stopped; REC-style LED for "playing".
- Master OUT module: analog VU meter with a bouncing needle driven by step activity / trig density (we have no audio input; derive an envelope from trigs and levels and say so in a code comment).
- Optional hero visual: concentric dotted rings pulsing from a hub on each kick/bar downbeat.
- Bar/step position shown as a 16-step pixel strip.

## Done when
- Tests pass, CI green, screenshots or a short description in the PR, hardware-test checklist (open view during a live Hermes session on the Air in Safari and Chrome; check motion stays in time).
- Never claim hardware-verified.
