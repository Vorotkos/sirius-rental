from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from main import app, get_db, Base, Room, Booking

TEST_DATABASE_URL = "sqlite:///./data/test_rooms.db"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False}
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


def setup_module():
    """Вызывается один раз перед всеми тестами"""
    Base.metadata.create_all(bind=test_engine)


def setup_function(function):
    """Вызывается перед каждым тестом"""
    db = TestSessionLocal()
    try:
        db.query(Booking).delete()
        db.query(Room).delete()
        db.commit()
    finally:
        db.close()


def teardown_module():
    """Вызывается один раз после всех тестов"""
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    import os
    import time
    time.sleep(0.1)
    if os.path.exists("./data/test_rooms.db"):
        try:
            os.remove("./data/test_rooms.db")
        except PermissionError:
            pass

def test_create_room():
    """Тест создания комнаты"""
    response = client.post("/rooms", json={
        "name": "Тестовая комната",
        "capacity": 10,
        "equipment": "Проектор"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Тестовая комната"
    assert data["capacity"] == 10
    assert "id" in data


def test_get_rooms():
    """Тест получения списка комнат"""
    response = client.get("/rooms")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_create_booking():
    """Тест создания бронирования"""
    room_response = client.post("/rooms", json={
        "name": "Комната для брони",
        "capacity": 5
    })
    room_id = room_response.json()["id"]

    response = client.post("/bookings", json={
        "room_id": room_id,
        "start_time": "2026-07-14T10:00:00",
        "end_time": "2026-07-14T11:00:00",
        "user_name": "Тестовый пользователь"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["room_id"] == room_id
    assert data["status"] == "active"


def test_booking_conflict():
    """Тест конфликта бронирований (409 Conflict)"""
    room_response = client.post("/rooms", json={
        "name": "Комната для конфликта",
        "capacity": 5
    })
    room_id = room_response.json()["id"]

    client.post("/bookings", json={
        "room_id": room_id,
        "start_time": "2026-07-15T10:00:00",
        "end_time": "2026-07-15T12:00:00",
        "user_name": "Пользователь 1"
    })

    response = client.post("/bookings", json={
        "room_id": room_id,
        "start_time": "2026-07-15T11:00:00",
        "end_time": "2026-07-15T13:00:00",
        "user_name": "Пользователь 2"
    })
    assert response.status_code == 409
    assert "пересекается" in response.json()["detail"].lower()


def test_cancel_booking():
    """Тест отмены бронирования"""
    room_response = client.post("/rooms", json={
        "name": "Комната для отмены",
        "capacity": 5
    })
    room_id = room_response.json()["id"]

    booking_response = client.post("/bookings", json={
        "room_id": room_id,
        "start_time": "2026-07-16T10:00:00",
        "end_time": "2026-07-16T11:00:00",
        "user_name": "Пользователь"
    })
    booking_id = booking_response.json()["id"]

    response = client.delete(f"/bookings/{booking_id}")
    assert response.status_code == 200
    assert "отменено" in response.json()["message"].lower()



def test_room_not_found():
    """Тест получения несуществующей комнаты (404)"""
    response = client.get("/rooms/99999")
    assert response.status_code == 404
    assert "не найдена" in response.json()["detail"].lower()