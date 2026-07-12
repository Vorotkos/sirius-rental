import os
import time
import logging
import webbrowser
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session

os.makedirs("data", exist_ok=True)
SQLALCHEMY_DATABASE_URL = "sqlite:///./data/rooms.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


#SQLAlchemy
class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    capacity = Column(Integer)
    equipment = Column(String, nullable=True)


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, index=True)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    user_name = Column(String)
    status = Column(String, default="active")  # active / cancelled


Base.metadata.create_all(bind=engine)


#PYDANTIC V2
class RoomCreate(BaseModel):
    name: str
    capacity: int
    equipment: Optional[str] = None


class RoomResponse(BaseModel):
    id: int
    name: str
    capacity: int
    equipment: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BookingCreate(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime
    user_name: str


class BookingResponse(BaseModel):
    id: int
    room_id: int
    start_time: datetime
    end_time: datetime
    user_name: str
    status: str

    model_config = ConfigDict(from_attributes=True)


#НАСТРОЙКА ПРИЛОЖЕНИЯ И ЛОГИРОВАНИЯ
app = FastAPI(
    title="Сириус.Аренда",
    description="Сервис бронирования пространств",
    version="1.0.0"
)

logger = logging.getLogger("api_logger")
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    "api_requests.log",
    maxBytes=5*1024*1024,  # 5 МБ
    backupCount=3,
    encoding="utf-8"
)
formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

#для веб-интерфейса
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} ({process_time:.0f}ms)"
    )
    return response


os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    return FileResponse("static/index.html")


# ЭНДПОИНТЫ: КОМНАТЫ
@app.post("/rooms", response_model=RoomResponse, status_code=201)
def create_room(room: RoomCreate, db: Session = Depends(get_db)):
    db_room = Room(**room.model_dump())
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room


@app.get("/rooms", response_model=List[RoomResponse])
def get_rooms(
    capacity: Optional[int] = Query(None, description="Минимальная вместимость"),
    equipment: Optional[str] = Query(None, description="Оборудование"),
    db: Session = Depends(get_db)
):
    query = db.query(Room)
    if capacity is not None:
        query = query.filter(Room.capacity >= capacity)
    if equipment:
        query = query.filter(Room.equipment.contains(equipment))
    return query.all()


@app.get("/rooms/{room_id}", response_model=RoomResponse)
def get_room(room_id: int, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    return room


@app.put("/rooms/{room_id}", response_model=RoomResponse)
def update_room(room_id: int, room: RoomCreate, db: Session = Depends(get_db)):
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    for key, value in room.model_dump().items():
        setattr(db_room, key, value)
    db.commit()
    db.refresh(db_room)
    return db_room


@app.delete("/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db)):
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    db.delete(db_room)
    db.commit()
    return {"message": "Комната удалена"}


# ЭНДПОИНТЫ: БРОНИРОВАНИЯ
@app.post("/bookings", response_model=BookingResponse, status_code=201)
def create_booking(booking: BookingCreate, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == booking.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    if booking.end_time <= booking.start_time:
        raise HTTPException(
            status_code=400,
            detail="Время окончания должно быть позже времени начала"
        )

    overlapping = db.query(Booking).filter(
        Booking.room_id == booking.room_id,
        Booking.status == "active",
        Booking.start_time < booking.end_time,
        Booking.end_time > booking.start_time
    ).first()

    if overlapping:
        raise HTTPException(
            status_code=409,
            detail="Время пересекается с существующим бронированием"
        )

    db_booking = Booking(**booking.model_dump())
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)
    return db_booking


@app.get("/bookings", response_model=List[BookingResponse])
def get_bookings(db: Session = Depends(get_db)):
    return db.query(Booking).filter(Booking.status == "active").all()


@app.delete("/bookings/{booking_id}")
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    db_booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not db_booking:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")
    if db_booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Бронирование уже отменено")
    db_booking.status = "cancelled"
    db.commit()
    return {"message": "Бронирование отменено"}


#РАСПИСАНИЕ КОМНАТ
@app.get("/rooms/{room_id}/bookings", response_model=List[BookingResponse])
def get_room_schedule(
    room_id: int,
    date: str = Query(..., description="Дата в формате YYYY-MM-DD"),
    db: Session = Depends(get_db)
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат даты (нужен YYYY-MM-DD)")

    bookings = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.start_time >= datetime.combine(target_date, datetime.min.time()),
        Booking.start_time < datetime.combine(target_date, datetime.max.time())
    ).all()

    return bookings

#ПОИСК СВОБОДНЫХ ПРОСТРАНСТВ
@app.get("/rooms/available", response_model=List[RoomResponse])
def get_available_rooms(
        start: str = Query(..., description="Время начала в формате YYYY-MM-DDTHH:MM:SS"),
        end: str = Query(..., description="Время окончания в формате YYYY-MM-DDTHH:MM:SS"),
        capacity: Optional[int] = Query(None, description="Минимальная вместимость"),
        db: Session = Depends(get_db)
):
    """Поиск свободных пространств на заданный интервал времени"""
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Неверный формат даты. Используйте YYYY-MM-DDTHH:MM:SS"
        )

    if end_dt <= start_dt:
        raise HTTPException(
            status_code=400,
            detail="Время окончания должно быть позже времени начала"
        )

    busy_room_ids = db.query(Booking.room_id).filter(
        Booking.status == "active",
        Booking.start_time < end_dt,
        Booking.end_time > start_dt
    ).subquery()

    query = db.query(Room).filter(~Room.id.in_(busy_room_ids))

    if capacity is not None:
        query = query.filter(Room.capacity >= capacity)

    return query.all()


#автозапуск
def open_browser():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    import uvicorn
    threading.Thread(target=open_browser, daemon=True).start()
    print("Запускаю сервер")
    print("Приложение откроется автоматически через 1.5 секунды...")
    uvicorn.run(app, host="127.0.0.1", port=8000)