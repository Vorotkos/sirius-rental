from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base


# Модель комнаты
class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    capacity = Column(Integer)
    equipment = Column(String)


    #связь с бронированиями
    bookings = relationship("Booking", back_populates="room")


#модель бронирования
class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    user_name = Column(String)
    status = Column(String, default="active")

    #связь с комнатой
    room = relationship("Room", back_populates="bookings")

