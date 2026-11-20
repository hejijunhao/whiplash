# Digitakt II: read-only SysEx research spike

Status: **desk research, 2026-11-21.** No message was sent to any device to write this, and nothing here has been tested on a Digitakt II. It backs Phil's decision of 21 Nov 2026 to allow read-only SysEx in the web app ([docs/vision/web-app.md](../vision/web-app.md) §2 item 8, §8). The Hermes plugin's no-SysEx rule is unchanged.

**How to read the labels.** Every claim carries one:
- **[source]**: stated by the cited document, or seen in the cited code at the cited commit.
- **[community]**: reported by a named user in a public thread or log. One report, not a spec.
- **[inferred]**: our reading of sources. It could be wrong.
- **UNKNOWN**: not found. It is not filled in.

**Abbreviations:**
- **[M]** is the *Digitakt II User Manual*, OS 1.17, edition 260930 ([PDF](https://www.elektron.se/wp-content/uploads/2026/10/Digitakt-2-User-Manual_ENG_OS1.17_260930.pdf), SHA-256 in [docs/digitakt-ii/README.md](../digitakt-ii/README.md)), cited by page.
- **[E]** is Elektroid's Elektron connector, `src/connectors/elektron.c` at commit [`cc09785`](https://github.com/dagargo/elektroid/blob/cc097859ef2a024027a7697b940a40cb6ca26df9/src/connectors/elektron.c) (2026-11-14), cited by line.
- **[RN]** is Elektron's [Digitakt II OS release notes](https://www.elektron.se/release-notes/digitakt-ii-os-release-notes) ("last updated Oct 1, 2026").
- **[ref]** is our own [device reference](../digitakt-ii/reference.md), which cites [M] by page.

Messages are written as hex bytes. Every byte below was seen in code or a log at the link given, never reconstructed.

---

## 1. Answers in brief

1. **Official spec:** Elektron publishes none for the Digitakt II.
   - The manual documents only the panel's SysEx dump menu ([M] p. 79-80).
   - We found no message format, identity reply or protocol statement on elektron.se or its knowledge base (§2.5).
2. **Who reverse-engineered it:** the open, maintained implementation for the Digitakt II is **Elektroid** (GPL-3.0). It has supported the Digitakt II since 2024-04-29 for +Drive samples, projects and presets (§6.2).
   - **elk-herd** also supports the Digitakt II in the browser, but its author asks that AI tools not read or reuse it, so we didn't (§6.6).
   - Every other project we found covers other Elektron units.
3. **Known read operations** (§6.3), all from Elektroid's code:
   - ping (device ID, name and supported command list);
   - OS version;
   - storage stats;
   - +Drive directory listing;
   - project, preset and kit listing;
   - the "RAM" read, which on the Digitakt I returns the pool *and* each track's sample.
4. **Per-track sample assignment without loading anything:** **yes on the Digitakt I** [source + community], **UNKNOWN on the Digitakt II.**
   - On the Digitakt II, a 2024 log shows the unit advertising the RAM-read command, and a Digitakt II user's pool listing worked in January 2026 [community].
   - A Digitakt II track listing has never been reported, and Elektroid closed the issue with Digitakt II "still unclear" (§6.5).
5. **Dangerous messages:** uploads, deletes, renames, moves, slot copy, swap and clear, RAM load (which also assigns a sample to a track), RAM clear, and OS upgrade, plus every command byte we can't name (§6.4).
6. **In the browser:** feasible for small listing requests (§8). It needs `sysex: true` and Chrome's permission prompt. Known silent-truncation bugs hit large messages, so the page should reassemble replies defensively and do reads while stopped.
7. **Risks:**
   - **OS updates have broken third-party tools.** elk-herd broke on Digitakt II OS 1.10 and 1.15 (§7).
   - **No bricking from read-only requests was reported anywhere.** That is absence of evidence, not proof.
   - **The EULA forbids reverse engineering "the Software"** (§2.6). Whether using a protocol others decoded falls under that needs a legal read.
8. **Next step:** a hardware probe that Phil runs on the Air with Elektroid's own list-only CLI commands, before we write a line of SysEx code (§11).

---

## 2. Official sources

### 2.1 The manual (OS 1.17)

- **SysEx dump menu** ([M] p. 79-80) [source]:
  - It sends and receives project, pattern and preset data over MIDI OUT or USB. It "does NOT send or receive the presets samples".
  - **Send:** PROJECT sends "the active project (settings, patterns, presets in the pool)"; PATTERN sends the selected pattern. Presets and kits can also be sent from the preset and kit menus (SEND SYSEX, p. 32, p. 35).
  - **Receive:** "Digitakt II is continuously listening for SysEx data so you can at any time send backed up projects or patterns to the device." The same page then describes a receive procedure started with [YES], which stores to the selected pattern slot or a +Drive preset slot.
    - **[inferred]** The two sentences don't say which SysEx the unit acts on without the menu open. Treat the unit as always listening.
- **No SysEx format, identity reply or manufacturer ID appears anywhere in the manual.** That is from a full-text search of the 118 pages for "sysex", "system exclusive", "identity" and "inquiry" [source].
- **Transfer** is Elektron's tool for backups, sample transfer and OS upgrades ([M] p. 20-21, p. 83). OS upgrade works through Transfer over USB, and the unit asks for [YES] before it installs ([M] p. 83) [source].
- **USB CONFIG** has three modes, and "selecting one mode disables the other two": OVERBRIDGE, USB MIDI, USB AUDIO/MIDI ([M] p. 83). The unit is class-compliant, with no driver needed ([M] p. 20) [source].
- **PORT CONFIG:** "If MIDI+USB is selected in the OUTPUT TO settings, MIDI data will limit the USB speed. When sending large chunks of data, make sure you only use the USB setting." ([M] p. 78) [source].
- **FORMAT +DRIVE** is a panel menu with a [YES] confirm ([M] p. 83) [source]. Whether any SysEx command formats the +Drive: UNKNOWN. None appears in Elektroid's command table [source: [E] L209-276].

### 2.2 OS versions ([RN], Oct 1 2026)

The current OS is **1.17**, dated Oct 1, 2026 on the [support page](https://www.elektron.se/support-downloads/digitakt-ii) [source]. That page labels the 1.17 manual "Oct 1, 2025", against the "260930" in its filename, which is a discrepancy on Elektron's side [source].

Versions and the lines that touch MIDI, USB, SysEx, storage, Transfer or Overbridge. The release notes give no per-version dates; the three dates shown come from Elektron's own announcements.

| Version | Relevant changes [source: RN unless noted] |
|---|---|
| 1.00 → 1.01 | CC control of BANK/SBNK on MIDI tracks fixed. "Some of the CC and NPRN values were the same for several parameters." USB audio pre/post fader gain fixed |
| 1.01 → 1.01A | none |
| 1.01A → 1.02 | Transfer sample uploads were slow. Crashes when the +Drive was filling up. Chorus and delay parameters shared NRPN values. CC learn captured the wrong channel |
| 1.02 → 1.03 | "Added support for Overbridge 2.13" |
| 1.03 → 1.03A | Overbridge USB input level |
| 1.03A → **1.10** (announced 2025-03-20, [Elektronauts](https://www.elektronauts.com/t/digitakt-ii-digitone-ii-os-1-10/230650/1)) | "Added support for importing legacy SysEx data." "SysEx import/export of presets did not work correctly." "Added support for exporting a previously imported project or preset with Transfer." "Some NRPN parameters were missing." Tap tempo via MIDI note G10 on FX CONTROL. AUTO-channel notes 0-15 triggering tracks 9-16 fixed |
| 1.10 → 1.10A | "Sample Select NRPN did not switch the sample slots correctly." Transfer project and preset fixes. Overbridge plugin sync fixes |
| 1.10A → 1.10B | none relevant in the notes. A separate summary reports an FX-channel note-on freeze fix; we didn't confirm it on the page |
| 1.10B → **1.15** (announced 2025-06-25, [Elektronauts](https://www.elektronauts.com/t/os-upgrade-digitakt-ii-1-15/235062)) | "the device will run a file system integrity check during its first reboot." If it finds errors: back up everything with Transfer, then FORMAT +DRIVE with SAMPLES ticked, then re-import |
| 1.15 → 1.15A | Filesystem-check dialog fix |
| 1.15A → 1.15B → 1.15C | none relevant |
| 1.15C → 1.16 | "MIDI messages were sometimes not sent if the device tempo was set to very low BPMs." Outbox 8 support |
| 1.16 → **1.17** (2026-10-01) | Outbox 8 features only |

**Downgrades:** "Downgrading the device OS is not supported, and is performed at your own risk. User content may be lost." [source: RN].

**Every other release date is UNKNOWN.**

**[inferred]** Two lines matter most for us:
- **1.10** changed SysEx import and export. That is also the release that broke elk-herd (§7).
- **1.15** changed the +Drive file system enough to need an integrity check. That is the other release that broke elk-herd.

### 2.3 Transfer

- **Version and support:** the current version is 1.10.4 (Jun 23, 2026), and the Digitakt II is on its supported list ([Transfer page](https://www.elektron.se/support-downloads/transfer)) [source]. The Digitakt II page still offers 1.10.3 [source].
- **When support started:** release notes list "Add support for Digitakt II" in the 1.7 to 1.8.6 range ([Transfer release notes](https://www.elektron.se/release-notes/elektron-transfer-release-notes)) [source]. The exact version is UNKNOWN.
- **What the manual says** ([Transfer User Manual v1.10, 2026-03-04](https://www.elektron.se/wp-content/uploads/2026/03/Transfer-User-Manual_ENG_OS1.10_260304.pdf)) [source]:
  - "Transfer uses a USB-MIDI protocol" (p. 4 §1.1).
  - It handles OS files, projects, sounds/presets and samples for the Digitakt I and II (p. 4 §1.3).
  - It recommends USB MIDI mode on the device (p. 8 §2.2.2).
- **The transport:** whether that "USB-MIDI protocol" is the same SysEx protocol Elektroid speaks is UNKNOWN from official sources. **[inferred]** Elektroid's README says it "started as a FLOSS Elektron Transfer alternative", and it works against the same units.
- **Other apps:** Elektron's KB, for connection problems: "Close all other applications that are running on your computer." (quoted on the Transfer page) [source].

### 2.4 Overbridge

- **Version:** current 2.26.10 (Sep 9, 2026), with a minimum of "Digitakt II running OS 1.16" ([Overbridge page](https://www.elektron.se/support-downloads/overbridge)) [source].
- **What it can do:** the plugin can browse and assign samples on the device (Overbridge User Manual, 2026-08-26, p. 27 §6.8) [source]. So Elektron itself reads sample assignment over USB, but through Overbridge mode, not documented SysEx.
- **Mode exclusivity:** turning Overbridge off means "activating USB-MIDI or USB AUDIO/MIDI mode" (p. 8 §3.3.2), and in a DAW "you must not activate the USB MIDI Input and Output" for the device (p. 40) [source]. Whether class-compliant MIDI still works in Overbridge mode is UNKNOWN. **[inferred]** No: [M] p. 83 says one mode disables the others.
- **Protocol:** the Overbridge protocol is unpublished. Overwitch (GPL-3.0, [dagargo/overwitch](https://github.com/dagargo/overwitch)) reverse-engineers its *audio* streaming, lists the Digitakt II, and does no file listing [community/source].

### 2.5 Official word on SysEx

- No Digitakt II SysEx spec, device-inquiry response or manufacturer ID was found on elektron.se, in the [knowledge base](https://support.elektron.se/support/solutions) or in any release notes. UNKNOWN.
- No official statement that the protocol is proprietary or undocumented was found either. Forum users say Elektron stopped publishing specs after the Machinedrum and Monomachine ([Elektronauts](https://www.elektronauts.com/t/undocumented-sysex/61204)) [community].
- **Manufacturer ID** **[inferred]**: Elektroid's header `F0 00 20 3C …` uses `00 20 3C`, the three-byte manufacturer ID that libanalogrytm also uses for Elektron ([sysex.h L44-50](https://github.com/bsp2/libanalogrytm/blob/a0a19f69fcfd44968f05ab7f0af8195633cb83f3/sysex.h)) [source, two codebases agree]. We didn't check it against the MIDI Association's registry.

### 2.6 Terms

- **[EULA](https://www.elektron.se/eula)** (no version or date shown) [source]:
  - §7.1: "You may not and may not permit others to (i) disassemble, decompile or otherwise derive source code from the Software; (ii) reverse engineer or create derivative works of the Software".
  - §2.1: "Software" includes software "pre-installed on Elektron hardware".
  - §4.3: the Software may be used only with Elektron hardware.
- **[Terms & Conditions](https://www.elektron.se/terms-conditions)** [source]:
  - The warranty does not apply if the product was "altered/opened, repaired/attempted to be repaired or reversed engineered in any way", or not operated "in accordance with Elektron's recommendations".
  - No clause names third-party SysEx or MIDI tools.
- **[inferred, needs a legal read]** Sending standard MIDI to the unit is ordinary use. Implementing a protocol decoded by others (Elektroid) isn't obviously "reverse engineering the Software" by us, but it is close enough that Phil should decide with that in view (Q-S5, §12).

---

## 3. MIDI behaviour (what the unit sends and receives)

This is covered in full, with page cites, in [ref] §0, §7-§10 and Appendix B ([M] p. 109-113). Summary:

| Topic | Behaviour | Source |
|---|---|---|
| Track channels | TRACK 1-16 CHANNEL, configurable or OFF. Parameter CC/NRPN is received and sent on each. Sequencer note data goes out on the SRC page's CHAN | [M] p. 79 |
| AUTO channel | controls the active track. Also used to record MIDI tracks from controllers | [M] p. 79 |
| FX CONTROL channel | delay, reverb, chorus, compressor and master overdrive | [M] p. 79 |
| Program change | receive and send toggles in SYNC, with their own in/out channels. Selects patterns | [M] p. 77, p. 79 |
| Clock and transport | CLOCK RECEIVE/SEND and TRANSPORT RECEIVE/SEND toggles | [M] p. 77 |
| Input and output routing | INPUT FROM and OUTPUT TO: DISABLED / MIDI / USB / MIDI+USB | [M] p. 78 |
| What the panel sends | ENCODER DEST, TRIG KEY DEST and MUTE DEST (INT / INT+EXT / EXT). PARAM OUTPUT CC or NRPN. OUTPUT CH auto or track | [M] p. 78 |
| What the unit receives | RECEIVE NOTES and RECEIVE CC/NRPN toggles | [M] p. 78 |
| CC/NRPN map | Appendix B. Discrepancies with midi.guide are in [ref] §8.3 | [M] p. 109-113 |
| SysEx | dump send and receive, always listening for receive | [M] p. 79-80 |
| Turbo MIDI | TURBO SPEED negotiation, needs a Turbo-MIDI interface (DIN only, **[inferred]**) | [M] p. 78 |

---

## 4. USB modes and sharing the port

- **Modes:** OVERBRIDGE, USB MIDI and USB AUDIO/MIDI are mutually exclusive ([M] p. 83) [source]. USB AUDIO/MIDI is class-compliant audio plus MIDI ([M] p. 20, p. 83) [source].
- **Which mode the SysEx file protocol works in:** Transfer recommends USB MIDI mode (Transfer manual p. 8) [source]. Whether Elektroid's protocol also works in USB AUDIO/MIDI mode is **UNKNOWN**, and that is the mode Whiplash's listening needs ([ref] §14).
- **Port names:**
  - On Linux the ALSA name is "Elektron Digitakt II", subdevice "Elektron Digitakt II MIDI 1" (Elektroid issues [#133](https://github.com/dagargo/elektroid/issues/133), [#142](https://github.com/dagargo/elektroid/issues/142), 2024) [community].
  - The macOS and Windows names are UNKNOWN. Whiplash matches "Digitakt" case-insensitively.
- **Two apps on one port** (host OS, not the unit):
  - **Linux:** the ALSA sequencer is shareable, rawmidi is exclusive ([PipeWire #232](https://gitlab.freedesktop.org/pipewire/pipewire/-/issues/232)) [source]. Chromium's ALSA backend uses the sequencer ([midi_manager_alsa.cc](https://chromium.googlesource.com/chromium/src/+/9b738f179f43a26775a41f43867a70b06eea3065/media/midi/midi_manager_alsa.cc)) [source]. **[inferred]** So does python-rtmidi, so Chrome and Whiplash could share it.
  - **Windows:** the legacy class driver is one app per port ([JUCE forum](https://forum.juce.com/t/windows-multiple-client-usb-midi-drivers/10766)) [community]. Windows MIDI Services is "fully multi-client" as it rolls out to Windows 11 ([Microsoft](https://devblogs.microsoft.com/windows-music-dev/?p=858)) [source]. Whether Chrome benefits is UNKNOWN.
  - **macOS:** CoreMIDI shares ports by design. Only dated sources were found ([WWDC 2001](https://nonstrict.eu/wwdcindex/wwdc2001/210/)), so current behaviour is unconfirmed.
- **What the unit does with SysEx while clock and notes arrive,** from one app or two: UNKNOWN.
- **With Transfer open alongside:** Elektron's KB says to close other apps (§2.3). **Proposal:** the web app never reads while Transfer is open, and says so.

---

## 5. Storage model

| Store | Holds | Limits | Source |
|---|---|---|---|
| +Drive | projects, kits, the preset library, the sample bank | 128 projects, 1024 kits, 2048 presets (banks A-H × 256), 20 GB of user samples | [M] p. 16, p. 29 |
| Project | 128 patterns, 16 songs, the pool, settings | | [M] p. 16 |
| Pool (project RAM) | samples loaded into the project, and pool presets | 1016 sample slots, 400 MB; 128 presets | [M] p. 16-17, p. 29 |
| Pattern | one kit, sequencer data for 16 tracks | | [M] p. 16, p. 29 |
| Preset | a sample *linked from the +Drive*, plus the SRC, FLTR, AMP, FX and MOD settings | | [M] p. 29 |
| Sample | 16-bit, 48 kHz, mono or stereo | | [M] p. 29 |

How things link: a kit or preset loaded into a pattern is an independent copy ([M] p. 17, p. 29). Deleting a sample from the +Drive removes it from every preset and pattern ([M] p. 29) [source]. The rest of the data model, including saved and live state, is in [ref] §2.

How Elektroid sees it on the Digitakt II [source: `res/elektron/devices.json` at `cc09785`, L215]:
- **Filesystems:** `sample` (the +Drive sample tree), `data`, `project` (extensions `dt2prj`, `dtprj`) and `preset-takt-ii` (`dt2pst`, `dtsnd`).
- **Storages:** `+Drive` and `RAM`.
- **Not defined for the Digitakt II:** `ram` and `track`, which the Digitakt I has.

A Digitakt II `data` listing at the root showed `projects`, `soundbanks` and `kits` (issue [#133](https://github.com/dagargo/elektroid/issues/133), 2024) [community].

---

## 6. SysEx

### 6.1 Official

None for the protocol (§2.5). Only the panel dump menu is documented (§2.1).

### 6.2 Elektroid

- **What it is:** [github.com/dagargo/elektroid](https://github.com/dagargo/elektroid). Licence **GPL-3.0** (`COPYING`) [source]. A Linux GTK app and CLI, with a macOS bundle script in the repo. The latest release is 3.4 (2026-08-22) and the last commit is 2026-11-14 [source].
- **Digitakt II support** was added in [`c485be6`](https://github.com/dagargo/elektroid/commit/c485be669) on 2024-04-29 as device ID 42 [source]. The maintainer: "Some people at Elektron have provided me with information at some points after the first couple of releases" ([#133](https://github.com/dagargo/elektroid/issues/133)) [community]. He doesn't own a Digitakt II ([#190](https://github.com/dagargo/elektroid/issues/190)) [community].
- **OS versions tested:** not recorded. `devices.json` has no OS-version field, and Elektroid doesn't gate on OS version [source; inferred from the schema]. **Which Digitakt II OS versions Elektroid works with: UNKNOWN.**
- **Framing** [source]:
  - **Header:** every message starts `F0 00 20 3C 10 00` ([E] L209) and ends `F7` (L510-521).
  - **Payload:** packed 7-in-8 (one byte of high bits per seven data bytes, L452-507).
  - **Decoded payload:**
    - bytes 0-1: a 16-bit request sequence number (L863-865);
    - bytes 2-3: the sequence the reply answers, checked on receipt (L960-961);
    - byte 4: the command;
    - the reply's command is `command | 0x80` (L938, L968).
  - **Timing:** a 5000 ms reply timeout (`src/backend.h` L43) and a 50 ms rest between handshake messages (L42).
  - **One request, one reply,** under a mutex. A directory listing is one request and one reply (L1027 `elektron_read_common_dir`, called from L1064-1074).

### 6.3 Read operations (candidates for the allow-list)

These are command bytes as defined in [E] L211-269. "Digitakt II evidence" is what has been seen on a real Digitakt II. None has been tested by us.

| Cmd | Elektroid name | What it returns | Digitakt II evidence |
|---|---|---|---|
| `01` | PING | device ID, the list of command bytes the device supports, and the device name ([E] `elektron_ping` L4402-4418, `elektron_handshake` L4453) | **Seen** in [#142](https://github.com/dagargo/elektroid/issues/142) (2024-06): reply type `81`, device ID `2a` (42), `2c` (44) command bytes, name "Digitakt II" [community]. The reply's layout is our reading of the handshake code [inferred] |
| `02` | SOFTWARE_VERSION | the OS version string (read from offset 10 of the reply) | run by every Elektroid handshake, and the Digitakt II handshake completed in [#133](https://github.com/dagargo/elektroid/issues/133) [inferred]. The string itself has never been posted: UNKNOWN |
| `03` | DEVICEUID | a 32-bit unit ID (Elektroid asks only in debug mode) | none. **Proposal:** leave it off the list, because we don't need it |
| `05` | STORAGEINFO | size and use of +Drive and RAM | **Seen:** `df` on a Digitakt II, "+Drive 20GiB … RAM 400MiB" ([#133](https://github.com/dagargo/elektroid/issues/133)) [community] |
| `10` | FS_SAMPLE_READ_DIR | one +Drive directory: type, size, hash, name | **Seen:** sample listing and download on a Digitakt II ([#133](https://github.com/dagargo/elektroid/issues/133), [#136](https://github.com/dagargo/elektroid/issues/136)) [community] |
| `53` | DATA_LIST | one directory in the data filesystem (projects, presets/soundbanks, kits) with slot, permissions, valid and has-metadata flags, size and name (README `elektron:data:ls`) | **Seen:** root listing on a Digitakt II ([#133](https://github.com/dagargo/elektroid/issues/133)) [community] |
| `17` | DIGITAKT_RAM_READ (request bytes `17 FF FF FF FF`, L263-264; the meaning of `FF FF FF FF` is not commented) | on the Digitakt I: the pool slots (hash, size, slot, used), *then* for each track of the current pattern a hash, size and slot (L3437-3468, L3730-3760; README "RAM and track") [source] | `17` is in the Digitakt II's PING command list ([#142](https://github.com/dagargo/elektroid/issues/142)) [community/inferred]. A Digitakt II pool listing worked on 2026-01-31 with a hand-edited `devices.json` ([#136](https://github.com/dagargo/elektroid/issues/136)) [community]. A Digitakt II track listing: **never reported** |
| `06` | DIGITAKT_GET_PATTERN_INFO | marked "Unused" in the code. The comment says it returns five 32-bit integers, the first the pattern tempo × 120 and the second the global tempo × 120 (L269) [source] | in the Digitakt II's PING list [community]. Untested. Leave it off |

Reading a sample's audio (`30`-`32`) or a project's data (`54`-`56`) is also a read. It is **out of scope** (vision §8), so it stays off the list. A Digitakt II project download stalled at about 70 % in 2024 ([#133](https://github.com/dagargo/elektroid/issues/133)) [community]; its current state is UNKNOWN.

### 6.4 Messages that must never be on the allow-list

From [E] L211-276 [source], with our reading of each name:

| Cmd | Name in Elektroid | Why it is banned |
|---|---|---|
| `11`, `15` | create dir (sample, raw) | writes to the +Drive |
| `12`, `16` | delete dir | deletes |
| `20`, `24` | delete file | deletes |
| `21`, `25` | rename (also used for move) | modifies |
| `40`-`42`, `43`-`45` | open, write and close a file writer | uploads |
| `57`-`59` | data write open, partial and close | overwrites a project, preset or kit slot |
| `5A` / `5B` / `5C` / `5D` | data move / copy / clear / swap | rearranges or erases slots |
| `18` | DIGITAKT_RAM_CLEAR_SLOT | removes a sample from the pool |
| `19` | DIGITAKT_RAM_LOAD_SLOT | loads a +Drive sample into a pool slot **and assigns it to a track** (`0xff` = no track, L3572-3576). It changes the live pattern |
| `50`, `51` | OS_UPGRADE start / write | firmware |
| `22`, `23`, `26` | get file info from path, or from hash and size | harmless-looking, but not needed. Off the list by default |
| `30`-`35`, `54`-`56` | file and data readers | not needed (out of scope). They open reader jobs on the device |
| **Unnamed bytes** in the Digitakt II PING list: `04 07 09 13 28 29 36 46 52 5E` | no name in Elektroid (`28` is a commented-out size/hash query, L271) | unknown effect. **Never sent** |
| Dump receive | the [M] p. 80 receive path: project, pattern and preset data | it stores to slots |
| Anything that isn't `F0 00 20 3C 10 00 …` | universal or other SysEx | not needed. A Universal Device Inquiry sent to a Digitakt II got a non-identity reply (§6.7) |

**The allow-list is the list in §6.3 minus `03` and `06`, and only after §11 confirms each command on a unit.** Everything else is refused before `MIDIOutput.send()`.

### 6.5 Per-track sample assignment, and unsaved state

- **On the Digitakt I** [source + community]: the single `17` RAM read returns, for each track of the *currently selected pattern*, which pool slot it plays and that sample's hash and size. The maintainer: "Notice that the shown tracks are the ones in the currently selected pattern" ([#136](https://github.com/dagargo/elektroid/issues/136), 2024). Elektroid resolves the hash and size to a +Drive path ([E] L3742-3760, `elektron_get_sample_path_from_hash_size`). Nothing is loaded, so **no unit state changes** [inferred from the code: one read request, no load or select command].
- **On the Digitakt II: UNKNOWN.**
  - **For:** `17` is in its PING command list (2024) [community], and the pool part of the reply parsed correctly for a Digitakt II user (2026-01-31) [community].
  - **Against:**
    - nobody has posted a Digitakt II track listing;
    - the Digitakt II has 16 tracks to the Digitakt I's 8, so the track block's length may differ [inferred];
    - a Digitakt II track *upload* (which uses the banned `19`) ended with slot 1023 and a null path;
    - the issue closed on 2026-03-25 with "the integration with the Digitakt II is still unclear" ([#136](https://github.com/dagargo/elektroid/issues/136)) [community].
- **Without loading a project:** for the active pattern, `17` needs no load on the Digitakt I [source]. For other patterns or projects the only known route is downloading the project (`54`-`56`) and parsing its undocumented format. No open decoder for Digitakt II projects was found [source: §6.6]. **UNKNOWN, and out of scope.**
- **Unsaved edits:** whether `17` reflects a sample changed on the unit but not yet saved: UNKNOWN. **[inferred]** Probably yes, because it reads the "currently selected pattern" from RAM, but the probe has to check (§11, step 6). Whether `53` and `10` listings reflect unsaved state is a non-question: they list the +Drive.

### 6.6 Other projects

| Project | Licence | Devices | Digitakt II? | Notes |
|---|---|---|---|---|
| [libanalogrytm](https://github.com/bsp2/libanalogrytm) | MIT | Analog Rytm | no | kit, sound, pattern and song dump formats. Last commit 2023-12-21 |
| [rytm-rs](https://github.com/alisomay/rytm-rs) / [rytm-external](https://github.com/alisomay/rytm-external) | MIT | Analog Rytm MKII, FW 1.70 | no | built on libanalogrytm |
| [digitools](https://github.com/ashojaeddini/digitools) | MIT | Digitone, A4 (sound .syx) | no | documents a sound-dump layout ([sysex_format.md](https://github.com/ashojaeddini/digitools/blob/74bd835baaa71348f2b72917bc9c8f62dd3d479e/docs/sysex_format.md)) |
| [libdigitone](https://github.com/d-huck/libdigitone) | MIT | Digitone patches | no | analysis only |
| [elektron-analog-four-sound-sysex](https://github.com/kimasendorf/elektron-analog-four-sound-sysex) | none found | A4 sounds | no | |
| [Overwitch](https://github.com/dagargo/overwitch) | GPL-3.0 | Overbridge audio | lists the Digitakt II | audio only, no SysEx |
| **elk-herd** (mzero) | UNKNOWN | Digitakt I/II, Model:Samples, Rytm | **yes**: samples and projects, in the browser over Web MIDI ([3.3 release thread](https://www.elektronauts.com/t/elk-herd-3-3-release/230353), 2025-03-14) | the code has moved off GitHub, and its [old repo](https://github.com/mzero/elk-herd) README asks bots and AI not to follow or reuse it. **We didn't read it.** It is the closest prior art to this web app. Contacting the author is a human decision (Q-S6) |

### 6.7 Universal Device Inquiry

Elektroid sends the standard Universal Device Inquiry first. A Digitakt II replied `F0 7E 00 7C 00 F7`, which Elektroid logged as "Illegal SUB-ID2" and then fell back to the Elektron ping ([#142](https://github.com/dagargo/elektroid/issues/142), 2024) [community].
- **[inferred]** `7C` is not the Identity Reply sub-ID (`06 02`). The Digitakt II didn't answer the standard inquiry with an identity reply on the OS it ran in 2024, and that OS is UNKNOWN.
- **So OS detection has to use the Elektron `02` request,** not Universal Device Inquiry.

---

## 7. Firmware churn and risk

- **Format and protocol drift is real:**
  - elk-herd stopped working on Digitakt II **OS 1.10** (author, 2025-03-20: "don't upgrade to 1.10 just yet"; fixed in 3.3.1 the next day).
  - It stopped again on **OS 1.15** (2025-07-29: "if you've updated to OS 1.15, you won't be able to use elk-herd"; fixed in 3.3.4, 2025-08-03). Source: [elk-herd thread p. 5](https://www.elektronauts.com/t/elk-herd-3-3-release/230353?page=5) [community].
  - Whether those breaks hit listings or only project transfer is UNKNOWN. A user reported "Fetch Project" failing on 1.15.
- **No compatibility statement for 1.16 or 1.17** was found from any third-party tool. UNKNOWN.
- **Bricking:** no report found of any third-party SysEx tool bricking an Elektron unit. Absence of evidence, not proof.
- **Data loss:** found only with *write* paths:
  - an elk-herd bug deleted samples used only by p-locks, Digitakt I only;
  - C6 restores gave empty projects when the wrong receive menu was used ([thread](https://www.elektronauts.com/t/c6-sysex-send-results-in-empty-patterns-projects/88883/19)) [community].
- **[inferred]** Read requests carry far less risk than writes, but not none:
  - the unit is "continuously listening" ([M] p. 80), so a malformed or wrong-command message is the main hazard. That is why the list is exact bytes, not ranges;
  - a hung reply could leave the unit's MIDI handling waiting. A Digitone 1.21 bug needed a restart after one SysEx packet (forum, search summary only).
- **Downgrades** are unsupported and "user content may be lost" [RN]. The version gate must never suggest one.
- **Terms:** §2.6.

---

## 8. Web MIDI constraints

- **Spec** ([W3C Web MIDI API](https://www.w3.org/TR/webmidi/), Working Draft 2026-10-31) [source]:
  - **Access:** `requestMIDIAccess` is `[SecureContext]` and "SHOULD prompt". A denied `sysex` request rejects with `NotAllowedError`.
  - **`send()`:** takes "one or more complete, valid MIDI messages" and throws `TypeError` otherwise. SysEx without SysEx access throws `NotAllowedError`. No size limit is stated.
  - **Timestamps:** milliseconds on the `performance.now()` clock. 0 or a past time means now. Same-timestamp sends keep their order.
  - **Received messages:** a `MIDIMessageEvent` carries "a single MIDI message".
- **Chrome** [source]:
  - "the entire Web MIDI API is now gated behind a permission prompt", rolled out from Chrome 124. The blog adds "prompt strings might change" ([Chrome blog](https://developer.chrome.com/blog/web-midi-permission-prompt)).
  - SysEx is allowed only on https:// or http://localhost ([Chromium design doc](https://www.chromium.org/developers/design-documents/web-midi/)).
  - Whether `sysex: true` gets a separate prompt today, and its wording: UNKNOWN.
  - `navigator.permissions.query({name: "midi", sysex: true})` reports the state ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Navigator/requestMIDIAccess)).
- **Size and transport in Chromium,** at commit [`9b738f1`](https://chromium.googlesource.com/chromium/src/+/9b738f179f43a26775a41f43867a70b06eea3065/) [source]:
  - **Overflow is silent:** more than 10 MB unacknowledged and bytes are dropped "on the floor", with no error from `send()` (`third_party/blink/renderer/modules/webmidi/midi_dispatcher.cc` L26, L49-62).
  - **Windows WinMM backend:** SysEx over 256 KB is dropped, and the input buffer is 32 KB (`media/midi/midi_manager_win.cc` L97-113, L558-562). Which Windows backend is the default: UNKNOWN.
  - **Linux:** output goes through the ALSA sequencer and the return value isn't checked (`midi_manager_alsa.cc` L798-822). Fedora [bug 2517136](https://bugzilla.redhat.com/show_bug.cgi?id=2517136): the default 4096-byte `snd_seq_midi` output buffer silently truncates large SysEx.
  - **macOS:** output is sent in chunks of 64 KB or less (`midi_manager_mac.cc` L328-385).
  - **[inferred, unverified]** On Linux a large *incoming* SysEx may arrive as several events, because no reassembly step was found in the ALSA path.
- **macOS 13/14 CoreMIDI** drops or duplicates 512-byte USB blocks on large SysEx ([mzero gist](https://gist.github.com/mzero/814eab1a833f2b0917eb241e377a8c74), 2025) [community]. elk-herd's author: Apple "can't reliably transfer large (> ~60k) SysEx messages, which of course the Digitakt II needs" (thread p. 5, 2025-08-01) [community]. macOS 15+: UNKNOWN.
- **Backpressure:** the spec has none for `send()`, and Chrome drops on overrun ([web-midi-api #158](https://github.com/WebAudio/web-midi-api/issues/158), open) [source].
- **Firefox and Safari:** Firefox 108+ gates Web MIDI behind a generated site-permission add-on, with separate `midi` and `midi-sysex` permissions ([Mozilla](https://groups.google.com/a/mozilla.org/g/dev-platform/c/15O04X2jE28)). Safari has none ([caniuse](https://caniuse.com/midi)) [source].
- **Background tabs:** Chrome throttles timers to about once a second ([Chrome blog](https://developer.chrome.com/blog/background_tabs)) [source]. Nothing is documented for Web MIDI specifically: UNKNOWN.

**[inferred] What this means for the read module:**
- **Requests are tiny:** a command byte plus a short path, packed. Output size limits don't apply.
- **Replies are bounded by one directory or one RAM read.** A large +Drive folder or a full 1016-slot pool could be several KB. The 1016 × 11-byte slot records Elektroid parses (L3753) come to about 11 KB before 7-bit packing.
- **So:**
  - buffer input until `F7`, across events;
  - match the reply's sequence number;
  - time out at 5 s, as Elektroid does;
  - send one request at a time;
  - do reads **with the transport stopped** in v1, because how the unit and Chrome interleave clock with SysEx is UNKNOWN;
  - ask for `sysex: true` only when the browser drawer is opened.

---

## 9. Capability table

| Capability | Possible? | How | Source | Verified or inferred |
|---|---|---|---|---|
| Detect a Digitakt II by port name | yes | Web MIDI port name containing "Digitakt" | [#133](https://github.com/dagargo/elektroid/issues/133) (Linux name) | community (Linux); other OSes UNKNOWN |
| Universal Device Inquiry identity reply | no (one 2024 observation) | `F0 7E 7F 06 01 F7` → `F0 7E 00 7C 00 F7` | [#142](https://github.com/dagargo/elektroid/issues/142) | community + inferred |
| Elektron ping: device ID, name, command list | yes | cmd `01` | [E] handshake; #142 | community log |
| Read the OS version | likely | cmd `02` | [E] handshake | inferred for Digitakt II |
| +Drive and RAM usage | yes | cmd `05` | #133 `df` | community |
| List +Drive samples | yes | cmd `10` | [E]; #133, #136 | community |
| List projects, presets and kits | yes | cmd `53` | [E]; #133 | community |
| List the pool (RAM slots) | probably | cmd `17` | #136 (2026-01-31) | community, one user |
| Per-track sample, active pattern | Digitakt I yes; **Digitakt II UNKNOWN** | cmd `17` | [E] L3730-3760; #136 | unknown |
| Per-track sample, other patterns or projects | UNKNOWN | project download plus an undocumented parse | none | unknown |
| Read kit or pattern parameters and trigs | UNKNOWN (no open Digitakt II decoder) | project or pattern dump | §6.6 | unknown |
| Reads reflect unsaved edits | UNKNOWN | — | — | probe step 6 |
| Reads without changing unit state | listings yes; `17` yes on the Digitakt I | — | [E] | inferred |
| Load a project over SysEx | not found in Elektroid | — | [E] L211-276 | unknown |
| Format the +Drive over SysEx | not found (panel only) | — | [M] p. 83; [E] | unknown |
| Upload, delete, rename or move | exists | §6.4 | [E] | source. **Banned** |
| Download sample audio | exists | `30`-`32` | [E] | source. Out of scope |
| SysEx in Chrome or Edge | yes, behind a prompt | `requestMIDIAccess({sysex: true})` | Chrome blog; W3C | source |
| SysEx in Safari | no | — | caniuse | source |
| SysEx in USB AUDIO/MIDI mode | UNKNOWN | — | Transfer recommends USB MIDI | unknown |
| SysEx reads while clock runs | UNKNOWN | — | — | unknown |
| Reads alongside Transfer | UNKNOWN; Elektron says close other apps | — | Elektron KB | source (advice) |
| Same reads across OS versions | not guaranteed | version gate | elk-herd thread | community |

---

## 10. What we would build (for the vision doc; nothing built yet)

- **One module** in the web app, for example `web/lib/sysex-read.ts`. It is the only code that can emit `F0`, and it is written from the facts in this doc, **not copied from Elektroid**. Elektroid is GPL-3.0, and copying its code would bring the GPL into the web app [inferred]. Facts such as command bytes aren't the same as code, but Phil should confirm the clean-room approach (Q-S5).
- **The allow-list holds exact requests**, after §11:
  - `01`, `02`, `05`;
  - `10` with a path checked against `^/[^\x00]{0,255}$`;
  - `53` with a path;
  - `17` with exactly `FF FF FF FF`.

  Anything else throws.
- **The version gate** passes only device ID 42 with an OS string Phil probed. Anything else turns the read path off.
- **Session rules:** no reads while Transfer or Elektroid holds the port, none while the transport runs (v1), one request in flight, and a 5 s timeout.

---

## 11. Next step: a hardware probe plan (for Phil, on the Air; not run)

**Goal:** confirm or refute §6.3 and §6.5 on the real unit, using **Elektroid's existing list-only CLI commands**, before any of our own SysEx code exists. Record results in [ref] (who, when, OS version) and add the checks to [docs/testing/hardware-checklist.md](../testing/hardware-checklist.md).

**Before you start:**
1. Back up the project and samples with Transfer.
2. Note the OS version shown in Transfer.
3. Close Transfer, Hermes and any DAW.
4. Set USB CONFIG = USB MIDI.
5. Use a scratch project, not one in slots 1-3.

**Install:** build Elektroid 3.4 from source per its README (it has a macOS bundle script; whether a ready macOS binary exists is UNKNOWN). Use **`elektroid-cli` only**. The GUI has drag-and-drop upload.

**Steps.** Every command is a listing from Elektroid's README. Run each with `-vv` and save the output: the hex log is the evidence.
1. `elektroid-cli ld`: the port name as macOS shows it.
2. `elektroid-cli info <n>`: the handshake (ping, version). Record the OS string and the PING command list, and compare the list with §6.3/§6.4.
3. `elektroid-cli df <n>`: storage stats.
4. `elektroid-cli elektron:sample:ls <n>:/` and one subfolder: the sample listing.
5. `elektroid-cli elektron:data:ls <n>:/` and `<n>:/projects`: the project listing.
6. **The RAM and track read.** Add `"ram": null, "track": null` to the Digitakt II entry in a local `~/.config/elektroid/elektron/devices.json`, as the maintainer suggested in [#136](https://github.com/dagargo/elektroid/issues/136). Then run **only** `elektron:ram:ls <n>:/` and `elektron:track:ls <n>:/`. Never `ul`, `dl`, `rm` or `cl`.
   - Do the 16 tracks list, with the right slots?
   - Change track 3's sample on the unit **without saving** and run `track:ls` again. Does it show the change?
   - Then reload the pattern on the unit ([FUNC] + [NO]).
7. Repeat steps 2, 4 and 6 with USB CONFIG = **USB AUDIO/MIDI**.
8. **Afterwards:**
   - The unit still plays the scratch project as before.
   - No new files appear under the +Drive's `incoming` folder (the RAM upload's target in #136).
   - The pattern reload shows nothing changed.
   - Delete the local `devices.json` edit.

**Stop at once** if the unit shows any prompt, dialog or progress bar, or if a command hangs past 10 s. Power-cycle the unit and record it.

**What each outcome means:**
- **All pass:** the allow-list in §10 is justified for that OS string.
- **Step 6 fails:** per-track assignment drops to "unknown". The web app shows slot numbers and labels, as today.

---

## 12. Open questions for Phil (SysEx)

- **Q-S1.** Run §11, and on which OS? 1.17 is current. Any update afterwards needs a re-probe before the gate opens.
- **Q-S2.** Is the version gate strict on the exact OS string, or does it accept versions within the same minor release?
- **Q-S3.** Only USB MIDI mode, or must reads also work in USB AUDIO/MIDI mode, which listening needs? Depends on §11 step 7.
- **Q-S4.** Reads only while the transport is stopped in v1: acceptable?
- **Q-S5.** EULA §7.1 and the GPL: are you comfortable implementing a protocol others decoded, written clean-room from this doc's facts? Is a legal read wanted?
- **Q-S6.** Contact elk-herd's author (prior art, Digitakt II-specific) before building, or stay independent?
- **Q-S7.** The roadmap asks for "a separate audit if [SysEx] is ever considered". Is this doc plus §11 that audit, or is another review wanted before code?

---

## 13. UNKNOWN list

1. Digitakt II OS release dates other than 1.10, 1.15 and 1.17.
2. Any official Digitakt II SysEx spec, identity reply or protocol statement.
3. Which Digitakt II OS versions Elektroid has been used with.
4. The Digitakt II's OS version string format (cmd `02` reply).
5. Per-track sample assignment on the Digitakt II through `17`, and the track block's layout for 16 tracks.
6. Whether `17` reflects unsaved edits.
7. What the unnamed PING-list commands do (`04 07 09 13 28 29 36 46 52 5E`).
8. Whether the protocol works in USB AUDIO/MIDI mode.
9. Unit behaviour with SysEx and clock or notes interleaved.
10. Port names on macOS and Windows.
11. Chrome's SysEx prompt wording, and whether it is a separate prompt.
12. Chrome's default Windows MIDI backend. Whether Linux delivers large incoming SysEx as one event.
13. macOS 15+ reliability with large SysEx.
14. The elk-herd licence, and its Digitakt II OS 1.16/1.17 status.
15. Whether Transfer's protocol is the one Elektroid speaks.
16. Whether class-compliant MIDI works in Overbridge mode (inferred no).
17. Any risk of bricking or data loss from read-only requests specifically.
