import os
import time
import uuid
from pathlib import Path

from sqlalchemy import JSON, Boolean, Float, Integer, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def uid():
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    password: Mapped[str] = mapped_column(String(255))


class Session(Base):
    __tablename__ = 'sessions'
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    expires: Mapped[float] = mapped_column(Float)


class OfficerProfile(Base):
    __tablename__ = 'officer_profiles'
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    department: Mapped[str] = mapped_column(String(80))
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    capacity: Mapped[int] = mapped_column(Integer, default=5)
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    __mapper_args__ = {'version_id_col': version}


class CapacityChange(Base):
    __tablename__ = 'capacity_changes'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    officer_id: Mapped[str] = mapped_column(String(32), index=True)
    modified_by: Mapped[str] = mapped_column(String(32))
    modified_at: Mapped[float] = mapped_column(Float, default=time.time)
    data: Mapped[dict] = mapped_column(JSON)


class Case(Base):
    __tablename__ = 'cases'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    tracking_hash: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    updated: Mapped[float] = mapped_column(Float, default=time.time)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    __mapper_args__ = {'version_id_col': version}


class Group(Base):
    __tablename__ = 'incident_groups'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON)
    __mapper_args__ = {'version_id_col': version}


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    case_id: Mapped[str] = mapped_column(String(32), default='')
    state: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_at: Mapped[float] = mapped_column(Float, default=time.time)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str] = mapped_column(String(200), default='')


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(255), unique=True)
    created: Mapped[float] = mapped_column(Float, default=time.time)
    state: Mapped[str] = mapped_column(String(30), default='recorded')
    data: Mapped[dict] = mapped_column(JSON)


class Attachment(Base):
    __tablename__ = 'attachments'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(150))
    mime: Mapped[str] = mapped_column(String(40))


class Limit(Base):
    __tablename__ = 'rate_limits'
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    expires: Mapped[float] = mapped_column(Float)


def connect(url=None):
    Path('.local').mkdir(exist_ok=True)
    url = url or os.getenv('DATABASE_URL', 'sqlite:///.local/safespot.db')
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def configure(connection, _):
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
