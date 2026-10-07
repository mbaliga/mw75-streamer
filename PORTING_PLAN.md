# MW75 Neuro Streamer — multi-platform porting plan

> Part of the constellation-wide porting program (`Personal-Tracker/PORTING_PROGRAM.md`, 2026-10-06).
> Status: **PLAN — nothing in this document has been built.** Every claim about a target platform is
> labelled with its evidence class (§0). This file is owned by the lead planning session; a platform
> track updates only its own §4 row and its lines in the evidence ledger (§6.6). This repo has no
> STATE.md or PROGRESS.md, so the ledger lives here.
>
> **Fork-only document.** `mbaliga/mw75-streamer` is a fork of `arctop/mw75-streamer` (MIT) and must stay
> upstreamable (§3). This file, the one-line pointer to it in `README.md`, the `ubuntu-touch/` directory
> proposed in §6.4 and any fork-only workflow are **excluded from every PR to arctop**. Written from `main`
> at a36ec45 plus a read-only look at PR #1 and PR #3 on GitHub (their branches are not in the local clone).

## 0. Evidence labels (never dropped)

`PLAN` (this document) · `CI (hosted VM)` · `SIMULATOR` · `CI-APPROX — NOT DEVICE EVIDENCE` ·
`NEEDS-DEVICE-VALIDATION` (NDV) · `NEEDS-OWNER-VALIDATION` (NOV) · `NOT-APPLICABLE` (with reason).
Also used here: `SYNTHETIC` (asom's base set; anything driven by `--mock` packets). Program additions used: `PLAN` and `NOT-APPLICABLE (<reason>)`; `CONTAINER-BUILD-ONLY` does not apply because this container runs nothing for this repo.
The planning environment has no MW75 headset and none of the target devices on record (no Windows machine,
Mac, Ubuntu Touch device or Raspberry Pi), so **no Bluetooth path on any OS can be verified from it**. Hosted runners prove
imports, type checks, factory selection and mock streaming only.

## 1. What this repo is, in porting terms

**Product.** MW75 Neuro Streamer (PyPI `mw75-streamer`, v1.0.8): a headless Python CLI and daemon that
streams 12-channel, 500 Hz EEG from Master & Dynamic MW75 Neuro headphones. It does a BLE activation
handshake (bleak), then reads Bluetooth Classic RFCOMM channel 25, and fans out to CSV, a WebSocket
client, LSL, a WebSocket remote-control server (`python -m mw75_streamer.server`) and a browser panel. In
the constellation it is the canonical streamer layer of the EEG stack (Ebbflow is the app above it, Baseline
the engine; `Personal-Tracker/DECISIONS.md` 2026-07-06, D-S).

**State** (`README.md` lines 10-19: `state: dormant (not dead)`). `main` is the macOS implementation
(PyObjC + IOBluetooth, with the macOS 26 "Taho" BLE-disconnect-before-RFCOMM workaround); on Linux and
Windows only `--mock` runs, because `main.py:445-453` and `server/__main__.py:67-71` refuse a real device.
Upstream code last changed 2025-12-11. Fork commits since are docs and CI only. Port work is parked on two
open **draft** PRs, checked on GitHub 2026-10-06:

| PR | Branch @ head | Content | Status |
|---|---|---|---|
| #1 Linux | `claude/cool-galileo-6AX0j` @ 0c3d363 | `device/rfcomm_backend.py` (factory + protocol), `rfcomm_manager_linux.py` (stdlib `AF_BLUETOOTH`, BlueZ D-Bus paired-device lookup), `README_LINUX.md`, `dbus-fast` marker, CI assertions | Based on c5d6aef; `main` is 4 commits ahead, so it needs a rebase and `README.md` will conflict. CI green 2026-07-06. Not hardware-verified. |
| #3 Windows | `claude/mw75-windows-rfcomm` @ 1950b0d | `rfcomm_manager_windows.py` (stdlib `AF_BTH`; `MW75_BT_ADDR` required), `README_WINDOWS.md`, `windows-latest` job | Stacked on #1. CI green 2026-07-06. Not hardware-verified. |

Neither PR touches `server/`, which stays macOS-bound; that is the largest remaining gap (§2, §6.1 L3).

**Stack.** Python 3.9–3.12; no UI toolkit (CLI plus `logging`; the browser panel is plain HTML/JS opened with
`webbrowser.open("file://…")`, `main.py:498-500`). Build: setuptools via `pyproject.toml`, `uv` + `uv.lock`,
`Makefile`, GitHub Actions. Key dependencies: `bleak>=0.20` (per-OS backends; none for iOS or Android),
`pyobjc` + `pyobjc-framework-IOBluetooth` (darwin marker), `websockets`, `websocket-client`, optional
`pylsl` (needs native liblsl per OS). Nothing is compiled in this repo.

**Size** (measured 2026-10-06 at a36ec45): `git ls-files 'mw75_streamer/*.py' 'examples/*.py' | xargs cat | wc -l`
gives 27 files, 5,825 lines; `git ls-files 'mw75_streamer/*.html' | xargs cat | wc -l` gives 2 files,
2,813 lines (≈ 8,640 lines in 29 files; `docs-src/conf.py` and the Sphinx `.rst` files are excluded).
**Tests: none.** `pyproject.toml` sets `testpaths = ["tests"]` but `tests/` does not exist; `make test` runs
a manual WebSocket harness (`python -m mw75_streamer.testing`), and CI is black, flake8, mypy and
import/`--help` smoke only.

## 2. Portable core vs platform-bound layers

| Module / dir | Role | Portability | Approx LOC | Notes |
|---|---|---|---|---|
| `mw75_streamer/config.py` | Protocol constants: BLE UUIDs, activation bytes, 63-byte packet layout, RFCOMM channel 25, CSV headers | Python | 60 | OS-neutral. The single source the constellation says must not be re-implemented (Ebbflow's `Mw75Constants.kt` mirrors it; Q5). |
| `data/` (`packet_processor`, `streamers`) | Sync-scan framing, checksum, ADC to µV, `EEGPacket`; CSV, stdout, WS-client, LSL outputs | Python | 796 | Fully portable. `pylsl` needs liblsl per OS; docs give macOS advice only (`streamers.py:365-371`). |
| `device/ble_manager.py` | BLE discovery and activation, disconnect-after-activation, cleanup | Python (bleak) | 302 | Portable to macOS, Linux (BlueZ) and Windows (WinRT) via bleak wheels. Desktop-only by dependency. Import-gated to darwin on `main`. |
| `device/rfcomm_manager.py` | RFCOMM ch. 25 via `IOBluetoothDevice`, `NSRunLoop`, priority boost | **macOS-bound** | 266 | **The seam.** Stays the unchanged darwin backend (§3). PR #1 adds the factory and a Linux manager; PR #3 adds Windows. |
| `device/mock_rfcomm_manager.py` | Synthetic 500 Hz packets, same manager interface | Python | 200 | Cross-platform; proves the seam; must keep working everywhere. |
| `device/mw75_device.py` | Coordinator: BLE activate, BLE disconnect, RFCOMM connect, run | Python | 116 | Imports the macOS manager directly on `main`; PR #1 swaps in the factory. |
| `main.py` | argparse CLI, fan-out, drop counting, panel launch | Python | 538 | darwin gates at lines 30-33 and 445-453. |
| `server/` | Multi-client WS control server: connect/status/broadcast, auto-reconnect, heartbeat, battery, log forwarding | **Partly macOS-bound** | 1,430 | `ws_server.py:36-51` imports `Foundation`; `_run_rfcomm_streaming` (896-913) pumps `NSRunLoop` 1 ms at a time between `asyncio` yields; it constructs `RFCOMMManager(...)` directly (line 704). Bound to `localhost` by default (`server/__main__.py:50`). **Main remaining port gap.** |
| `panel/`, `testing/` | Browser dashboard relay; manual WS test harness and HTML visualiser | Web / Python | 1,332 / 2,605 | Portable wherever a browser exists; unused on headless hosts. |
| `utils/`, `examples/` | stderr logger; integration examples | Python | 73 / 815 | Pure. `examples/README.md:216` still says "macOS (Linux support planned)". |
| `docs/`, `docs-src/` | Jekyll Pages root; Sphinx source built into `docs/api/` | Docs | — | **Published upstream-facing docs**, not a place for fork-internal plans. |
| `.github/` | `ci.yml`, `docs.yml`, `cleanup-artifacts.yml`, `settings.yml`, PR template | CI | — | See §3 for branch protection and the PyPI publish hazard. |

**Platform-bound APIs that matter**

| API | Where | Porting impact |
|---|---|---|
| `objc`, `Foundation`, `IOBluetooth` (`pairedDevices`, `openRFCOMMChannelAsync_…`) | `device/rfcomm_manager.py:10-12,111,149,165-169,238-253` | The only hard macOS dependency of the CLI path; replaced per OS behind the factory. |
| `ctypes.CDLL("libc.dylib").thread_policy_set` + `os.nice(-10)` | `rfcomm_manager.py:178-225` | macOS-only priority boost. Linux and Windows backends on the PRs have none; add only if measured drop rates demand it. |
| `NSRunLoop` interleaved with `asyncio` | `server/ws_server.py:36-51,114-115,695-705,739-742,896-913`; `server/__main__.py:15-19,67-71` | Real-device server path is macOS-only on `main` and on both PRs. |
| `sys.platform == "darwin"` import gates | `__init__.py:23-31`; `device/__init__.py:10-28`; `main.py:30-33,445-453` | Lifted on the PRs; the existing CI assertions encode the old rule (§6.0). |
| `bleak` | `device/ble_manager.py:10,52,131-136,181-192,273` | Desktop OSes only. No iOS backend. On Ubuntu Touch it needs system-bus access to BlueZ. |
| `AF_BLUETOOTH` (Linux), `AF_BTH` (Windows), stdlib via `getattr` | PR #1 `rfcomm_manager_linux.py`; PR #3 `rfcomm_manager_windows.py` | Dependency-free and MIT-clean. Kernel `rfcomm` on Halium unverified; Windows address form unverified. |
| `dbus-fast` (BlueZ `GetManagedObjects`) | PR #1 `rfcomm_manager_linux.py:195-262` | User needs the `bluetooth` group or a polkit rule; `MW75_BT_ADDR` bypass exists. |
| `webbrowser.open(file://…)` | `main.py:498-500` | Fine on desktops; headless hosts run without `--browser`. |
| `pyrightconfig.json` `pythonPlatform: "Darwin"`; `Makefile` `sed -i ''` | `pyrightconfig.json:21`; `Makefile:109-139` | Dev tooling assumes macOS; BSD `sed` breaks on GNU. |
| PyPI trusted publishing on `refs/tags/v*` | `.github/workflows/ci.yml` `build-and-publish` | A hazard, not an API: a `v*` tag on the fork would attempt a publish under upstream's package name. |
| `[tool.setuptools] packages = [...]` | `pyproject.toml` | The explicit list omits `mw75_streamer.server`. CI's `python -m mw75_streamer.server --help` runs from an editable install, so it would not notice. Whether the published wheel lacks `server/` is **unverified** (L7). |

## 3. Binding rules this port must not break

- **Upstreamability governs.** Every change is a small, additive, isolated contribution fit for a PR to
  `arctop/mw75-streamer`; no package rename (`mw75_streamer`); no fork-specific behaviour in shipped code
  (`README.md:10-19`; `DECISIONS.md` 2026-07-06; `Ebbflow/docs/streamer_port_plan.md` "Contribution intent").
- **Do not re-implement MW75 packet parsing elsewhere** (`README.md:14-16`; `DECISIONS.md` EEG-stack item 1).
  A UT click or any other front end imports this package; it never copies parsing or constants. The Kotlin
  re-implementation in Ebbflow is a standing tension (Q5).
- **The WebSocket JSON output schema is frozen** (timestamp, event_id, counter, ref, drl, channels ch1–ch12,
  feature_status, type): Baseline and Ebbflow depend on it (`streamer_port_plan.md` "Untouched"; PR #1/#3 bodies).
- **BLE handshake, packet parsing, mock mode and output paths stay unchanged**; new OS code goes in clearly
  named new files behind the `rfcomm_backend` factory (`streamer_port_plan.md` "Design" and "Untouched").
  `server/` appears in that "Untouched" list; §6.1 L3 asks to change only its internal RFCOMM pump, with a
  byte-identical wire format. That is a **proposal** (Q6), not a ruling.
- **Mock mode (`--mock`) must work on every platform**; downstream is developed against it first.
- **Licence: MIT**, Copyright (c) 2025 Arctop (`LICENSE`). No copyleft dependencies: PyBluez is GPL-2.0, which
  is why the ports use stdlib sockets. Keep it that way (I-11). The program's OQ-12 lists "mw75 upstreaming"
  under licence gaps; this repo's own licence is present, and the gap OQ-12 names is Ebbflow's missing
  `LICENSE`, which matters if constants are ever generated from `config.py` into it (Q5).
- **Code standards enforced by CI and `CONTRIBUTING.md`:** Python 3.9+ (typeshed already forced `getattr()`
  for `AF_BLUETOOTH`), black (line length 100), flake8, mypy strict, annotations and docstrings on public
  functions. `.github/settings.yml`: required checks `code-quality` and `macos-compatibility`, one approving
  review, squash or rebase only, no force-push to `main`.
- **Environment honesty (I-4):** every port stays "NOT hardware-verified" with an owner checklist until the
  owner confirms (`README_WINDOWS.md` "Status" block; `rfcomm_manager_windows.py` docstring "Do not report
  Windows streaming as confirmed").
- **No telemetry (I-1).** The package makes no outbound call of its own: the WS client in
  `data/streamers.py` connects only to the URI the user passes, and `server/`, `panel/` and `testing/` listen on
  `localhost` unless the user passes `--host`. Ports add no analytics, update checks or crash reporting.
- **Colour never carries meaning alone (I-3).** The program's I-3 list and OQ-26 do not name this repo, so its
  scope here is unruled (Q13). This plan applies it to anything it adds (shape plus word in any status UI).
  The existing `panel.html` and `eeg_test_client.html` use `#4CAF50` and `#f44336` for buttons and status; the
  visible labels carry words, but the surface is **unaudited** and this plan does not edit it.
- **`CLAUDE.md` and `.claude/` are gitignored** (`.gitignore`); agent instructions cannot be committed here.
- **Never push a `v*` tag from the fork**; versions are bumped only by upstream (`Makefile` version targets and
  the `pyproject.toml` / `__init__.py` / `docs-src/conf.py` triplet).
- **Fork workflow:** develop in the fork, PR upstream; Ebbflow and baseline pin the fork by commit and never
  vendor the streamer (`streamer_port_plan.md`). **Do not close or rewrite PR #1/#3 without the owner**
  (`Personal-Tracker/CONSTELLATION.md` row `mw75-streamer`, which marks the repo verify-only).
- **This repo has no decision log.** Proposals stay in this file (§6, §8) until the owner rules; the owner
  then chooses where a ruling lives (`Personal-Tracker/DECISIONS.md` or the upstream PR description).

## 4. Target matrix (owner's order)

| Target | Feasibility | Approach | Blockers | Effort (eng-weeks, estimate) | Evidence today |
|---|---|---|---|---|---|
| Ubuntu Touch | reframe | **(a) Recommended:** the phone is a WebSocket client of `mw75_streamer.server` running on a LAN host (the Linux build; a Pi with the systemd unit from `README_LINUX.md`). The client click is Ebbflow's, not this repo's: 0 weeks here. **(b) Only if the owner wants on-phone capture:** a Python + QML click in `ubuntu-touch/` importing this package, with the reserved `bluetooth` policy group (open source, manual OpenStore review or sideload), foreground-only. Labelled "MW75 capture on Ubuntu Touch", never "a port of the CLI" (R12). | No UT device on record (OQ-1). Unknown: whether the `bluetooth` group alone allows raw `AF_BLUETOOTH` RFCOMM and bleak's BlueZ D-Bus use (else `unconfined`); whether the Halium kernel has `rfcomm`; BlueZ version; arm64 `dbus-fast`. Lomiri freezes unfocused apps, so capture stops off-screen. Needs the Linux backend (PR #1, OQ-13). | 4 (0.5 spike + ≈3.5 for (b)) | PLAN |
| Linux desktop | straight | Rebase and land PR #1; make the `server/` real-device pump backend-aware (proposal, Q6); add tests, an arm64 smoke lane, priority only if measured, docs; owner hardware verification on a Steam Deck, a Debian host and a Raspberry Pi; one upstream PR. Fallback if non-root RFCOMM fails: BlueZ `ProfileManager1` over `dbus-fast`. Redmagic-Edge (Termux/proot, no radio, no BlueZ) can run `--mock` only. | OQ-13; MW75 + a Linux host (OQ-5); `server/` still macOS-bound; no automated tests exist | 1.5 | PLAN |
| iOS / iPadOS | n/a | None. iOS gives third parties no Bluetooth Classic RFCOMM without MFi; CoreBluetooth is BLE-only; bleak has no iOS backend (community and Apple-forum sourced; the master brief labels it `ASSUMPTION`). The iOS-shaped artefact is an Ebbflow LAN viewer of this streamer's WebSocket. | Would reopen only if the headset exposes a BLE GATT data stream or an MFi protocol (unknown). | 0 | PLAN — `NOT-APPLICABLE` (no RFCOMM API on iOS) |
| macOS | done | `main` is the implementation. Keep `rfcomm_manager.py` as the unchanged darwin backend behind the factory when #1 and #3 land; regression-check in CI; owner re-verifies on macOS 26. No `.app` bundle: it is a pip-installed CLI (Q12). | No Mac on record (OQ-5): device gate stays NOV | 0.2 | PLAN (today `main` has `CI (hosted VM)` import checks only) |
| Windows | moderate | Land PR #3 after #1 (retargeted to the Windows delta): add paired-device enumeration so `MW75_BT_ADDR` is optional (WinRT packages bleak already installs, `ctypes` `BluetoothFindFirstDevice` fallback); confirm the `AF_BTH` address form and channel 25 without an SDP record on hardware; same `server/` generalisation as Linux (proposal, Q6); priority only if measured; docs. | OQ-13; a Windows 10/11 box with a BR/EDR adapter plus the headset (unknown whether one exists); `AF_BTH` behaviour unverified | 2 | PLAN |

The sum for Linux + Windows + macOS is 3.7 engineer-weeks, the "about 4" in the program's §5 row. Ubuntu Touch
is counted separately and only under shape (b). All figures are estimates, not commitments.

## 5. Tier and sequencing

**Tier B (port).** This is a classic port: macOS is done on `main`, and Linux (PR #1) and Windows (PR #3) are
CI-green stdlib backends behind a factory, with the owner's mandate to give them back upstream. It is not
tier A because it is a headless CLI with no UI surface and two of five targets do not apply or are reframed
(iOS not-applicable; Ubuntu Touch a reframe). It is not C or D because the Linux backend unblocks the EEG
stack (Ebbflow and Baseline consume its WebSocket) and most of the code is written.

**Gate before any wave** (program §5): OQ-13 (the owner's merge-or-close call on #1 and #3); an MW75 headset
plus a Linux host; branch protection (one review, squash or rebase); this plan stays fork-only.

| Target | Program wave | Repo-local gate that must hold before the wave starts |
|---|---|---|
| Ubuntu Touch | **P-UT a** (Python + QML click; manual review, open source), parallel with P-LX | Build-entry: PR #1's backend exists on a green branch (OQ-13) and the on-device spike (§6.4 U1) is passed; device-entry: a UT device (OQ-1) or an explicit CI-only waiver, in which case every device gate is NDV. Shape (a) needs no wave here. |
| Linux desktop | **P-LX** | OQ-13 ruled; PR #1 rebased, CI green on the hosted matrix, un-drafted; owner has the headset and a Linux host. |
| iOS / iPadOS | none (program §7: "Not on iOS: Ebbflow/mw75 capture") | `NOT-APPLICABLE`. |
| macOS | **P-mac** | P-LX landed, so the darwin path is regression-checked through the factory. Device gate NOV until a Mac exists (OQ-5). |
| Windows | **P-win** | PR #1 landed (PR #3 is stacked on it); OQ-13; Windows hardware (OQ-5) or the owner accepts "experimental, unverified". |

The owner's order (UT first) is the order in which the owner receives device-installable artefacts. The
cheapest build order is Linux first, because a UT click imports the Linux backend (R4: core before UI). The
UT hardware spike can run before OQ-13 resolves, since it needs only a short socket script and the device.

## 6. Work breakdown

### 6.0 Placement and rules applied to this repo

- **"Root build" here** means `pyproject.toml`, `ci.yml`, `settings.yml`, `docs.yml`. PR #1 and PR #3 already
  edit `pyproject.toml` (dependency marker, classifiers) and `ci.yml` (the Linux job asserts
  `MW75Device is None` on non-darwin, which lifting the gate necessarily flips; PR #3 adds a Windows job).
  R3 ("`ci.yml` is not edited by a port") cannot hold for those two drafts. This plan keeps their edits and
  asks for the exception (Q11). **Every lane this plan adds goes in a new workflow file.**
- **Per-OS backends** are new, OS-named files in `mw75_streamer/device/` behind the factory, per the repo's own
  design rule. Shared edit points (`device/__init__.py`, `mw75_device.py`, `main.py`, `server/ws_server.py`,
  `server/__main__.py`) are touched by the Linux track first; the Windows track adds its file, one factory
  branch and the win32 guard only, to avoid conflicts.
- **Tests** go in a new top-level `tests/` (already declared in `pyproject.toml`). No existing file changes.
- **Ubuntu Touch** goes in `ubuntu-touch/` at the repo root, outside `[tool.setuptools] packages`, so it is
  never in the wheel and is fork-only by default.
- **No listener in any lane this plan adds (R5):** tests call serialisers and the pump with fakes; the existing
  `--help` smoke is unchanged. **No artefact uploads (R6)**; nothing is signed or released; no tags.
- **R3 path lint:** `git ls-files | grep -E '[:<>|?*"]|(^|/)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|/|$)'`
  returns nothing on `main` at a36ec45. PR branches have not been checked. There are no byte-exact fixtures.

### 6.1 Linux desktop (wave P-LX)

| Step | Work | Where | Done when |
|---|---|---|---|
| L0 | Owner rules OQ-13 (rebase #1 then retarget #3, or fold into one PR) and Q6 (server in scope). | — | Owner answer recorded in §8. |
| L1 | Rebase PR #1 onto current `main`. Resolve the `README.md` header conflict by keeping the fork header (and this plan's pointer line); `ci.yml` should merge cleanly against #4's separate workflow file (reader's finding, unverified). | PR #1 branch | PR #1 CI green on the hosted matrix (`CI (hosted VM)`); `git diff --stat` shows `device/rfcomm_manager.py` untouched. |
| L2 | Add the repo's first automated tests: packet framing and checksum using `build_eeg_packet` from the mock; factory selection per `sys.platform` (monkeypatched); a short mock run asserting checksum validity, counter continuity and the JSON key set (the frozen schema as a golden list), with **no wall-clock rate assertion**. | `tests/`; new `.github/workflows/tests.yml` (pytest on ubuntu 3.9–3.12, `macos-latest` and `windows-latest`) | Green on hosted runners. `SYNTHETIC` + `CI (hosted VM)`. Upstreamable (`CONTRIBUTING.md` asks for tests). |
| L3 | **PROPOSAL (Q6):** make the `server/` real-device path backend-aware. Build the manager through the factory; darwin keeps the 1 ms `NSRunLoop` pump; socket backends run `run_until_stopped` in `run_in_executor` and await it; lift the `server/__main__.py` gate. Wire format byte-identical (L2's golden list). | `server/ws_server.py`, `server/__main__.py` | Tests pass on all hosted OSes with the mock backend; **real-device path NDV**. |
| L4 | Priority boost: first take a drop-rate baseline without any boost (L8), then add `os.nice` and optional best-effort `sched_setscheduler` to the Linux backend only if the measured drop rate warrants it. No sudo requirement. | `rfcomm_manager_linux.py` | Owner run shows the measured effect (NDV); otherwise left out of the upstream PR (Q9). |
| L5 | arm64 smoke lane for the Pi: install, import, factory selection, tests, short `--mock` run on `ubuntu-24.04-arm`. Proves the userland imports, nothing about Bluetooth. | New `.github/workflows/linux-arm.yml` | `CI (hosted VM)` green; Pi device run stays NDV. LSL on aarch64 is unverified. |
| L6 | **Non-root RFCOMM spike** (the program records this as unsettled on Ubuntu 24.04): can an unprivileged user in the `bluetooth` group open channel 25 with PR #1's socket path? If not, add `rfcomm_manager_linux_profile.py` (BlueZ `ProfileManager1` via `dbus-fast`, which PR #1 already depends on) behind the same factory. Build the fallback only on failure. | `mw75_streamer/device/` | Written verdict; NDV. |
| L7 | Docs and tooling that say "macOS only": `docs-src/installation.rst`, `index.rst`, `protocol.rst` (replace "Windows via pywin32" with stdlib `AF_BTH`), `examples/README.md:216`, per-OS liblsl notes in `README_LINUX.md`, `pyrightconfig.json` pin, `Makefile` `sed -i ''`. Add a step to the new `tests.yml` (L2) that builds the wheel and lists its contents; if `mw75_streamer.server` is missing from the built wheel, add it to `[tool.setuptools] packages` in `pyproject.toml` (an upstreamable root-build fix, the same file PR #1/#3 already edit). | Existing docs and config (upstreamable) | `docs.yml` build step succeeds on the PR; wheel check is `CI (hosted VM)`. |
| L8 | **Owner hardware verification** per PR #1's checklist: Steam Deck (Arch, immutable rootfs, venv under `$HOME`), a Debian host, a Raspberry Pi (model unknown); a 10-minute lossless 500 Hz, 12-channel run; whether BLE-disconnect-before-RFCOMM is needed on Linux; Classic versus BLE address. | Owner devices | Ledger rows (§6.6) move from NDV only when the owner confirms. |
| L9 | Open the upstream PR to `arctop/mw75-streamer` per their PR template, squashed, with the hardware checklists in the body. **Excludes** `PORTING_PLAN.md`, the `README.md` fork header and pointer, `ubuntu-touch/`, `cleanup-artifacts.yml` and any fork-only lane. | Upstream | PR opened; draft or ready per Q10. |

### 6.2 Windows (wave P-win)

| Step | Work | Where | Done when |
|---|---|---|---|
| W1 | After L1, retarget PR #3 onto the rebased PR #1, or fold per OQ-13, so its diff is the Windows delta. | PR #3 branch | `windows-compatibility` green (`CI (hosted VM)`). |
| W2 | Paired-device enumeration so `MW75_BT_ADDR` is optional: prefer the WinRT `Windows.Devices.Bluetooth` packages bleak already installs on win32 (`GetDeviceSelectorFromPairingState`, `DeviceInformation.FindAllAsync`, read `BluetoothAddress`); fall back to `ctypes` `BluetoothFindFirstDevice`. Both are the reader's recommendation, unverified. | `rfcomm_manager_windows.py` or a sibling module | Unit tests with a fake enumerator on `windows-latest` (`CI (hosted VM)`); real enumeration NDV. |
| W3 | On hardware, confirm the `AF_BTH` address string Winsock accepts (bare versus parenthesised) and that channel 25 connects without an SDP record. If it does not, the fallback is unknown. | Owner Windows box | NDV; ledger. |
| W4 | `SetPriorityClass` / `SetThreadPriority` through `ctypes`, gated like L4. | Windows backend | Measured on hardware (NDV) or omitted (Q9). |
| W5 | `server/` generalisation is L3; here only verify on `windows-latest` with the mock backend. | — | `CI (hosted VM)` green. |
| W6 | `README_WINDOWS.md` keeps its "Status" block; `docs-src/protocol.rst` updated in L7; fold into the upstream PR. If no Windows hardware exists, ship labelled "experimental, unverified" (OQ-13). | Docs | Labels present in the upstream PR text. |

There is no Windows binary to sign: the artefact is the pure-Python wheel. A frozen `.exe` would be a new
decision (Q12), unsigned and never released from CI (R6, OQ-3).

### 6.3 macOS (wave P-mac)

| Step | Work | Done when |
|---|---|---|
| M1 | After L1 and L3, confirm the darwin backend is still `rfcomm_manager.py` behind the factory, and that `server/` keeps the `NSRunLoop` pump for darwin. | `macos-compatibility` green; the diff shows `rfcomm_manager.py` unchanged (`CI (hosted VM)`). |
| M2 | Owner re-verification on macOS 26 after the rebase (Taho workaround still effective, 500 Hz run). | NOV: no Mac is on record (OQ-5). Upstream users may report. |

### 6.4 Ubuntu Touch (wave P-UT a)

| Step | Work | Where | Done when |
|---|---|---|---|
| U0 | Owner picks shape (a) or (b) (Q3). Under (a), the work is documentation: how a phone reaches a LAN host. The server binds `localhost` by default, so the phone needs `--host <LAN or VPN address>`, which exposes the EEG stream to that network. Whether the server authenticates clients was not established in this pass (unknown); check before recommending LAN use. | `README_LINUX.md` (L7) | Decision recorded; under (a) nothing more here. |
| U1 | **Spike M-UT** (a local label, not a program id; 0.5 week; only if (b) is chosen). On the owner's device: `/proc/modules` or `modinfo rfcomm`; `python3 -c "import socket; socket.AF_BLUETOOTH"`; a small test click with the `bluetooth` group attempting an RFCOMM connect to the paired headset; the same under the `unconfined` template to separate policy from kernel; BlueZ version and whether bleak sees the device. | Test click outside the repo | Written verdict, NDV. If the kernel lacks `rfcomm`, stop: shape (b) is **D-defer** and only (a) stands. |
| U2 | Only if U1 passes: `ubuntu-touch/` with `manifest.json.in`, an AppArmor policy (`networking`, `bluetooth`, `keep-display-on`), `clickable.yaml`, one QML page, and `pyotherside` glue that imports `mw75_streamer` (nothing copied, per §3). No click package name is written until it has a NAMES.md row (R11, OQ-25); use a placeholder. | `ubuntu-touch/` (fork-only) | Clickable build passes in CI: `CI-APPROX — NOT DEVICE EVIDENCE`. |
| U3 | CI lane: compile-only on PRs, SHA-pinned actions, digest-pinned Clickable image, no artefact upload (R6). | New `.github/workflows/ut-click.yml` | Green; this container cannot build a click. |
| U4 | Front-panel rules: status is shape plus word, never colour alone; no dependency on Hyle tokens (F1 waits on OQ-17). The panel states "Foreground only: capture pauses when the app loses focus" and reports counter gaps instead of hiding them. Keep the QML to one page, since Qt 5.15 needs a Qt 6 rebuild later. | `ubuntu-touch/qml/` | Visible in the UI text; device behaviour NDV. |
| U5 | Owner checklist: install by sideload (or OpenStore after manual review), pair in system settings, a 10-minute foreground capture with the display kept on, then lock and refocus and record the gaps. | Owner device | NDV; ledger. |

### 6.5 iOS / iPadOS

| Step | Work | Done when |
|---|---|---|
| I1 | Record the reason (§4) and, in L7's docs pass, one sentence in `docs-src/protocol.rst` so upstream users stop asking. Revisit only if the headset exposes BLE GATT data or an MFi protocol. | `NOT-APPLICABLE (no third-party Bluetooth Classic RFCOMM on iOS)`. |

### 6.6 Evidence ledger (fork-only; update only your own rows)

| Item | Label today | Needed to advance |
|---|---|---|
| macOS real-device streaming on `main` | Not verified by the owner; `CI (hosted VM)` import checks only | NOV on macOS 26 |
| Linux backend (PR #1) | `CI (hosted VM)` (imports, type checks); not hardware-verified | NDV: Steam Deck, Debian host, Pi |
| Windows backend (PR #3) | `CI (hosted VM)`; not hardware-verified | NDV: Windows 10/11 with BR/EDR |
| `server/` real-device path off darwin | Does not exist | L3, then NDV |
| Ubuntu Touch capture (shape b) | PLAN | U1 verdict (NDV), then `CI-APPROX` build |
| iOS / iPadOS | `NOT-APPLICABLE` | — |

## 7. Shared foundation this repo consumes or provides

This is a Python repo outside the Kotlin and Hyle waves, so it consumes little of the program's §6.

**Consumes**
- **F11 (evidence scheme and device checklists):** the `DEVICE_CHECKLIST_{UT,LINUX,MACOS,WINDOWS}.md` templates
  seed the owner checklists in L8, W3, M2 and U5; today those live in PR bodies and `README_*.md`.
- **F7 (ubuntu-touch-shell), partly:** the OpenStore account and policy and `DEVICE_CHECKLIST_UT.md`. Its
  manifest templates are "common groups only" and JVM-oriented, so they do not fit: this click needs the
  reserved `bluetooth` group and Python, hence its own policy file (U2). Sharing mechanism per OQ-24.
- **F9 (CI matrix), concepts only:** `kmp-matrix.yml` is Kotlin-shaped and not consumed. This repo adopts its
  rules: SHA-pinned actions, an `ubuntu-24.04-arm` lane, the R3 Windows path lint, no artefact uploads.
- **F6 (platform-ports):** not consumed. This repo's factory is the Python reference for the Bluetooth RFCOMM
  seam F6 specifies for Kotlin.
- Not consumed: F1, F2, F3, F4, F5, F8, F10, F12 (no Hyle, no Kotlin, no native engines, no packaging
  templates unless Q12 changes that).

**Provides**
- The **WebSocket JSON stream** to Ebbflow (desktop on Linux, macOS and Windows; a LAN viewer on UT and iOS) and
  to Baseline. Ebbflow's plan names PR #1/#3 as its desktop dependency (OQ-13, OQ-23).
- A **frozen, versioned WebSocket schema document plus a CI check** (L2's golden list is the seed), which
  today exists only in PR bodies and `streamer_port_plan.md`. Where it lives is part of Q6; proposed, not ruled.
- `config.py` as the canonical constants source; a generator for Ebbflow's `Mw75Constants.kt` is a proposal in Q5.
- Hardware-verification results for F11's matrix: headset plus Steam Deck, Debian host, Pi, Windows box, Mac.
- A fork-safe release policy (Q8), per-OS liblsl notes (L7), and an upstream contribution lane (L9).

## 8. Open questions for the owner

1. **Merge strategy and Windows stance (OQ-13).** Rebase PR #1 then retarget PR #3, or fold both into one
   multi-platform PR to arctop? Should Windows ship upstream as "experimental, unverified", or wait for
   hardware? *Blocks:* L1, W1, the upstream PR, P-LX and P-win.
2. **Validation hardware (OQ-5).** Which Linux hosts will you verify on (Steam Deck, Debian homelab, which
   Raspberry Pi model)? Is there a Windows 10/11 box with a BR/EDR adapter, and a Mac? *Blocks:* L8, W3, M2.
3. **Ubuntu Touch shape (OQ-1).** Is the phone consuming the Linux streamer over WebSocket from a Pi (shape
   (a), nothing built here) enough, or do you want on-phone capture (shape (b), ≈ 4 weeks, contingent on a
   spike)? Which UT device do you own, and do `modinfo rfcomm` and `socket.AF_BLUETOOTH` work on it? Is a
   LAN-exposed, possibly unauthenticated EEG stream acceptable for (a)? *Blocks:* U0–U5.
4. **iOS.** Confirm not-applicable for this repo (no RFCOMM without MFi) and that the iOS shape is an Ebbflow
   client. *Blocks:* nothing; closes I1.
5. **Parsing canonicality (OQ-23).** `DECISIONS.md` says never re-implement parsing elsewhere, yet
   Ebbflow's `core-eeg-community` (`PacketParser.kt`, `Mw75Constants.kt`, `Mw75RfcommConnection.kt`) does, per
   `baseline/docs/PR_DISPOSITION.md`. Is Android/Kotlin the accepted exception, with this repo canonical for
   desktop OSes only? Should the Kotlin constants be generated from `config.py`? Ebbflow has no `LICENSE` (OQ-12), which
   matters if constants are generated into it. *Blocks:* Ebbflow desktop rows; the §3 canonicality wording.
6. **`server/` in scope (OQ-13, OQ-23).** Make the WebSocket control server's real-device path cross-platform
   in the same PR? Both drafts deferred it, and `streamer_port_plan.md` lists `server/` as "Untouched". This
   plan proposes changing only its internal pump with a byte-identical wire format. Also where the schema
   document and its CI check should live. *Blocks:* L3, W5 and Ebbflow's Linux and Windows desktop use.
7. **Plan location and stale text.** Confirm a root, fork-only `PORTING_PLAN.md` (alternative: keep it in
   Personal-Tracker, or publish as `docs-src/porting.rst`). `README.md` still says "Windows is still
   unimplemented" and `CONSTELLATION.md` says "Windows TODO" although PR #3 exists; this pass only added a
   pointer line. Correct both? *Blocks:* nothing technical.
8. **Release guard.** Confirm the fork never pushes `v*` tags, or should `build-and-publish` be guarded or
   disabled on the fork? *Blocks:* any release or version bump from the fork.
9. **Priority tuning.** Linux (`nice`, `SCHED_FIFO`) and Windows (`SetPriorityClass`) boosts, added only if
   measured against drop rates on your hosts, or left out of the upstream PR? *Blocks:* L4, W4.
10. **Upstream etiquette.** Open the arctop PR now as a draft (the contribution-back gesture), or only after
    your hardware verification? *Blocks:* L9.
11. **CI shape (OQ-20).** Accept the R3 exception for the two drafts' `ci.yml` edits? Add `tests.yml` and
    `linux-arm.yml` as new files? Should `.github/settings.yml` required checks gain the Linux and Windows jobs
    (edits upstream-facing config)? Actions artifact storage is exhausted account-wide (the six-hourly
    cleanup workflow), so each added matrix job must upload nothing. *Blocks:* L2, L5, U3, W1.
12. **Packaging beyond PyPI (OQ-3, OQ-4).** The program's §4.4 and P-mac row mention a Briefcase package for this
    repo and §4.6 says PyInstaller per OS, while the repo ships a pip-installed CLI. Is anything beyond PyPI
    wanted (a frozen `.exe` or macOS binary would be unsigned, R6)? *Blocks:* M3-type work; none planned.
13. **I-3 scope (OQ-26).** Does the violet/cyan plus shape rule bind this fork's panel HTML (upstream-authored,
    green and red buttons with word labels) and the UT front panel? *Blocks:* any panel change; U4's styling.

## 9. Sources read

- This repo: `README.md`, `CONTRIBUTING.md`, `LICENSE`, `pyproject.toml`, `requirements.txt`, `uv.lock` (bleak
  block and platform markers), `Makefile`, `.flake8`, `pyrightconfig.json`, `.gitignore`.
- `.github/workflows/ci.yml`, `docs.yml`, `cleanup-artifacts.yml`; `.github/settings.yml`;
  `.github/PULL_REQUEST_TEMPLATE.md`; `docs/_config.yml`; `docs-src/protocol.rst`, `index.rst`;
  `examples/README.md` (lines 200-235).
- `mw75_streamer/__init__.py`, `config.py`, `main.py`, `device/__init__.py`, `rfcomm_manager.py`,
  `mw75_device.py`, `ble_manager.py`, `mock_rfcomm_manager.py`, `server/__main__.py`, `server/ws_server.py`
  (lines 1-140, 666-760, 896-915 and the symbol index), `utils/logging.py`, and the import headers of
  `data/packet_processor.py`, `data/streamers.py`, `panel/panel_server.py`, `testing/*.py`.
- GitHub, read-only: PR #1, #2, #3, #4 metadata, bodies, file lists and check runs; on
  `claude/cool-galileo-6AX0j` the files `device/rfcomm_manager_linux.py` and `README_LINUX.md`; on
  `claude/mw75-windows-rfcomm` the files `device/rfcomm_backend.py` and `device/rfcomm_manager_windows.py`.
- Constellation: `Ebbflow/docs/streamer_port_plan.md` (identical copy in `baseline/docs/`),
  `Ebbflow/build_plan.md` §1 and layout (copy in `baseline/`), `Ebbflow/docs/session_handoff.md`,
  `Ebbflow/app/README.md`, `Ebbflow/app/src/main/kotlin/ai/ebbflow/baseline/app/bluetooth/Mw75RfcommConnection.kt`,
  `Ebbflow/core-eeg-community/src/main/kotlin/ai/ebbflow/eeg/Mw75Constants.kt`, `baseline/docs/PR_DISPOSITION.md`,
  `Personal-Tracker/CONSTELLATION.md`, `DECISIONS.md` (2026-07-06), `STATE.md`, `Form-analyser/docs/architecture.md`,
  `asystemofcells/packages/roster/roster.public.json`, and `Personal-Tracker/PORTING_PROGRAM.md` (§0–§3, §4,
  this repo's §5 row, §6, §7, §8).

## Owner rulings and the proposed line (added 2026-10-07)

Status: PLAN. Nothing here is built, run on a device, signed or submitted. The program-level plan is Personal-Tracker `PORTING_PROGRAM.md` ([PR #10](https://github.com/mbaliga/Personal-Tracker/pull/10)), which holds the owner's rulings and section 5A, the proposed port / no-port line. The cells, estimates and open questions above are this repo's original plan and are unedited. Where the owner has since answered a question, the answer is below. Section 5A is a proposal; the owner has not yet confirmed it.

### Where mw75-streamer sits in the proposed line (program section 5A.3, a proposal)

| Target       | Verdict    | Weeks and flags |
| ------------ | ---------- | --------------- |
| Ubuntu Touch | owner-call | 4w g            |
| Linux        | port       | 1.5w            |
| iOS/iPadOS   | no-port    | -               |
| macOS        | exists     | 0.2w            |
| Windows      | port       | 2w              |

Key: `follows` means it ports only as far as the products that depend on it; `exists` means the program reads it as already running there, unverified (finish, verify and sign); `owner-call` means a genuine toss-up that the owner decides, with the program's lean in section 5A.4; flags: `g` gated on a prerequisite, `r` re-estimate or floor, `o` its own program, `s` scope note. The program's P4, P8, P12 and P13 gate whole columns or repos and are not flagged per cell. A port verdict counts the deliverable in the line; where this repo's plan calls a deliverable a reframe (program rule R12) it keeps that label. Tests cited in the reason: (a) the owner said it is needed there; (b) its job is really done on that OS by real users; (c) that OS is where it is sold or its audience is; it has no reason to exist if (x) its surface is absent or untouchable, (y) the capability is forbidden or impossible, or (z) the only form is a thin wrapper or a different product nobody asked for. P-numbers and OQ-numbers refer to the program plan (Personal-Tracker `PORTING_PROGRAM.md`, sections 5A.5 and 8).

Reason: A sidecar that reads EEG over RFCOMM (PT:D-S, the owner's EEG-stack decision): Linux and Windows are ports, macOS exists, iOS is impossible. UT is a call with no lean until you say whether you want it (clause a): the program's own UT brief says a confined click with the reserved bluetooth group can do it foreground-only, but a pocket capture click is a different product from the headless streamer (z), and it needs you to own the MW75. The 4 weeks are this plan's shape (b), on-phone capture; its recommended shape (a), a phone as a WebSocket client of the Linux build, would be Ebbflow's click and costs 0 weeks here; the program line has Ebbflow's Ubuntu Touch cell as no-port (its LAN viewer is the substitute the Ubuntu Touch scope ruling excludes), so shape (a) is not counted in the line.

### Owner rulings that apply here

- **Ubuntu Touch device:** the owner owns one and says it is a OnePlus 6; research reads it as 20.04-only while the program plan targets 24.04. On 2026-10-07 the owner chose "OnePlus 6 pre-spike now, decide later" (OQ-37): a labelled "S-UT1 (focal)" headless-JVM pre-spike, no 24.04 flashing, a 24.04 device decision afterwards. Every Ubuntu Touch device gate stays NDV until then. The pre-spike tests a headless JVM and does not exercise this repo's shape (Python plus QML).
- **OQ-31 Mac (2026-10-06 and 2026-10-07):** "Buy a Mac", and on 2026-10-07 an Apple-silicon Mac mini, not yet bought. mw75-streamer has no iOS port and its macOS cell is a pip-installed CLI with no store listing, so only the Mac statement applies. The macOS re-verification stays NOV until the Mac exists.
- **OQ-20 CI (2026-10-06):** "Linux-only CI when private (Recommended)": this repo is public, so the ruling does not limit its macOS and Windows lanes; going private would stop them. Actions artifact storage is still exhausted (program rule R6). Each added matrix job uploads nothing (this plan, question 11).
- **OQ-5 hardware (2026-10-06):** the owner's answer changes which of their other machines can serve as device gates, so a gate this plan names on specific hardware may be moved or dropped. Which machine carries which device gate is not decided (OQ-33).
- **Repo-specific:** this fork has an MIT LICENSE inherited from arctop; the gap OQ-12 names is Ebbflow's.
- **Directives (2026-10-06):** "Draft amendments for approval": program directives I-1 to I-12 and rules R1 to R12 are unchanged; PROPOSED-1 to PROPOSED-4 in Personal-Tracker `DECISIONS.md` are drafts awaiting the owner.

### Prerequisites and open questions that touch this repo (program sections 5A.5 and 8)

Prerequisites (program-level; not costed here):

- program P4: A device that can run the 24.04 Ubuntu Touch the program plan targets (the owner's OnePlus 6 is read as 20.04-only)
- program P8: An Apple-silicon Mac (OQ-31: a Mac mini chosen on 2026-10-07, not yet bought); here it matters only for the owner re-verification on macOS 26 (plan step M2, NOV)
- program P15: A 0.5-week RFCOMM spike on a device

Owner questions in the program register that concern this repo (status as of 2026-10-07):

- OQ-5 (ruled): Hardware stance
- OQ-12 (open): Licences for repos without a LICENSE
- OQ-13 (open): mw75-streamer: merge strategy for PRs #1 and #3
- OQ-20 (ruled): CI minutes, storage and repo visibility
- OQ-23 (open): EEG canonical transport layer per OS (D-S: the streamer layer lives in mw75-streamer)
- OQ-31 (ruled): CI for App Store builds; which Mac
- OQ-33 (open): Hardware details still open
- OQ-37 (answered in part): A second Ubuntu Touch device

When the owner confirms or changes the line, this repo's original cells above stay as the engineering detail; only the verdicts and re-costs in program section 5A change.
