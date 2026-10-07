import os

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

try:
    from .api import (ANKLE_FOOT_Z_MAX, ANKLE_FOOT_Z_MIN, BBOX_POSITION_METHOD,
                      BOX_FOOT_Z_MAX, BOX_FOOT_Z_MIN, MAX_EPIPOLAR_ERROR_PX, router)
    from .database import get_db
except ImportError:  # Docker runs this directory as the import root.
    from api import (ANKLE_FOOT_Z_MAX, ANKLE_FOOT_Z_MIN, BBOX_POSITION_METHOD,
                     BOX_FOOT_Z_MAX, BOX_FOOT_Z_MIN, MAX_EPIPOLAR_ERROR_PX, router)
    from database import get_db

app = FastAPI(title="CCTV Safety Monitor API")
app.include_router(router)


@app.get("/health")
def health_check():
    """서버 자체가 살아있는지 확인"""
    return {
        "status": "ok",
        "commit": os.getenv("APP_COMMIT_SHA", "unknown"),
        "max_epipolar_error_px": MAX_EPIPOLAR_ERROR_PX,
        "box_foot_z_min": BOX_FOOT_Z_MIN,
        "box_foot_z_max": BOX_FOOT_Z_MAX,
        "ankle_foot_z_min": ANKLE_FOOT_Z_MIN,
        "ankle_foot_z_max": ANKLE_FOOT_Z_MAX,
        "bbox_position_method": BBOX_POSITION_METHOD,
    }


@app.get("/health/db")
def health_check_db(db: Session = Depends(get_db)):
    """DB 연결이 정상인지 확인"""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}
