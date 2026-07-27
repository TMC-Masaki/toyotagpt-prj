from __future__ import annotations

import time
from dataclasses import dataclass
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import cv2
import numpy as np


@dataclass
class BufferedFrame:
    ts: float
    frame_id: int
    jpeg: bytes
    width: int
    height: int


class EventRingBuffer:
    """
    JPEG-compressed frame ring buffer.
    - keeps last N seconds
    - throttles append to target_fps
    - stores jpeg bytes to reduce RAM usage
    """

    def __init__(
        self,
        *,
        max_seconds: float = 22.0,
        target_fps: float = 10.0,
        jpeg_quality: int = 85,
    ) -> None:
        self.max_seconds = float(max_seconds)
        self.target_fps = float(target_fps)
        self.jpeg_quality = int(jpeg_quality)

        self._frames: Deque[BufferedFrame] = deque()
        self._last_append_ts: float = 0.0
        self._closed: bool = False

    def clear(self) -> None:
        self._frames.clear()
        self._last_append_ts = 0.0

    def close(self) -> None:
        self.clear()
        self._closed = True

    def reopen(self) -> None:
        self._closed = False
        self.clear()

    def append(self, *, frame_bgr: Any, ts: float, frame_id: int) -> bool:
        if self._closed:
            return False

        if frame_bgr is None:
            return False

        # throttle
        if self.target_fps > 0:
            min_dt = 1.0 / self.target_fps
            if self._last_append_ts > 0 and (ts - self._last_append_ts) < min_dt:
                return False

        try:
            h, w = frame_bgr.shape[:2]
            ok, enc = cv2.imencode(
                ".jpg",
                frame_bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
            )
            if not ok:
                return False
            item = BufferedFrame(
                ts=float(ts),
                frame_id=int(frame_id),
                jpeg=enc.tobytes(),
                width=int(w),
                height=int(h),
            )
            self._frames.append(item)
            self._last_append_ts = float(ts)
            self._evict_old(now_ts=float(ts))
            return True
        except Exception:
            return False

    def _evict_old(self, *, now_ts: float) -> None:
        cutoff = float(now_ts) - self.max_seconds
        while self._frames and self._frames[0].ts < cutoff:
            self._frames.popleft()

    def snapshot_last(self, seconds: float) -> List[BufferedFrame]:
        if not self._frames:
            return []
        end_ts = self._frames[-1].ts
        start_ts = end_ts - float(seconds)
        return [x for x in self._frames if x.ts >= start_ts]

    def latest_ts(self) -> Optional[float]:
        if not self._frames:
            return None
        return float(self._frames[-1].ts)

    def frame_count(self) -> int:
        return len(self._frames)

    def sample_last_seconds_1fps(self, seconds: float = 5.0, step_sec: float = 1.0) -> List[BufferedFrame]:
        snap = self.snapshot_last(seconds)
        if not snap:
            return []

        end_ts = snap[-1].ts
        targets: List[float] = []
        n = int(seconds // step_sec)
        for i in range(n, 0, -1):
            targets.append(end_ts - float(i))

        out: List[BufferedFrame] = []
        for t in targets:
            nearest = min(snap, key=lambda x: abs(x.ts - t))
            if not out or out[-1].frame_id != nearest.frame_id:
                out.append(nearest)
        return out

    @staticmethod
    def decode_jpeg(item: BufferedFrame) -> np.ndarray:
        arr = np.frombuffer(item.jpeg, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("jpeg decode failed")
        return img

    def summary(self) -> Dict[str, Any]:
        return {
            "count": self.frame_count(),
            "latest_ts": self.latest_ts(),
            "max_seconds": self.max_seconds,
            "target_fps": self.target_fps,
            "jpeg_quality": self.jpeg_quality,
        }
