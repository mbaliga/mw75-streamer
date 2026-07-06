# MW75 EEG Streamer on Windows

This document covers running the MW75 EEG streamer on **Windows**. Windows is
supported as a real-device platform alongside macOS and Linux; the cross-platform
mock mode (`--mock`) works everywhere.

> **Status: not yet hardware-verified.** The Windows RFCOMM backend is wired up
> and passes CI (imports, factory selection, static analysis), but it has **not**
> been validated against a real MW75 over Windows Bluetooth on real hardware.
> Treat streaming as experimental until confirmed on-device. This mirrors how the
> Linux port (PR #1) was staged. If you test it on hardware, please report back.

## How it works

The MW75 link has two phases:

1. **BLE activation** — discovery and the enable-EEG/raw-mode handshake run
   through [`bleak`](https://github.com/hbldh/bleak), which supports Windows
   (WinRT). This phase is unchanged from macOS/Linux.
2. **RFCOMM streaming** — EEG data streams over a Bluetooth Classic RFCOMM
   channel (channel 25). On Windows this uses the Python standard library's
   `socket.socket(AF_BTH, SOCK_STREAM, BTPROTO_RFCOMM)` (Winsock Bluetooth). No
   `pybluez` or other third-party socket library is required.

The platform-specific RFCOMM backend is selected lazily, so neither the macOS
PyObjC stack nor the Linux `dbus_fast` stack is imported on Windows.

## Requirements

- Windows 10/11 with a Bluetooth adapter that supports **BR/EDR (Bluetooth
  Classic)**, not just BLE.
- Python **3.9+** (standard CPython Windows build — `AF_BTH` / `BTPROTO_RFCOMM`
  are included).
- The MW75 **paired** in Windows Bluetooth settings.

## Providing the device address (v1)

Automatic paired-device enumeration via the Win32 Bluetooth API is a planned
follow-up (it needs validation on real Windows hardware). For now, supply the
MW75's Bluetooth **Classic** address explicitly via the `MW75_BT_ADDR`
environment variable — the same override the macOS and Linux backends accept:

```powershell
# Find the address (Settings > Bluetooth & devices > device > Properties, or):
Get-PnpDevice -Class Bluetooth | Format-List FriendlyName, InstanceId

# PowerShell:
$env:MW75_BT_ADDR = "AA:BB:CC:DD:EE:FF"
mw75-streamer --websocket

# cmd.exe:
set MW75_BT_ADDR=AA:BB:CC:DD:EE:FF
mw75-streamer --websocket
```

Either the bare (`AA:BB:CC:DD:EE:FF`) or parenthesised (`(AA:BB:CC:DD:EE:FF)`)
form is accepted; the backend normalises it for Winsock.

## Development without hardware

Everything except the live RFCOMM read works cross-platform with mock mode:

```powershell
mw75-streamer --mock --websocket
```

## Contributing back upstream

This Windows support is intended to be **upstreamable** to
[`arctop/mw75-streamer`](https://github.com/arctop/mw75-streamer). The WebSocket
JSON schema, packet parsing, and BLE activation are untouched; the change is an
additive platform backend plus its factory wiring and CI checks.
