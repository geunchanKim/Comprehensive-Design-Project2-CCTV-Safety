import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# 환경변수로 DB 접속 정보 관리 (.env 참고)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://cctv_user:cctv_password@db:5432/cctv_safety_db",
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI Depends로 주입할 DB 세션. 요청 끝나면 자동으로 닫힘"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()