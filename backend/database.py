import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
 
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 환경변수가 설정되지 않았습니다. "
        "infra/.env 파일을 만들고 docker compose로 실행했는지 확인하세요."
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
 
