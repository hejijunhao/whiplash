# Digitakt II manual and reference

- **[reference.md](reference.md)**: how the Digitakt II works and what that means for Whiplash. This is the canonical device reference for anyone working on Whiplash. Every claim cites a manual page.
- **The manual itself** is not in the repo. Run `./fetch-manual.sh` to download it here, with a hash check (`*.pdf` is gitignored).

## Source

| | |
| --- | --- |
| Document | *Digitakt II User Manual*, English, for **OS 1.17**. This is the latest OS on Elektron's support page as of 2026-11-11. |
| Edition | Imprint: "last updated September 24, 2026". File dated 260930. 118 pages. |
| Official page | <https://www.elektron.se/support-downloads/digitakt-ii> (Manuals) |
| PDF | <https://www.elektron.se/wp-content/uploads/2026/10/Digitakt-2-User-Manual_ENG_OS1.17_260930.pdf> |
| Size / SHA-256 | 7,923,073 bytes / `a5c12b2b692311828f78fad18008dcda96bf26dd50e117bda5d735794e0bbd06` |
| Page numbers | The printed page numbers match the PDF page numbers. `p. 25` in reference.md is page 25 in both. |

Cross-check source: **midi.guide**, <https://midi.guide/d/elektron/digitakt-ii/>. It is backed by the CSV at [pencilresearch/midi `Elektron/Digitakt II.csv`](https://github.com/pencilresearch/midi/blob/main/Elektron/Digitakt%20II.csv), whose last commit is 2026-10-12. midi.guide is community data under CC BY-SA 4.0, not Elektron's.

## Why only a link, not the PDF

The manual's imprint (p. 11) says: *"This manual is copyright © 2026 Elektron Music Machines MAV AB. All reproduction, digital or printed, without written authorization is strictly prohibited."*

This repo is public, and committing the PDF would be a digital reproduction. So the repo keeps:
- the link,
- the hash,
- a script that fetches the file onto your own machine,
- and `reference.md`. That file is written in our own words, organised for Whiplash, with page references. It quotes only short phrases where the exact wording matters, such as note ranges and channel rules.

If Elektron reissues the manual, the hash check in `fetch-manual.sh` fails. When that happens, re-check the page numbers and tables in `reference.md` against the new edition, then update the URL and hash.
