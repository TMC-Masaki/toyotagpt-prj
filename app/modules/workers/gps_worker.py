import os
import time
import json
import socket
import threading
from app.runtime.bus import STATE

class GpsWorker(threading.Thread):
    daemon = True

    def __init__(self, gnss_id: int = 0, max_points: int = 5000):
        super().__init__()
        self.gnss_id = gnss_id
        self.max_points = max_points
        self._stop_evt = threading.Event()

        # docker-compose から渡す想定
        self.host = os.getenv("GPSD_HOST", "192.168.1.35")
        self.port = int(os.getenv("GPSD_PORT", "2947"))

    def stop(self):
        self._stop_evt.set()

    def _set_err(self, msg: str | None):
        with STATE.lock:
            STATE.latest_gnss_error[self.gnss_id] = msg

    def run(self):
        # 初期化
        with STATE.lock:
            STATE.latest_gnss_error[self.gnss_id] = None
            STATE.latest_gnss_ts[self.gnss_id] = None
            STATE.latest_gnss_mode[self.gnss_id] = 0
            STATE.latest_gnss_connected[self.gnss_id] = 0
            if self.gnss_id not in STATE.gnss_track:
                STATE.gnss_track[self.gnss_id] = []

        while not self._stop_evt.is_set():
            s = None
            try:
                # 1) TCP接続
                s = socket.create_connection((self.host, self.port), timeout=5)
                s.settimeout(2)

                # 2) WATCH を送る（JSONモード）
                watch = '?WATCH={"enable":true,"json":true,"nmea":false,"raw":0}\n'
                s.sendall(watch.encode("ascii", errors="ignore"))
                with STATE.lock:
                    STATE.latest_gnss_connected[self.gnss_id] = 1
                    STATE.latest_gnss_error[self.gnss_id] = None

                buf = b""
                while not self._stop_evt.is_set():
                    try:
                        chunk = s.recv(4096)
                        if not chunk:
                            raise RuntimeError("gpsd connection closed")
                        buf += chunk
                    except socket.timeout:
                        continue

                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            msg = json.loads(line.decode("utf-8", errors="ignore"))
                        except Exception:
                            continue

                        if not isinstance(msg, dict):
                            continue
                        if msg.get("class") != "TPV":
                            continue

                        lat = msg.get("lat")
                        lon = msg.get("lon")
                        mode = int(msg.get("mode") or 0)
                        now_ts = time.time()

                        with STATE.lock:
                            STATE.latest_gnss_mode[self.gnss_id] = mode
                            STATE.latest_gnss_ts[self.gnss_id] = now_ts
                            STATE.latest_gnss_connected[self.gnss_id] = 1
                            STATE.latest_gnss_error[self.gnss_id] = None

                        # no-fix TPV でも mode/ts は保持する
                        if lat is None or lon is None:
                            continue

                        pt = {"lat": float(lat), "lon": float(lon), "mode": mode, "ts": now_ts}

                        with STATE.lock:
                            STATE.latest_gnss[self.gnss_id] = pt
                            STATE.latest_gnss_ts[self.gnss_id] = pt["ts"]
                            STATE.latest_gnss_error[self.gnss_id] = None

                            tr = STATE.gnss_track.get(self.gnss_id) or []
                            tr.append(pt)
                            if len(tr) > self.max_points:
                                tr = tr[-self.max_points:]
                            STATE.gnss_track[self.gnss_id] = tr

            except Exception as e:
                with STATE.lock:
                    STATE.latest_gnss_connected[self.gnss_id] = 0
                    STATE.latest_gnss_error[self.gnss_id] = f"gnss: gpsd connect/read failed {self.host}:{self.port}: {e}"
                time.sleep(1.0)
            finally:
                try:
                    if s:
                        s.close()
                except Exception:
                    pass
