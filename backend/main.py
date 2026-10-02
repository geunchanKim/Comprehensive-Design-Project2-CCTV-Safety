from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db

app = FastAPI(title="CCTV Safety Monitor API")


@app.get("/health")
def health_check():
    """서버 자체가 살아있는지 확인"""
    return {"status": "ok"}


@app.get("/health/db")
def health_check_db(db: Session = Depends(get_db)):
    """DB 연결이 정상인지 확인"""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}