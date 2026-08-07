from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from sharp_scout.config import get_settings


class Base(DeclarativeBase):
    pass


class TeamRating(Base):
    __tablename__ = "team_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    team: Mapped[str] = mapped_column(String(8), index=True)
    off_epa: Mapped[float] = mapped_column(Float)
    def_epa: Mapped[float] = mapped_column(Float)
    off_success: Mapped[float] = mapped_column(Float, default=0.0)
    def_success: Mapped[float] = mapped_column(Float, default=0.0)
    off_ypp: Mapped[float] = mapped_column(Float, default=0.0)
    def_ypp: Mapped[float] = mapped_column(Float, default=0.0)
    qb_starter_epa: Mapped[float] = mapped_column(Float, default=0.0)
    qb_backup_epa: Mapped[float] = mapped_column(Float, default=0.0)
    power: Mapped[float] = mapped_column(Float, default=0.0)


class GameSnapshot(Base):
    __tablename__ = "game_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    commence_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    home_team: Mapped[str] = mapped_column(String(8))
    away_team: Mapped[str] = mapped_column(String(8))
    model_spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    model_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p_home_win: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharp_spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharp_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    market: Mapped[str] = mapped_column(String(32))  # spread | total | h2h
    side: Mapped[str] = mapped_column(String(32))
    line: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    book: Mapped[str] = mapped_column(String(64))
    price: Mapped[float] = mapped_column(Float)
    p_true: Mapped[float] = mapped_column(Float)
    p_mkt: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    edge: Mapped[float] = mapped_column(Float)
    filter_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    filter_notes: Mapped[str] = mapped_column(Text, default="")
    tier: Mapped[str] = mapped_column(String(32), default="candidate")
    rationale: Mapped[str] = mapped_column(Text, default="")


def get_engine():
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, future=True, connect_args=connect_args)


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, future=True)


def get_session():
    engine = get_engine()
    SessionLocal.configure(bind=engine)
    return SessionLocal()