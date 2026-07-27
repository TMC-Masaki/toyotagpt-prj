from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import cv2


class ImageDirSource:
    def __init__(self, path: str, fps: float = 29.97, loop: bool = False):
        self.path = Path(path)
        self.fps = float(fps) if fps else 0.0
        self.loop = bool(loop)

        self.files = []
        self.index = 0
        self.frame_idx = 0
        self.width = 0
        self.height = 0
        self.opened = False
        self._t_next: Optional[float] = None

    def open(self):
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        if not self.path.exists():
            raise FileNotFoundError(f"image dir not found: {self.path}")

        self.files = sorted([p for p in self.path.iterdir() if p.suffix.lower() in exts])
        if not self.files:
            raise RuntimeError(f"no image files found in: {self.path}")

        first = cv2.imread(str(self.files[0]), cv2.IMREAD_COLOR)
        if first is None:
            raise RuntimeError(f"failed to read first image: {self.files[0]}")

        self.height, self.width = first.shape[:2]
        self.index = 0
        self.frame_idx = 0
        self.opened = True
        self._t_next = time.time()
        return True

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.opened:
            self.open()

        if self.index >= len(self.files):
            if self.loop:
                self.index = 0
            else:
                return False, None

        if self.fps > 0 and self._t_next is not None:
            now = time.time()
            wait = self._t_next - now
            if wait > 0:
                time.sleep(wait)

        p = self.files[self.index]
        frame = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if frame is None:
            self.index += 1
            self.frame_idx += 1
            return False, None

        self.index += 1
        self.frame_idx += 1

        if self.fps > 0 and self._t_next is not None:
            self._t_next += 1.0 / self.fps

        return True, frame

    def get(self, prop_id):
        if prop_id == cv2.CAP_PROP_FPS:
            return self.fps
        if prop_id == cv2.CAP_PROP_FRAME_COUNT:
            return float(len(self.files))
        if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self.width)
        if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self.height)
        if prop_id == cv2.CAP_PROP_POS_FRAMES:
            return float(self.index)
        if prop_id == cv2.CAP_PROP_POS_MSEC:
            if self.fps > 0:
                return float((self.index / self.fps) * 1000.0)
            return 0.0
        return 0.0

    def set(self, prop_id, value):
        if prop_id == cv2.CAP_PROP_POS_FRAMES:
            i = int(value)
            if i < 0:
                i = 0
            if i >= len(self.files):
                i = len(self.files) - 1 if self.files else 0
            self.index = i
            self.frame_idx = i
            if self.fps > 0:
                self._t_next = time.time()
            return True
        return False

    def release(self):
        self.opened = False
