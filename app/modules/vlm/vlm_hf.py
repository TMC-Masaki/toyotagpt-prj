# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import cv2
import sys

_TORCH_IMPORT_LOCK = threading.Lock()

def _ensure_torch_ready():
    """
    If torch import ever failed mid-way in this process, a partially initialized
    'torch' can remain in sys.modules and will poison all subsequent imports.
    This function detects that state, purges torch modules, and re-imports torch
    in a serialized way.
    """
    with _TORCH_IMPORT_LOCK:
        t = sys.modules.get("torch", None)
        if t is not None and not hasattr(t, "nn"):
            # purge partial torch
            for k in list(sys.modules.keys()):
                if k == "torch" or k.startswith("torch."):
                    sys.modules.pop(k, None)

        import torch  # re-import cleanly
        import torch.nn  # force init of nn
        import torch.jit  # force init of jit
        return torch

torch = _ensure_torch_ready()
from PIL import Image
from transformers import AutoProcessor, AutoModelForCausalLM
from transformers import Qwen2_5_VLForConditionalGeneration
from transformers import LlavaForConditionalGeneration
from transformers import SmolVLMForConditionalGeneration
from transformers import Qwen2VLForConditionalGeneration

def _dtype_from_str(s: str) -> torch.dtype:
    s = (s or "").lower()
    if s in ("fp16", "float16", "half"):
        return torch.float16
    if s in ("bf16", "bfloat16"):
        return torch.bfloat16
    if s in ("fp32", "float32"):
        return torch.float32
    return torch.float16


@dataclass
class HfOpts:
    device: str = "cuda"          # "cuda" | "cpu"
    dtype: str = "float16"        # "float16" | "bfloat16" | "float32"
    max_new_tokens: int = 128
    temperature: float = 0.2
    do_sample: bool = False
    infer_width: int = 640        # 0 disables resize


_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {}  # key -> (processor, model)  (keep only one for fast switching)
_WARMED_KEYS = set()


