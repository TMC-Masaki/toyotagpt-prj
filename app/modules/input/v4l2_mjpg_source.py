import subprocess
import time
import cv2
import numpy as np


class V4L2MJPGSource:
    """
    Reads MJPG stream using v4l2-ctl --stream-to=-
    and decodes each JPEG frame with cv2.imdecode.

    Latency-oriented behavior:
    - if multiple complete JPEGs are buffered, return the latest one
    - discard older buffered frames
    """
    def __init__(self, device="/dev/video0", width=1920, height=1080, fps=30, mmap=3):
        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.mmap = int(mmap)
        self._proc = None
        self._buf = bytearray()
        self._start()

    def _start(self):
        self.close()
        cmd = [
            "v4l2-ctl",
            "-d", self.device,
            f"--set-fmt-video=width={self.width},height={self.height},pixelformat=MJPG",
            f"--stream-mmap={self.mmap}",
            "--stream-to=-",
            "--stream-count=0",
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def _extract_latest_complete_jpeg(self):
        if not self._buf:
            return None

        starts = []
        pos = 0
        while True:
            i = self._buf.find(b"\xff\xd8", pos)
            if i == -1:
                break
            starts.append(i)
            pos = i + 2

        if not starts:
            return None

        last_jpg = None
        last_end = None

        for s in starts:
            e = self._buf.find(b"\xff\xd9", s + 2)
            if e == -1:
                continue
            last_jpg = bytes(self._buf[s:e + 2])
            last_end = e + 2

        if last_jpg is None:
            return None

        # 最新の完全JPEGまでの古いデータを捨てる
        del self._buf[:last_end]
        return last_jpg

    def read_frame(self):
        if self._proc is None or self._proc.stdout is None:
            self._start()
            time.sleep(0.1)
            return None

        jpg = self._extract_latest_complete_jpeg()
        if jpg is not None:
            arr = np.frombuffer(jpg, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)

        while True:
            chunk = self._proc.stdout.read(65536)
            if not chunk:
                self._start()
                time.sleep(0.1)
                return None

            self._buf.extend(chunk)

            jpg = self._extract_latest_complete_jpeg()
            if jpg is not None:
                arr = np.frombuffer(jpg, dtype=np.uint8)
                return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def close(self):
        try:
            if self._proc is not None:
                self._proc.terminate()
                self._proc.wait(timeout=1)
        except Exception:
            pass
        self._proc = None
