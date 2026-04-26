"""SQLAlchemy ORM models. Schema matches the brief in the research notes."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Snapshot(Base):
    """One row per option-chain pull (per ticker, per timestamp)."""

    __tablename__ = "snapshots"

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    spot: Mapped[float] = mapped_column(Float, nullable=False)
    risk_free: Mapped[float] = mapped_column(Float, nullable=False)
    div_yield: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="yfinance")

    quotes: Mapped[list["OptionQuote"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True
    )
    metrics: Mapped["DerivedMetrics | None"] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )

    __table_args__ = (
        UniqueConstraint("ticker", "snapshot_ts", name="uq_snapshots_ticker_ts"),
        Index("ix_snap_ticker_ts", "ticker", "snapshot_ts"),
    )


class OptionQuote(Base):
    """Per-strike, per-expiry option row inside a snapshot."""

    __tablename__ = "option_quotes"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"), primary_key=True
    )
    expiry: Mapped[date] = mapped_column(Date, primary_key=True)
    strike: Mapped[float] = mapped_column(Float, primary_key=True)
    cp: Mapped[str] = mapped_column(String(1), primary_key=True)  # 'C' or 'P'

    dte: Mapped[int] = mapped_column(Integer, nullable=False)
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float)
    mid: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)
    iv_yahoo: Mapped[float | None] = mapped_column(Float)
    iv_recalc: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)
    gamma: Mapped[float | None] = mapped_column(Float)
    vega: Mapped[float | None] = mapped_column(Float)
    theta: Mapped[float | None] = mapped_column(Float)
    charm: Mapped[float | None] = mapped_column(Float)
    vanna: Mapped[float | None] = mapped_column(Float)
    last_trade_ts: Mapped[datetime | None] = mapped_column(DateTime)

    snapshot: Mapped[Snapshot] = relationship(back_populates="quotes")

    __table_args__ = (Index("ix_oq_expiry", "snapshot_id", "expiry"),)


class DerivedMetrics(Base):
    """One row per snapshot — pre-aggregated dashboard metrics."""

    __tablename__ = "derived_metrics"

    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("snapshots.snapshot_id", ondelete="CASCADE"), primary_key=True
    )

    total_gex: Mapped[float | None] = mapped_column(Float)
    zero_gamma: Mapped[float | None] = mapped_column(Float)
    call_wall: Mapped[float | None] = mapped_column(Float)
    put_wall: Mapped[float | None] = mapped_column(Float)
    max_pain_30d: Mapped[float | None] = mapped_column(Float)
    rr25_30d: Mapped[float | None] = mapped_column(Float)
    skew_90_110_30d: Mapped[float | None] = mapped_column(Float)
    atm_iv_7: Mapped[float | None] = mapped_column(Float)
    atm_iv_30: Mapped[float | None] = mapped_column(Float)
    atm_iv_90: Mapped[float | None] = mapped_column(Float)
    term_slope: Mapped[float | None] = mapped_column(Float)
    pcr_vol: Mapped[float | None] = mapped_column(Float)
    pcr_oi: Mapped[float | None] = mapped_column(Float)
    rv_yz_21: Mapped[float | None] = mapped_column(Float)
    vrp_30: Mapped[float | None] = mapped_column(Float)
    implied_move_weekly: Mapped[float | None] = mapped_column(Float)

    snapshot: Mapped[Snapshot] = relationship(back_populates="metrics")


class UnderlyingBar(Base):
    """Daily OHLCV for the underlying — fuels realised-vol computations."""

    __tablename__ = "underlying_bars"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    bar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int | None] = mapped_column(Integer)
