from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

#подключение к базе данных SQLite
SQLALCHEMY_DATABASE_URL = "sqlite:///./rooms.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

#класс для моделей
class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()