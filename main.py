from fastapi import FastAPI, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, Field

from database import engine, get_db, Base
from models import Room, Booking

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os

import webbrowser
import threading
import time

import logging
from logging.handlers import RotatingFileHandler
from fastapi import Request
from fastapi.responses import JSONResponse
import time


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Сириус.Аренда",
    description="Сервис бронирования пространств",
    version="1.0.0"
)
# ______________________
# ЛОГИРОВАНИЕ
# ______________________
logger = logging.getLogger("api_logger")
logger.setLevel(logging.INFO)

# RotatingFileHandler — новый файл при достижении 5МБ
# backupCount – количество сохраняемых старых файлов
file_handler = RotatingFileHandler(
    "api_requests.log",
    maxBytes=5 * 1024 * 1024,  # 5 МБ
    backupCount=3,
    encoding="utf-8"
)
formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# middleware — собирает все запросы и логирует их
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000  # время в миллисекундах

    #метод, URL, статус ответа, время выполнения
    logger.info(
        f"{request.method} {request.url.path} → {response.status_code} ({process_time:.0f}ms)"
    )

    return response

#схемы для комнат
class RoomCreate(BaseModel):
    """Схема для создания комнаты (POST /rooms)"""
    name: str = Field(..., min_length=1, max_length=100)
    capacity: int = Field(..., gt=0)
    equipment: str = Field(default="")

class RoomUpdate(BaseModel):
    """Схема для обновления комнаты (PUT /rooms/{id})"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    capacity: Optional[int] = Field(None, gt=0)
    equipment: Optional[str] = None

class RoomResponse(BaseModel):
    """Схема ответа с данными комнаты"""
    id: int
    name: str
    capacity: int
    equipment: str

    class Config:
        from_attributes = True


#схемы для бронирований
class BookingCreate(BaseModel):
    """Схема для создания бронирования (POST /bookings)"""
    room_id: int
    start_time: datetime
    end_time: datetime
    user_name: str = Field(..., min_length=1, max_length=100)

class BookingResponse(BaseModel):
    """Схема ответа с данными бронирования"""
    id: int
    room_id: int
    start_time: datetime
    end_time: datetime
    user_name: str
    status: str

    class Config:
        from_attributes = True


#создание комнаты
@app.post("/rooms", response_model=RoomResponse, status_code=201)
def create_room(room: RoomCreate, db: Session = Depends(get_db)):
    """POST /rooms — создать новую комнату"""
    db_room = Room(
        name=room.name,
        capacity=room.capacity,
        equipment=room.equipment
    )
    db.add(db_room)
    db.commit()
    db.refresh(db_room)
    return db_room


#получение  списка комнат
@app.get("/rooms", response_model=List[RoomResponse])
def get_rooms(
        min_capacity: Optional[int] = Query(None, description="Минимальная вместимость"),
        equipment: Optional[str] = Query(None, description="Наличие оборудования"),
        db: Session = Depends(get_db)
):
    """GET /rooms — список всех комнат (с опциональной фильтрацией)"""
    query = db.query(Room)

    if min_capacity is not None:
        query = query.filter(Room.capacity >= min_capacity)

    if equipment is not None:
        query = query.filter(Room.equipment.contains(equipment))

    return query.all()


#получение одной комнаты
@app.get("/rooms/{room_id}", response_model=RoomResponse)
def get_room(room_id: int, db: Session = Depends(get_db)):
    """GET /rooms/{id} — информация о конкретной комнате"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")
    return room


#обновление комнаты
@app.put("/rooms/{room_id}", response_model=RoomResponse)
def update_room(room_id: int, room_update: RoomUpdate, db: Session = Depends(get_db)):
    """PUT /rooms/{id} — обновить данные комнаты"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    update_data = room_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)

    db.commit()
    db.refresh(room)
    return room


#удаление комнаты
@app.delete("/rooms/{room_id}", status_code=200)
def delete_room(room_id: int, db: Session = Depends(get_db)):
    """DELETE /rooms/{id} — удалить комнату"""
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    db.delete(room)
    db.commit()
    return {"message": "Комната удалена"}


#вспомогательная функция проверки конфликтов
def check_booking_conflict(
        db: Session,
        room_id: int,
        start_time: datetime,
        end_time: datetime,
        exclude_booking_id: int = None
):
    """Проверяет, что комната свободна в указанное время"""

    if end_time <= start_time:
        raise HTTPException(
            status_code=400,
            detail="Время окончания должно быть позже времени начала"
        )

    query = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.status == "active",
        Booking.start_time < end_time,  # начало существующего < конец нового
        Booking.end_time > start_time  # конец существующего > начало нового
    )

    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)

    conflict = query.first()
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=f"Комната уже забронирована в это время (бронирование #{conflict.id})"
        )


#создание бронирования
@app.post("/bookings", response_model=BookingResponse, status_code=201)
def create_booking(booking: BookingCreate, db: Session = Depends(get_db)):
    """POST /bookings — создать бронирование"""

    room = db.query(Room).filter(Room.id == booking.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    check_booking_conflict(db, booking.room_id, booking.start_time, booking.end_time)

    db_booking = Booking(
        room_id=booking.room_id,
        start_time=booking.start_time,
        end_time=booking.end_time,
        user_name=booking.user_name,
        status="active"
    )
    db.add(db_booking)
    db.commit()
    db.refresh(db_booking)
    return db_booking


#отмена бронирования
@app.delete("/bookings/{booking_id}", status_code=200)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    """DELETE /bookings/{id} — отменить бронирование"""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Бронирование не найдено")

    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Бронирование уже отменено")

    booking.status = "cancelled"
    db.commit()
    return {"message": "Бронирование отменено"}


#получение бронирований комнаты на дату
@app.get("/rooms/{room_id}/bookings", response_model=List[BookingResponse])
def get_room_bookings(
        room_id: int,
        date: date = Query(..., description="Дата в формате YYYY-MM-DD"),
        db: Session = Depends(get_db)
):
    """GET /rooms/{id}/bookings?date=YYYY-MM-DD — бронирования на дату"""

    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Комната не найдена")

    day_start = datetime.combine(date, datetime.min.time())
    day_end = datetime.combine(date, datetime.max.time())

    bookings = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.start_time <= day_end,
        Booking.end_time >= day_start
    ).all()

    return bookings


#поиск свободных комнат
@app.get("/rooms/available", response_model=List[RoomResponse])
def get_available_rooms(
        start: datetime = Query(..., description="Время начала"),
        end: datetime = Query(..., description="Время окончания"),
        capacity: Optional[int] = Query(None, description="Минимальная вместимость"),
        db: Session = Depends(get_db)
):
    """GET /rooms/available?start=...&end=...&capacity=... — свободные комнаты"""

    if end <= start:
        raise HTTPException(status_code=400, detail="Время окончания должно быть позже начала")

    busy_room_ids = db.query(Booking.room_id).filter(
        Booking.status == "active",
        Booking.start_time < end,
        Booking.end_time > start
    ).subquery()
    query = db.query(Room).filter(~Room.id.in_(busy_room_ids))

    if capacity is not None:
        query = query.filter(Room.capacity >= capacity)

    return query.all()



def open_browser():
    """Открывает браузер через 1.5 секунды после запуска сервера"""
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")

# ДЛЯ ИНТЕРФЕЙСА

#для запросов из других источников
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#для папки
os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

#главная страница
@app.get("/")
def read_root():
    return FileResponse("static/index.html")
# ______________________________

if __name__ == "__main__":
    import uvicorn

    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=8000)