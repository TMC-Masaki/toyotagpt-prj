from fastapi import FastAPI
from app.api.main_api import router as main_router
from app.api.ui import router as ui_router
from app.api.stream_api import router as stream_router
from app.api.video_api import router as video_router
from app.api.gnss_api import router as gnss_router
from app.api.can_api import router as can_router
from app.modules.workers.gps_worker import GpsWorker
from app.modules.workers.can_worker import CanWorker

app = FastAPI(title="vlm-platform-mvp")
app.include_router(main_router)
app.include_router(ui_router)
app.include_router(stream_router)
app.include_router(video_router)
app.include_router(gnss_router)
app.include_router(can_router)

gps_worker = GpsWorker(gnss_id=0)
can_worker = CanWorker(can_id=0)

@app.on_event("startup")
def _startup_gnss():
    global gps_worker
    if not gps_worker.is_alive():
        gps_worker = GpsWorker(gnss_id=0)
        gps_worker.start()


@app.on_event("startup")
def _startup_can():
    global can_worker
    if not can_worker.is_alive():
        can_worker = CanWorker(can_id=0)
        can_worker.start()


@app.on_event("shutdown")
def _shutdown_workers():
    try:
        if can_worker.is_alive():
            can_worker.stop()
            can_worker.join(timeout=2.0)
    except Exception:
        pass
    try:
        if gps_worker.is_alive():
            gps_worker.stop()
            gps_worker.join(timeout=2.0)
    except Exception:
        pass
