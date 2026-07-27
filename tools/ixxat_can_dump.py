#!/usr/bin/env python3
import json
import os
import sys
import time

# project-local fallback for python-can
sys.path.insert(0, "/app/vendor/python")

import can

# python-can ixxat backend workaround:
# some environments fail to expose can.ctypesutil.HRESULT even though backend expects it
try:
    import can.ctypesutil as _cu
    if not hasattr(_cu, "HRESULT"):
        import ctypes
        class HRESULT(ctypes.c_long):
            pass
        _cu.HRESULT = HRESULT
except Exception:
    pass


def env_int(name, default):
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return int(v)


def env_bool(name, default):
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.lower() in ("1", "true", "yes", "on")


BITRATE = env_int("IXXAT_BITRATE", 500000)
DATA_BITRATE = env_int("IXXAT_DATA_BITRATE", 2000000)
FD = env_bool("IXXAT_FD", True)
CHANNEL = os.getenv("IXXAT_CHANNEL", "0")
SOCKETCAN_IF = os.getenv("SOCKETCAN_IF", "can0")


def log(msg):
    print(json.dumps({"type": "log", "msg": msg}, ensure_ascii=False), flush=True)


def msg_to_json(msg):
    return {
        "type": "frame",
        "ts": getattr(msg, "timestamp", time.time()),
        "can_id": f"0x{int(msg.arbitration_id):X}",
        "is_extended_id": bool(getattr(msg, "is_extended_id", False)),
        "is_remote_frame": bool(getattr(msg, "is_remote_frame", False)),
        "is_error_frame": bool(getattr(msg, "is_error_frame", False)),
        "is_fd": bool(getattr(msg, "is_fd", False)),
        "bitrate_switch": bool(getattr(msg, "bitrate_switch", False)),
        "error_state_indicator": bool(getattr(msg, "error_state_indicator", False)),
        "dlc": int(getattr(msg, "dlc", len(getattr(msg, "data", b"")))),
        "data_hex": bytes(getattr(msg, "data", b"")).hex().upper(),
        "channel": str(getattr(msg, "channel", "")),
    }


def try_open_ixxat():
    errors = []
    attempts = [
        {"interface": "ixxat", "channel": 0, "fd": FD, "bitrate": BITRATE, "data_bitrate": DATA_BITRATE},
        {"interface": "ixxat", "channel": CHANNEL, "fd": FD, "bitrate": BITRATE, "data_bitrate": DATA_BITRATE},
        {"interface": "ixxat", "channel": 0, "bitrate": BITRATE},
        {"interface": "ixxat", "channel": CHANNEL, "bitrate": BITRATE},
    ]
    for kwargs in attempts:
        try:
            bus = can.Bus(**kwargs)
            log(f"OPEN_OK ixxat {kwargs}")
            return bus
        except Exception as e:
            errors.append(f"{kwargs} -> {repr(e)}")
    raise RuntimeError(" ; ".join(errors))


def try_open_socketcan():
    errors = []
    attempts = [
        {"interface": "socketcan", "channel": SOCKETCAN_IF, "fd": FD},
        {"interface": "socketcan", "channel": SOCKETCAN_IF},
    ]
    for kwargs in attempts:
        try:
            bus = can.Bus(**kwargs)
            log(f"OPEN_OK socketcan {kwargs}")
            return bus
        except Exception as e:
            errors.append(f"{kwargs} -> {repr(e)}")
    raise RuntimeError(" ; ".join(errors))


def main():
    backend = os.getenv("CAN_BACKEND", "ixxat").strip().lower()

    bus = None
    if backend == "ixxat":
        bus = try_open_ixxat()
    elif backend == "socketcan":
        bus = try_open_socketcan()
    elif backend == "auto":
        try:
            bus = try_open_ixxat()
        except Exception as e1:
            log(f"ixxat open failed: {e1}")
            bus = try_open_socketcan()
    else:
        raise RuntimeError(f"unknown CAN_BACKEND={backend}")

    while True:
        msg = bus.recv(timeout=1.0)
        if msg is None:
            continue
        print(json.dumps(msg_to_json(msg), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(json.dumps({"type": "fatal", "error": repr(e)}, ensure_ascii=False), flush=True)
        raise
