# MW75 EEG Streamer on Linux

This document covers running the MW75 EEG streamer on Linux. Linux is supported
as a real-device platform alongside macOS; the cross-platform mock mode
(`--mock`) works everywhere.

## How it works

The MW75 link has two phases, both handled cross-platform:

1. **BLE activation** — discovery and the enable-EEG/raw-mode handshake run
   through [`bleak`](https://github.com/hbldh/bleak), which already supports
   Linux (BlueZ). This phase is unchanged from macOS.
2. **RFCOMM streaming** — EEG data streams over a Bluetooth Classic RFCOMM
   channel (channel 25). On Linux this uses the Python standard library's
   `socket.socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM)` (backed by BlueZ).
   No `pybluez` or other third-party socket library is required.

The paired device's Bluetooth Classic address is resolved from BlueZ over D-Bus
(via `dbus-fast`, already a dependency of `bleak` on Linux), mirroring the macOS
`IOBluetoothDevice.pairedDevices()` lookup by name.

The platform-specific RFCOMM backend is selected lazily, so the macOS PyObjC
stack is never imported on Linux (and vice versa).

## Requirements

- Linux with **BlueZ** (`bluetoothd` running) and a Bluetooth adapter that
  supports **BR/EDR (Bluetooth Classic)**, not just BLE.
- Python **3.9+**. The standard CPython Linux build includes `AF_BLUETOOTH`
  socket support; verify with:
  ```bash
  python3 -c "import socket; print(hasattr(socket, 'AF_BLUETOOTH'))"  # -> True
  ```
- BlueZ command-line tools (`bluetoothctl`) for pairing.

Target platforms: Steam Deck (Arch), a Debian homelab server, and **Raspberry Pi**
(Raspberry Pi OS) — see [Raspberry Pi](#raspberry-pi) below. The backend is pure
standard-library `AF_BLUETOOTH` RFCOMM + BlueZ, with no architecture-specific
code, so the same path runs on x86-64 and ARM (aarch64/armhf) alike.

## Raspberry Pi

The Raspberry Pi is a first-class target — a headless Pi makes a natural always-on
host that streams the MW75 and forwards EEG (WebSocket/LSL) to whatever consumes it.
Nothing Pi-specific is needed in code; the notes below are just setup.

- **Hardware.** A Pi with onboard Bluetooth (Pi 3/4/5, Zero 2 W) or a USB BT
  dongle — it must support **BR/EDR (Bluetooth Classic)**, not BLE-only, because
  RFCOMM rides on Classic. The onboard controllers on Pi 3/4/5 do.
- **OS / Python.** Raspberry Pi OS (Bookworm ships Python 3.11; Bullseye 3.9) —
  both meet the 3.9+ floor. 64-bit is recommended but not required.
- **Enable Bluetooth (headless):**
  ```bash
  sudo rfkill unblock bluetooth
  sudo systemctl enable --now bluetooth
  bluetoothctl show      # expect "Powered: yes" and BR/EDR (not LE-only)
  ```
- **Permissions.** So the streamer can reach BlueZ on the system D-Bus without
  root, add your user to the `bluetooth` group once, then re-login:
  ```bash
  sudo usermod -aG bluetooth "$USER"
  ```
- **Pair over SSH.** Pairing is the same `bluetoothctl` flow as above — no display
  needed; run it over SSH.
- **Pin the address for boot/kiosk.** On a headless Pi, skip name lookup by
  exporting the Classic address (e.g. in the systemd unit below):
  ```bash
  export MW75_BT_ADDR=AA:BB:CC:DD:EE:FF
  ```
- **Autostart (optional).** A minimal user/system service:
  ```ini
  # /etc/systemd/system/mw75.service
  [Unit]
  Description=MW75 EEG streamer
  After=bluetooth.target
  Wants=bluetooth.target

  [Service]
  Environment=MW75_BT_ADDR=AA:BB:CC:DD:EE:FF
  ExecStart=/home/pi/.venv/bin/mw75-streamer --websocket ws://localhost:8080
  Restart=on-failure
  User=pi

  [Install]
  WantedBy=multi-user.target
  ```
  ```bash
  sudo systemctl enable --now mw75.service
  ```

> 500 Hz × 12 channels is a light load — even a Pi Zero 2 W handles it. On-device
> verification (BLE activation + a clean multi-minute RFCOMM stream on a real Pi +
> MW75) is still pending, same as the other Linux targets.

## Install

```bash
# from a clone of this repo
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[websocket]"      # add ,lsl for Lab Streaming Layer output
```

`dbus-fast` is installed automatically on Linux (it is a dependency of `bleak`).

## Pairing the MW75 (one-time)

Pairing is a manual prerequisite on Linux, just as it is on macOS. Put the MW75
into pairing mode (power on, then hold the pairing button per Master & Dynamic's
instructions) and run:

```bash
bluetoothctl
```

Then inside the `bluetoothctl` prompt:

```
power on
agent on
default-agent
scan on
# wait until a line like "[NEW] Device AA:BB:CC:DD:EE:FF MW75" appears, then:
scan off
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
quit
```

Replace `AA:BB:CC:DD:EE:FF` with your headset's address. Once paired and
trusted, the streamer can find the device by name on subsequent runs.

## Running

Mock mode (no hardware, validates the full pipeline):

```bash
mw75-streamer --mock                       # EEG to stdout
mw75-streamer --mock --websocket ws://localhost:8080
```

Real device:

```bash
mw75-streamer                              # EEG to stdout (CSV columns)
mw75-streamer --csv eeg.csv                # write EEG CSV
mw75-streamer --websocket ws://localhost:8080
mw75-streamer --lsl MW75_EEG               # Lab Streaming Layer (needs [lsl] extra)
```

Press `Ctrl+C` to stop; the streamer disables EEG mode and disconnects cleanly.

### Overriding address resolution

If name-based lookup fails (or you want to pin a specific headset), set the
Classic address explicitly and the BlueZ lookup is skipped:

```bash
MW75_BT_ADDR=AA:BB:CC:DD:EE:FF mw75-streamer
```

## Permissions

Opening an RFCOMM socket to an already-paired device typically does **not**
require root. If you hit a permission error, ensure your user is in the
`bluetooth` group (some distros) and that `bluetoothd` is running:

```bash
systemctl status bluetooth
```

The streamer also tries to raise its process priority for smoother real-time
streaming; this is best-effort and silently degrades without privileges.

## Troubleshooting

- **"No paired device found matching 'MW75'"** — pair and `trust` the device via
  `bluetoothctl` first (see above). Confirm it shows under `paired-devices`.
- **"Failed to query BlueZ for paired devices"** — ensure `bluetoothd` is
  running and reachable on the system D-Bus. As a workaround, pass the address
  directly with `MW75_BT_ADDR`.
- **RFCOMM connection fails / times out** — make sure the headset is on, in
  range, and connected at the Classic layer. Re-`connect` it in `bluetoothctl`.
  Confirm the adapter supports BR/EDR (`bluetoothctl show` → `Powered: yes` and
  not LE-only).
- **`AF_BLUETOOTH` missing** — your Python was built without Bluetooth socket
  support (uncommon on Linux). Install/Use a standard distro CPython.

## Notes and known differences from macOS

- **BLE disconnect before RFCOMM.** The coordinator disconnects BLE after
  activation before opening RFCOMM. This step is labelled a macOS (Taho)
  compatibility workaround in the source. On Linux it is retained and appears
  harmless (BLE and Classic are separate transports under BlueZ); confirm during
  hardware testing and remove for Linux if it proves unnecessary.
- **BLE vs. Classic address.** This backend resolves the **Classic** `bd_addr`
  from BlueZ paired devices by name rather than assuming it equals the BLE
  advertising address. On dual-mode headsets the two are often identical, but
  resolving from paired devices matches the macOS behaviour and avoids relying
  on that assumption.
- **WebSocket control server.** The optional control server
  (`python -m mw75_streamer.server`) supports mock mode on Linux; its
  real-device path is currently macOS-only and is a candidate follow-up. The
  primary `mw75-streamer` CLI supports real devices on Linux. The emitted
  WebSocket/CSV/LSL data formats are unchanged across platforms.
```
