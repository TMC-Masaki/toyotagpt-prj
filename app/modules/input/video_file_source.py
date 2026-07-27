import threading
import time
import cv2


class VideoFileSource:
    def __init__(self, path: str, start_sec: float = 0.0):
        self.path = path
        self.cap = cv2.VideoCapture(self.path)
        self._cap_lock = threading.Lock()

        try:
            backend = self.cap.getBackendName() if hasattr(self.cap, "getBackendName") else "unknown"
        except Exception:
            backend = "unknown"
        try:
            with self._cap_lock:
                cap_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                cap_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                cap_fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            cap_w, cap_h, cap_fps = -1, -1, -1.0

        print(
            f"[video_src] open backend={backend} cap_w={cap_w} cap_h={cap_h} cap_fps={cap_fps:.3f} path={self.path}",
            flush=True
        )

        with self._cap_lock:
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
            self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        if self.fps <= 1e-6:
            self.fps = 30.0

        self.duration_sec = (self.frame_count / self.fps) if self.frame_count > 0 else 0.0

        self.lock = threading.Lock()
        self._latest_frame = None
        self._latest_pos_sec = 0.0
        self._latest_ok = False
        self._latest_seq = 0
        self._last_consumed_seq = -1
        self._eof = False
        self._stopped = False
        self._reader = None

        if start_sec > 0:
            self.seek(start_sec)
        else:
            self._pos_sec = 0.0

        self._start_reader()

    def _start_reader(self):
        if self._reader is not None:
            return
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()

    def _reader_loop(self):
        target_interval = 1.0 / float(self.fps or 30.0)

        while not self._stopped:
            with self.lock:
                if self._eof:
                    time.sleep(0.01)
                    continue

            t0 = time.time()
            try:
                with self._cap_lock:
                    if self._stopped or self.cap is None:
                        break
                    ok, frame = self.cap.read()
                    pos_msec = self.cap.get(cv2.CAP_PROP_POS_MSEC) if ok else -1
            except Exception as e:
                with self.lock:
                    self._latest_ok = False
                    self._latest_frame = None
                    self._eof = True
                print(f"[video_src] read_exc err={e!r}", flush=True)
                break

            read_ms = (time.time() - t0) * 1000.0

            if not ok:
                with self.lock:
                    self._latest_ok = False
                    self._latest_frame = None
                    self._eof = True
                print(f"[video_src] read_ng read_ms={read_ms:.1f}", flush=True)
                break

            pos_sec = (pos_msec / 1000.0) if pos_msec is not None and pos_msec >= 0 else self._latest_pos_sec

            try:
                h, w = frame.shape[:2]
                c = frame.shape[2] if len(frame.shape) >= 3 else 1
            except Exception:
                h, w, c = -1, -1, -1

            with self.lock:
                self._latest_frame = frame
                self._latest_pos_sec = pos_sec
                self._latest_ok = True
                self._latest_seq += 1

            print(
                f"[video_src] read_ok read_ms={read_ms:.1f} pos_sec={pos_sec:.3f} shape={w}x{h}x{c}",
                flush=True
            )

            elapsed = time.time() - t0
            sleep_sec = max(0.0, target_interval - elapsed)
            if sleep_sec > 0:
                time.sleep(sleep_sec)

    def read(self):
        wait_deadline = time.time() + 1.5
        while True:
            with self.lock:
                if self._eof and self._latest_frame is None:
                    return False, None

                if self._latest_frame is not None:
                    if self._latest_seq == self._last_consumed_seq:
                        frame = self._latest_frame.copy()
                        self._pos_sec = self._latest_pos_sec
                        return True, frame

                    self._last_consumed_seq = self._latest_seq
                    frame = self._latest_frame.copy()
                    self._pos_sec = self._latest_pos_sec
                    return True, frame

            if time.time() >= wait_deadline:
                break
            time.sleep(0.01)

        return False, None

    def read_frame(self):
        ok, frame = self.read()
        if not ok:
            return None
        return frame

    def seek(self, sec: float):
        with self._cap_lock:
            if self.cap is not None:
                self.cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(sec)) * 1000.0)
        with self.lock:
            self._pos_sec = max(0.0, float(sec))
            self._latest_frame = None
            self._latest_ok = False
            self._latest_seq += 1
            self._last_consumed_seq = -1
            self._eof = False

    def get_pos_sec(self) -> float:
        with self.lock:
            return float(self._pos_sec)

    def get_duration_sec(self) -> float:
        return float(self.duration_sec)

    def release(self):
        self._stopped = True

        try:
            if self._reader is not None and self._reader.is_alive():
                self._reader.join(timeout=2.0)
        except Exception:
            pass

        try:
            with self._cap_lock:
                if self.cap is not None:
                    self.cap.release()
                    self.cap = None
        except Exception:
            pass

        with self.lock:
            self._latest_frame = None
            self._latest_ok = False
            self._eof = True

    def close(self):
        self.release()
