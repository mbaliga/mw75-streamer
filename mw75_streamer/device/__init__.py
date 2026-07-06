"""
MW75 Device Management

Modules for handling MW75 device connections, BLE activation, and RFCOMM streaming.
"""

import sys
from typing import List

# BLEManager and MW75Device are cross-platform (BLE via bleak, RFCOMM via the
# lazy platform backend), so they import on every supported OS.
from .ble_manager import BLEManager  # noqa: F401
from .mw75_device import MW75Device  # noqa: F401
from .rfcomm_backend import create_rfcomm_manager  # noqa: F401

__all__: List[str] = ["BLEManager", "MW75Device", "create_rfcomm_manager"]

if sys.platform == "darwin":
    from .rfcomm_manager import RFCOMMManager, RFCOMMDelegate  # noqa: F401

    __all__ += ["RFCOMMManager", "RFCOMMDelegate"]
elif sys.platform == "linux":
    from .rfcomm_manager_linux import LinuxRFCOMMManager  # noqa: F401

    __all__ += ["LinuxRFCOMMManager"]
elif sys.platform == "win32":
    from .rfcomm_manager_windows import WindowsRFCOMMManager  # noqa: F401

    __all__ += ["WindowsRFCOMMManager"]
