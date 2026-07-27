import time
import threading
from queue import Queue, Full, Empty
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from app.runtime.event_buffer import EventRingBuffer

# --- utility: latest-priority enqueue (drop oldest) ---
def put_latest(q: Queue, item: Any) -> None:
    try:
        q.put_nowait(item)
    except Full:
        try:
            q.get_nowait()  # drop oldest
        except Empty:
            pass
        try:
            q.put_nowait(item)
        except Full:
            pass

@dataclass
class SharedState:
    lock: threading.Lock = field(default_factory=threading.Lock)

    # latest per cam
    latest_frame_bgr: Dict[int, Any] = field(default_factory=dict)   # numpy array
    latest_ts: Dict[int, float] = field(default_factory=dict)
    latest_frame_id: Dict[int, int] = field(default_factory=dict)
    latest_pos_sec: Dict[int, float] = field(default_factory=dict)
    latest_dets: Dict[int, Any] = field(default_factory=dict)        # list/dict
    latest_preview_jpg: Dict[int, bytes] = field(default_factory=dict)   # overlay済み表示用JPEG
    latest_preview_frame_id: Dict[int, int] = field(default_factory=dict)
    latest_preview_ts: Dict[int, float] = field(default_factory=dict)
    latest_vlm: Dict[int, Any] = field(default_factory=dict)         # dict result
    latest_error: Dict[int, str] = field(default_factory=dict)
    latest_vlm_busy: Dict[int, int] = field(default_factory=dict)   # 1/0
    latest_yolo_busy: Dict[int, int] = field(default_factory=dict)  # 1/0
    latest_gnss: Dict[int, Any] = field(default_factory=dict)   # {"lat":..,"lon":..,"ts":..,"mode":..}
    latest_gnss_error: Dict[int, str] = field(default_factory=dict)
    latest_gnss_ts: Dict[int, float] = field(default_factory=dict)
    latest_gnss_mode: Dict[int, int] = field(default_factory=dict)      # 0/1/2/3
    latest_gnss_connected: Dict[int, int] = field(default_factory=dict) # 1/0
    gnss_track: Dict[int, Any] = field(default_factory=dict)    # list of points

    # CAN-FD / vehicle state
    latest_can_status: Dict[int, str] = field(default_factory=dict)     # "OK"/"NO DATA"/...
    latest_can_ts: Dict[int, float] = field(default_factory=dict)
    latest_can_error: Dict[int, str] = field(default_factory=dict)
    latest_vehicle_speed: Dict[int, float] = field(default_factory=dict)    # km/h
    latest_shift: Dict[int, str] = field(default_factory=dict)              # P/R/N/D/B...
    latest_accel_xyz: Dict[int, Any] = field(default_factory=dict)          # {"x":..,"y":..,"z":..}
    latest_pedal: Dict[int, Any] = field(default_factory=dict)              # {"accel":..,"brake":..}
    latest_steering_rate: Dict[int, float] = field(default_factory=dict)    # deg/s

    latest_can_signals: Dict[int, Any] = field(default_factory=dict)       # decoded signals
    latest_can_frame: Dict[int, Any] = field(default_factory=dict)         # last raw frame
    latest_can_iface: Dict[int, str] = field(default_factory=dict)         # can0/can1/dummy
    latest_can_rx_count: Dict[int, int] = field(default_factory=dict)      # rx count

    # runtime metrics
    latest_yolo_fps: Dict[int, float] = field(default_factory=dict)
    latest_yolo_latency_ms: Dict[int, float] = field(default_factory=dict)
    latest_vlm_fps: Dict[int, float] = field(default_factory=dict)
    latest_vlm_latency_ms: Dict[int, float] = field(default_factory=dict)
    latest_vlm_ttft_ms: Dict[int, float] = field(default_factory=dict)

    # latest event save result
    latest_event_save: Dict[int, Any] = field(default_factory=dict)

    # latest primary infer input actually sent to VLM
    latest_primary_infer_input: Dict[int, Any] = field(default_factory=dict)

    # latest secondary inference result
    latest_secondary_result: Dict[int, Any] = field(default_factory=dict)
    latest_secondary_status: Dict[int, Any] = field(default_factory=dict)
    latest_secondary_error: Dict[int, Any] = field(default_factory=dict)

    # latest event display
    latest_event_state: Dict[int, Any] = field(default_factory=dict)

    # accumulated event log (推論開始/停止でクリア)
    latest_event_log: Dict[int, Any] = field(default_factory=dict)

STATE = SharedState()

# event ring buffer (camera / video 共通)
EVENT_BUFFER: Dict[int, EventRingBuffer] = {
    0: EventRingBuffer(max_seconds=22.0, target_fps=10.0, jpeg_quality=85)
}

# latest event/save logs for UI
EVENT_LOGS: Dict[int, list] = {0: []}

# Queues (small = backpressure)
VISION_IN_Q: Dict[int, Queue] = {0: Queue(maxsize=2)}   # frame refs or actual frames for now
VLM_IN_Q: Queue = Queue(maxsize=1)                      # always latest event
EVENT_SAVE_Q: Queue = Queue(maxsize=8)                  # async event bundle save jobs
SECONDARY_INFER_Q: Queue = Queue(maxsize=4)             # async secondary inference jobs
