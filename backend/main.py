import os
from math import isfinite

from fastapi import FastAPI, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

try:
    from .api import (ANKLE_FOOT_Z_MAX, ANKLE_FOOT_Z_MIN, BBOX_POSITION_METHOD,
                      BOX_FOOT_Z_MAX, BOX_FOOT_Z_MIN, MAX_EPIPOLAR_ERROR_PX, MAX_SYNC_DELTA_MS,
                      FEATURE_CODES, LIVE_ALGORITHM, _experiment_settings, router)
    from .database import get_db
    from .dashboard_api import router as dashboard_router
    from .heartbeat import router as heartbeat_router
    from .alerts import router as alerts_router
except ImportError:  # Docker runs this directory as the import root.
    from api import (ANKLE_FOOT_Z_MAX, ANKLE_FOOT_Z_MIN, BBOX_POSITION_METHOD,
                     BOX_FOOT_Z_MAX, BOX_FOOT_Z_MIN, MAX_EPIPOLAR_ERROR_PX, MAX_SYNC_DELTA_MS,
                     FEATURE_CODES, LIVE_ALGORITHM, _experiment_settings, router)
    from database import get_db
    from dashboard_api import router as dashboard_router
    from heartbeat import router as heartbeat_router
    from alerts import router as alerts_router

app = FastAPI(title="CCTV Safety Monitor API")
app.include_router(router)
app.include_router(dashboard_router)
app.include_router(heartbeat_router)
app.include_router(alerts_router)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # JSON decoders can parse 1e309 as infinity. Keep validation errors JSON-safe
    # instead of failing while serializing the rejected input back to the caller.
    detail = jsonable_encoder(exc.errors(), custom_encoder={
        float: lambda value: value if isfinite(value) else str(value)})
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/health")
def health_check():
    """서버 자체가 살아있는지 확인"""
    try:
        from .ppe import settings as ppe_settings
    except ImportError:
        from ppe import settings as ppe_settings
    try:
        from .alerts import ALERT_HOLD_MS, SESSION_ALERT_TIMEOUT_MS
    except ImportError:
        from alerts import ALERT_HOLD_MS, SESSION_ALERT_TIMEOUT_MS
    return {
        "alert_hold_ms": ALERT_HOLD_MS,
        "session_alert_timeout_ms": SESSION_ALERT_TIMEOUT_MS,
        "ppe": ppe_settings(),
        "live_algorithm": LIVE_ALGORITHM,
        "live_settings": _experiment_settings(LIVE_ALGORITHM),
        "status": "ok",
        "commit": os.getenv("APP_COMMIT_SHA", "unknown"),
        "max_epipolar_error_px": MAX_EPIPOLAR_ERROR_PX,
        "default_max_sync_delta_ms": MAX_SYNC_DELTA_MS,
        "box_foot_z_min": BOX_FOOT_Z_MIN,
        "box_foot_z_max": BOX_FOOT_Z_MAX,
        "ankle_foot_z_min": ANKLE_FOOT_Z_MIN,
        "ankle_foot_z_max": ANKLE_FOOT_Z_MAX,
        "bbox_position_method": BBOX_POSITION_METHOD,
        "algorithms": {
            "baseline": _experiment_settings("baseline"),
            "improved": _experiment_settings("improved"),
        },
        "feature_codes": FEATURE_CODES,
    }


@app.get("/health/db")
def health_check_db(db: Session = Depends(get_db)):
    """DB 연결이 정상인지 확인"""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}