class VlmHf:
    def __init__(self, model_id: str, opts: Optional[HfOpts] = None):
        self.model_id = model_id
        self.opts = opts or HfOpts()

    def _get_processor_and_model(self):
        device = (self.opts.device or "cuda").lower()
        if device.startswith("cuda") and not torch.cuda.is_available():
            device = "cpu"

        dtype = _dtype_from_str(self.opts.dtype)
        key = f"{self.model_id}|{device}|{str(dtype)}"

        with _CACHE_LOCK:
            # keep only ONE model in memory for fast switching evaluation
            if _CACHE and (key not in _CACHE):
                try:
                    _, old_model = next(iter(_CACHE.values()))
                    del old_model
                except Exception:
                    pass
                _CACHE.clear()
                try:
                    if device.startswith("cuda"):
                        torch.cuda.empty_cache()
                except Exception:
                    pass

            if key in _CACHE:
                return _CACHE[key]

            try:
                processor = AutoProcessor.from_pretrained(
                    self.model_id,
                    trust_remote_code=True,
                    use_fast=True,
                )
            except TypeError:
                processor = AutoProcessor.from_pretrained(
                    self.model_id,
                    trust_remote_code=True,
                )

            mid = (self.model_id or "").lower()
            if "qwen2.5-vl" in mid or "qwen2_5_vl" in mid:
                model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                    attn_implementation="eager",
                )
            elif "qwen2-vl" in mid:
                model = Qwen2VLForConditionalGeneration.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                )
            elif "llava" in mid:
                model = LlavaForConditionalGeneration.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                )
            elif "smolvlm" in mid:
                model = SmolVLMForConditionalGeneration.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                )
            else:
                model = AutoModelForCausalLM.from_pretrained(
                    self.model_id,
                    torch_dtype=dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                )

            model.eval()
            model.to(device)

            if key not in _WARMED_KEYS:
                try:
                    dummy = Image.new("RGB", (224, 224), color=(0, 0, 0))
                    warm_messages = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "image": dummy},
                                {"type": "text", "text": "短く説明して"},
                            ],
                        }
                    ]
                    warm_text = processor.apply_chat_template(
                        warm_messages,
                        tokenize=False,
                        add_generation_prompt=True,
                    )
                    warm_inputs = processor(
                        text=[warm_text],
                        images=[dummy],
                        return_tensors="pt",
                    )
                    for k2, v2 in list(warm_inputs.items()):
                        if torch.is_tensor(v2):
                            warm_inputs[k2] = v2.to(device, non_blocking=True)

                    warm_kwargs = {"max_new_tokens": 1, "do_sample": False}
                    tw0 = time.time()
                    if str(device).startswith("cuda") and dtype in (torch.float16, torch.bfloat16):
                        with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=dtype):
                            _ = model.generate(**warm_inputs, **warm_kwargs)
                    else:
                        with torch.inference_mode():
                            _ = model.generate(**warm_inputs, **warm_kwargs)
                    print(f"[vlm_hf] warmup ok sec={time.time()-tw0:.3f} key={key}", flush=True)
                    _WARMED_KEYS.add(key)
                except Exception as e:
                    print(f"[vlm_hf] warmup error: {e!r}", flush=True)

            _CACHE[key] = (processor, model)
            return processor, model

    def infer(self, frame_bgr, prompt: str) -> Dict[str, Any]:
        t0 = time.time()
        print('[vlm_hf] enter infer', flush=True)
        if frame_bgr is None:
            raise RuntimeError("frame is None")

        t_resize0 = time.time()
        if self.opts.infer_width and frame_bgr.shape[1] > int(self.opts.infer_width):
            h, w = frame_bgr.shape[:2]
            nh = int(h * (int(self.opts.infer_width) / w))
            frame_bgr = cv2.resize(frame_bgr, (int(self.opts.infer_width), nh))
        resize_sec = time.time() - t_resize0

        t_rgb0 = time.time()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        rgb_pil_sec = time.time() - t_rgb0

        t_model0 = time.time()
        processor, model = self._get_processor_and_model()
        device = next(model.parameters()).device
        get_model_sec = time.time() - t_model0
        print(f'[vlm_hf] after get_model sec={get_model_sec:.3f} device={device}', flush=True)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        t_chat0 = time.time()
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        chat_template_sec = time.time() - t_chat0
        print(f'[vlm_hf] after chat_template sec={chat_template_sec:.3f}', flush=True)

        t_proc0 = time.time()
        inputs = processor(
            text=[text],
            images=[image],
            return_tensors="pt",
        )
        processor_sec = time.time() - t_proc0
        print(f'[vlm_hf] after processor sec={processor_sec:.3f}', flush=True)

        t_dev0 = time.time()
        for k, v in list(inputs.items()):
            if torch.is_tensor(v):
                inputs[k] = v.to(device, non_blocking=True)
        to_device_sec = time.time() - t_dev0
        print(f'[vlm_hf] after to_device sec={to_device_sec:.3f}', flush=True)

        gen_kwargs = {
            "max_new_tokens": int(self.opts.max_new_tokens),
            "do_sample": bool(self.opts.do_sample),
            "num_beams": 1,
            "use_cache": True,
        }

        try:
            if getattr(processor, "tokenizer", None) is not None:
                tok = processor.tokenizer
                if getattr(tok, "pad_token_id", None) is not None:
                    gen_kwargs["pad_token_id"] = tok.pad_token_id
                if getattr(tok, "eos_token_id", None) is not None:
                    gen_kwargs["eos_token_id"] = tok.eos_token_id
        except Exception:
            pass

        if gen_kwargs["do_sample"]:
            gen_kwargs["temperature"] = float(self.opts.temperature)

        try:
            in_len_dbg = int(inputs["input_ids"].shape[1])
        except Exception:
            in_len_dbg = -1

        t_gen0 = time.time()
        print(
            f'[vlm_hf] before generate max_new_tokens={int(self.opts.max_new_tokens)} '
            f'input_len={in_len_dbg} do_sample={gen_kwargs.get("do_sample")} '
            f'num_beams={gen_kwargs.get("num_beams")} use_cache={gen_kwargs.get("use_cache")} '
            f'pad_token_id={gen_kwargs.get("pad_token_id")} eos_token_id={gen_kwargs.get("eos_token_id")}',
            flush=True
        )
        if str(device).startswith("cuda") and next(model.parameters()).dtype in (torch.float16, torch.bfloat16):
            with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=next(model.parameters()).dtype):
                out_ids = model.generate(**inputs, **gen_kwargs)
        else:
            with torch.inference_mode():
                out_ids = model.generate(**inputs, **gen_kwargs)
        generate_sec = time.time() - t_gen0
        print(f'[vlm_hf] after generate sec={generate_sec:.3f}', flush=True)

        t_dec0 = time.time()
        in_len = inputs["input_ids"].shape[1]
        gen_only = out_ids[:, in_len:]
        out_text = processor.batch_decode(gen_only, skip_special_tokens=True)[0].strip()
        out_text = _postprocess_text(out_text, max_chars=220)
        decode_sec = time.time() - t_dec0

        total_sec = time.time() - t0
        print(
            "[vlm_hf] timing "
            f"resize={resize_sec:.3f}s "
            f"rgb_pil={rgb_pil_sec:.3f}s "
            f"get_model={get_model_sec:.3f}s "
            f"chat={chat_template_sec:.3f}s "
            f"processor={processor_sec:.3f}s "
            f"to_device={to_device_sec:.3f}s "
            f"generate={generate_sec:.3f}s "
            f"decode={decode_sec:.3f}s "
            f"total={total_sec:.3f}s "
            f"max_new_tokens={int(self.opts.max_new_tokens)} "
            f"device={device}",
            flush=True,
        )

        return {
            "ok": True,
            "engine": "hf",
            "model": self.model_id,
            "text": out_text,
            "prompt_used": prompt,
            "has_frame": True,
            "latency_ms": int((time.time() - t0) * 1000),
        }

def _postprocess_text(text: str, max_chars: int = 220) -> str:
    """
    - 文字化け(�)を除去
    - 長すぎる場合はできるだけ自然な位置で切る
    - 自然な区切りが見つからない場合は ... を付ける
    """
    if text is None:
        return ""

    t = str(text).replace("\ufffd", "").strip()
    if not t:
        return ""

    # 改行などを軽く整理
    t = " ".join(t.split()).strip()

    if max_chars is None or max_chars <= 0:
        return t

    if len(t) <= max_chars:
        return t

    cut = t[:max_chars]

    # 文末っぽい区切りを優先
    ends = ("。", "！", "？", ".", "!", "?", "）", ")", "」", "』")
    best = -1
    for e in ends:
        i = cut.rfind(e)
        if i > best:
            best = i

    if best >= 0:
        return cut[:best + 1].strip()

    return cut.rstrip(" 、,") + "..."
