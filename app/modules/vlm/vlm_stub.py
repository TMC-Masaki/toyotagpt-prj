# -*- coding: utf-8 -*-
from __future__ import annotations

import random
import time
from typing import Any, Dict, Optional


class VlmStub:
    """
    Compatibility stub.

    This repo currently has mixed call sites:
      - infer(prompt)
      - infer(frame_bgr, prompt)

    To avoid breakage, this stub accepts both.
    It returns a dict that works for /latest and run_once.
    """

    def __init__(self, model: str = "stub"):
        self.model = model

    def infer(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        t0 = time.time()

        frame_bgr: Optional[Any] = None
        prompt: str = ""

        if len(args) == 1:
            prompt = "" if args[0] is None else str(args[0])
        elif len(args) >= 2:
            frame_bgr = args[0]
            prompt = "" if args[1] is None else str(args[1])

        # MVP: それっぽい固定フォーマット
        risk = random.choice(["通常", "注意", "危険"])
        score = {"通常": 0.2, "注意": 0.6, "危険": 0.9}[risk]
        text = f"【{risk}】前方に注意。周囲確認を継続し、必要なら減速してください。"

        return {
            "ok": True,
            "engine": "stub",
            "model": self.model,
            "risk_level": risk,
            "risk_score": score,
            "text": text,
            "prompt_used": prompt,
            "has_frame": frame_bgr is not None,
            "latency_ms": int((time.time() - t0) * 1000),
        }
