import time
import socket
import struct
import threading
import subprocess
from typing import Any, Dict, List, Optional

from app.core.config import load_config
from app.runtime.bus import STATE


def _parse_can_id(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(s, 10)
    except Exception:
        return None


def _to_signed(value: int, bits: int) -> int:
    if bits <= 0:
        return value
    sign_bit = 1 << (bits - 1)
    return (value ^ sign_bit) - sign_bit


def _extract_intel(data: bytes, byte_pos_1based: int, bit_pos: int, length: int) -> int:
    u = int.from_bytes(data, byteorder="little", signed=False)
    start = (byte_pos_1based - 1) * 8 + bit_pos
    mask = (1 << length) - 1
    return (u >> start) & mask


def _extract_motorola(data: bytes, byte_pos_1based: int, bit_pos: int, length: int) -> int:
    # Motorola(Big Endian) bit extraction
    # byte is 1-based, bit is 0..7 where 7=MSB, 0=LSB in the OEM-style table.
    # We treat the given (byte, bit) as the start bit, then walk toward lower bit
    # positions; when crossing a byte boundary, move to the next byte and restart at bit 7.
    if length <= 0:
        return 0

    byte_index = byte_pos_1based - 1
    cur_bit = bit_pos

    value = 0
    for _ in range(length):
        if byte_index < 0 or byte_index >= len(data) or cur_bit < 0 or cur_bit > 7:
            return 0
        bit_val = (data[byte_index] >> cur_bit) & 1
        value = (value << 1) | bit_val

        if cur_bit == 0:
            byte_index += 1
            cur_bit = 7
        else:
            cur_bit -= 1

    return value


def _extract_signal(data: bytes, byte_pos_1based: int, bit_pos: int, length: int, endian: str) -> int:
    e = (endian or "intel").lower()
    if e in ("motorola", "big", "be", "big_endian"):
        return _extract_motorola(data, byte_pos_1based, bit_pos, length)
    return _extract_intel(data, byte_pos_1based, bit_pos, length)


def _decode_one_signal(data: bytes, sig: Dict[str, Any], default_endian: str = "intel") -> Optional[Dict[str, Any]]:
    can_id = _parse_can_id(sig.get("can_id"))
    byte_pos = sig.get("byte")
    bit_pos = sig.get("bit")
    length = sig.get("length")

    if can_id is None or byte_pos is None or bit_pos is None or length is None:
        return None

    byte_pos = int(byte_pos)
    bit_pos = int(bit_pos)
    length = int(length)

    endian = str(sig.get("endian") or default_endian or "intel")
    signed = bool(sig.get("signed", False))
    resolution = float(sig.get("resolution", 1.0) or 1.0)
    offset = float(sig.get("offset", 0.0) or 0.0)

    raw = _extract_signal(
        data=data,
        byte_pos_1based=byte_pos,
        bit_pos=bit_pos,
        length=length,
        endian=endian,
    )

    raw_signed = _to_signed(raw, length) if signed else raw
    physical = raw_signed * resolution + offset

    return {
        "can_id": can_id,
        "label": sig.get("label"),
        "name_en": sig.get("name_en"),
        "name_jp": sig.get("name_jp"),
        "unit": sig.get("unit", "-"),
        "byte": byte_pos,
        "bit": bit_pos,
        "length": length,
        "endian": endian,
        "signed": signed,
        "resolution": resolution,
        "offset": offset,
        "raw": raw_signed,
        "physical": physical,
    }


def _can_frame_to_dict(frame: bytes) -> Dict[str, Any]:
    can_id, dlc = struct.unpack("=IB3x", frame[:8])
    data = frame[8:8 + min(int(dlc), max(0, len(frame) - 8))]
    return {
        "can_id": can_id & 0x1FFFFFFF,
        "dlc": int(dlc),
        "data": bytes(data),
        "data_hex": data.hex(),
    }


def _decode_configured_signals(can_id: int, data: bytes, sig_defs: List[Dict[str, Any]], default_endian: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for sig in sig_defs:
        sig_id = _parse_can_id(sig.get("can_id"))
        if sig_id is None or sig_id != can_id:
            continue
        dec = _decode_one_signal(data, sig, default_endian=default_endian)
        if dec is None:
            continue
        label = str(dec.get("label") or f"sig_{can_id:x}_{len(out)}")
        out[label] = dec
    return out


def _pick_shift(decoded: Dict[str, Dict[str, Any]]) -> Optional[str]:
    for label, val in decoded.items():
        raw = val.get("raw")
        if label == "B_P" and raw == 1:
            return "P"
        if label == "B_R" and raw == 1:
            return "R"
        if label == "B_N" and raw == 1:
            return "N"
        if label == "B_D" and raw == 1:
            return "D"
        if label == "B_B" and raw == 1:
            return "B"

    if "PTCURSFT" in decoded:
        raw = int(decoded["PTCURSFT"]["raw"])
        mapping = {
            0: "P",
            1: "R",
            2: "N",
            3: "D",
            4: "B",
        }
        return mapping.get(raw, str(raw))
    return None


def _publish_dummy_from_config(cfg: Dict[str, Any], cam_id: int = 0) -> None:
    d = ((cfg.get("can") or {}).get("dummy") or {})
    now = time.time()
    with STATE.lock:
        STATE.latest_can_status[cam_id] = "OK"
        STATE.latest_can_ts[cam_id] = now
        STATE.latest_can_error[cam_id] = None
        STATE.latest_can_iface[cam_id] = "dummy"
        STATE.latest_can_rx_count[cam_id] = int((STATE.latest_can_rx_count.get(cam_id, 0) or 0))

        STATE.latest_vehicle_speed[cam_id] = float(d.get("vehicle_speed", 0.0) or 0.0)
        STATE.latest_shift[cam_id] = str(d.get("shift", "D"))
        STATE.latest_accel_xyz[cam_id] = {
            "x": float(d.get("accel_x", 0.0) or 0.0),
            "y": float(d.get("accel_y", 0.0) or 0.0),
            "z": float(d.get("accel_z", 0.0) or 0.0),
        }
        STATE.latest_pedal[cam_id] = {
            "accel": float(d.get("pedal_accel", 0.0) or 0.0),
            "brake": float(d.get("pedal_brake", 0.0) or 0.0),
        }
        STATE.latest_steering_rate[cam_id] = float(d.get("steering_rate", 0.0) or 0.0)
        STATE.latest_can_signals[cam_id] = {
            "dummy_vehicle_speed": {"raw": d.get("vehicle_speed"), "physical": d.get("vehicle_speed"), "unit": "km/h"},
            "dummy_shift": {"raw": d.get("shift"), "physical": d.get("shift"), "unit": "-"},
        }


class CanWorker(threading.Thread):
    daemon = True

    def __init__(self, can_id: int = 0):
        super().__init__()
        self.can_id = can_id
        self._stop_evt = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._proc: Optional[subprocess.Popen] = None
        self._last_mode: Optional[str] = None
        self._last_iface: Optional[str] = None

    def stop(self):
        self._stop_evt.set()
        self._close_sock()
        self._close_proc()

    def _close_sock(self):
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        self._sock = None

    def _close_proc(self):
        try:
            if self._proc is not None:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
        except Exception:
            try:
                if self._proc is not None:
                    self._proc.kill()
            except Exception:
                pass
        self._proc = None

    def _ensure_socket(self, iface: str):
        if self._sock is not None and self._last_iface == iface:
            return
        self._close_sock()
        s = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FD_FRAMES, 1)
        except Exception:
            pass
        s.settimeout(1.0)

        # kernel-level CAN ID filter: keep only signals used by the app
        try:
            filters = [
                (0x025, 0x7FF),  # SSA
                (0x090, 0x7FF),  # VSC_GX0
                (0x097, 0x7FF),  # PTCURSFT
                (0x0D7, 0x7FF),  # SP1
                (0x101, 0x7FF),  # WSTP / PMC
                (0x116, 0x7FF),  # HV_ACCP
                (0x3BF, 0x7FF),  # shift
            ]
            flt = b"".join(struct.pack("=II", can_id, can_mask) for can_id, can_mask in filters)
            s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, flt)
        except Exception:
            pass

        s.bind((iface,))
        self._sock = s
        self._last_iface = iface

    def run(self):
        cfg = {}
        ccfg = {}
        mode = "disabled"
        iface = "can0"
        default_endian = "intel"
        sig_defs = []
        next_cfg_reload = 0.0

        while not self._stop_evt.is_set():
            now_cfg = time.time()
            if now_cfg >= next_cfg_reload:
                cfg = load_config() or {}
                ccfg = cfg.get("can", {}) or {}
                mode = str(ccfg.get("mode", "disabled")).lower()
                iface = str(ccfg.get("interface", "can0"))
                default_endian = str(ccfg.get("endian_default", "intel"))
                sig_defs = list(ccfg.get("signals", []) or [])
                next_cfg_reload = now_cfg + 1.0

            if mode != self._last_mode:
                self._close_sock()
                self._last_mode = mode

            if mode == "disabled":
                with STATE.lock:
                    STATE.latest_can_status[self.can_id] = "DISABLED"
                    STATE.latest_can_error[self.can_id] = None
                    STATE.latest_can_iface[self.can_id] = iface
                time.sleep(0.5)
                continue

            if mode == "dummy":
                _publish_dummy_from_config(cfg, cam_id=self.can_id)
                time.sleep(0.2)
                continue

            if mode == "real_script":
                script_cmd = str(ccfg.get("script_cmd", "")).strip()
                if not script_cmd:
                    with STATE.lock:
                        STATE.latest_can_status[self.can_id] = "ERROR"
                        STATE.latest_can_error[self.can_id] = "can.script_cmd is empty"
                        STATE.latest_can_iface[self.can_id] = "ixxat-script"
                    time.sleep(1.0)
                    continue
                try:
                    if self._proc is None or self._proc.poll() is not None:
                        self._close_proc()
                        self._proc = subprocess.Popen(
                            script_cmd,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            bufsize=1,
                        )
                    assert self._proc.stdout is not None
                    line = self._proc.stdout.readline()
                    if not line:
                        time.sleep(0.05)
                        continue
                    now = time.time()
                    line = line.rstrip("\n")
                    with STATE.lock:
                        STATE.latest_can_status[self.can_id] = "OK"
                        STATE.latest_can_ts[self.can_id] = now
                        STATE.latest_can_error[self.can_id] = None
                        STATE.latest_can_iface[self.can_id] = "ixxat-script"
                        STATE.latest_can_rx_count[self.can_id] = int((STATE.latest_can_rx_count.get(self.can_id, 0) or 0) + 1)
                        STATE.latest_can_frame[self.can_id] = {
                            "raw_line": line,
                            "ts": now,
                        }
                    continue
                except Exception as e:
                    self._close_proc()
                    with STATE.lock:
                        STATE.latest_can_status[self.can_id] = "ERROR"
                        STATE.latest_can_error[self.can_id] = f"real_script: {e}"
                        STATE.latest_can_iface[self.can_id] = "ixxat-script"
                    time.sleep(1.0)
                    continue

            if mode != "real":
                with STATE.lock:
                    STATE.latest_can_status[self.can_id] = "INVALID MODE"
                    STATE.latest_can_error[self.can_id] = f"unknown can.mode={mode}"
                    STATE.latest_can_iface[self.can_id] = iface
                time.sleep(1.0)
                continue

            try:
                self._ensure_socket(iface)
                assert self._sock is not None
                frame = self._sock.recv(72)
                fr = _can_frame_to_dict(frame)
                now = time.time()

                can_id = int(fr["can_id"])
                data = fr["data"]
                decoded = _decode_configured_signals(can_id, data, sig_defs, default_endian=default_endian)

                with STATE.lock:
                    STATE.latest_can_status[self.can_id] = "OK"
                    STATE.latest_can_ts[self.can_id] = now
                    STATE.latest_can_error[self.can_id] = None
                    STATE.latest_can_iface[self.can_id] = iface
                    STATE.latest_can_rx_count[self.can_id] = int((STATE.latest_can_rx_count.get(self.can_id, 0) or 0) + 1)
                    STATE.latest_can_frame[self.can_id] = {
                        "can_id": f"0x{can_id:X}",
                        "dlc": fr["dlc"],
                        "data_hex": fr["data_hex"],
                        "ts": now,
                    }

                    cur = dict((STATE.latest_can_signals.get(self.can_id) or {}))
                    cur.update(decoded)
                    STATE.latest_can_signals[self.can_id] = cur

                    shift = _pick_shift(cur)

                    if shift is not None:
                        STATE.latest_shift[self.can_id] = shift


                    if "SP1" in cur:
                        STATE.latest_vehicle_speed[self.can_id] = float(cur["SP1"]["physical"])

                    if "HV_ACCP" in cur:
                        pedal = dict((STATE.latest_pedal.get(self.can_id) or {}))
                        pedal["accel"] = float(cur["HV_ACCP"]["physical"])
                        STATE.latest_pedal[self.can_id] = pedal

                    if "PMC" in cur:
                        pedal = dict((STATE.latest_pedal.get(self.can_id) or {}))
                        pedal["brake"] = float(cur["PMC"]["physical"])
                        STATE.latest_pedal[self.can_id] = pedal

                    if "WSTP" in cur:
                        pedal = dict((STATE.latest_pedal.get(self.can_id) or {}))
                        pedal["brake_switch"] = int(cur["WSTP"]["raw"])
                        STATE.latest_pedal[self.can_id] = pedal

                    if "SSA" in cur:
                        STATE.latest_steering_rate[self.can_id] = float(cur["SSA"]["physical"])

                    if "VSC_GX0" in cur:
                        accel = dict((STATE.latest_accel_xyz.get(self.can_id) or {}))
                        prev_x = accel.get("x")
                        new_x = float(cur["VSC_GX0"]["physical"])
                        speed_kmh = float(STATE.latest_vehicle_speed.get(self.can_id, 0.0) or 0.0)

                        keep_prev = False

                        # 絶対値が大きすぎる前後Gは捨てる
                        if abs(new_x) > 6.0:
                            keep_prev = True

                        # 低速域で大きすぎる前後Gは捨てる
                        if speed_kmh < 3.0 and abs(new_x) > 3.0:
                            keep_prev = True

                        # 直前値からの急ジャンプは捨てる
                        if prev_x is not None and abs(new_x - float(prev_x)) > 3.0:
                            keep_prev = True

                        if keep_prev:
                            if prev_x is None:
                                accel["x"] = 0.0
                        else:
                            accel["x"] = new_x

                        STATE.latest_accel_xyz[self.can_id] = accel

            except socket.timeout:
                with STATE.lock:
                    STATE.latest_can_status[self.can_id] = "NO DATA"
                    STATE.latest_can_iface[self.can_id] = iface
                    STATE.latest_can_error[self.can_id] = None
                    STATE.latest_can_ts[self.can_id] = time.time()
                continue
            except Exception as e:
                self._close_sock()
                with STATE.lock:
                    STATE.latest_can_status[self.can_id] = "ERROR"
                    STATE.latest_can_error[self.can_id] = str(e)
                    STATE.latest_can_iface[self.can_id] = iface
                    STATE.latest_can_ts[self.can_id] = time.time()
                time.sleep(1.0)
