from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    memberships: Mapped[list[HouseMembership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class House(Base):
    __tablename__ = "houses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    invite_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    memberships: Mapped[list[HouseMembership]] = relationship(back_populates="house", cascade="all, delete-orphan")


class HouseMembership(Base):
    __tablename__ = "house_memberships"
    __table_args__ = (UniqueConstraint("user_id", "house_id", name="uq_membership_user_house"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="memberships")
    house: Mapped[House] = relationship(back_populates="memberships")


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("house_id", "name", name="uq_category_house_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int | None] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"), index=True)
    paid_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    purchased_on: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    split_method: Mapped[str] = mapped_column(String(20))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    payer: Mapped[User] = relationship(foreign_keys=[paid_by_id])
    category: Mapped[Category] = relationship()
    splits: Mapped[list[PurchaseSplit]] = relationship(back_populates="purchase", cascade="all, delete-orphan")


class PurchaseSplit(Base):
    __tablename__ = "purchase_splits"
    __table_args__ = (UniqueConstraint("purchase_id", "user_id", name="uq_purchase_split_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_owed_cents: Mapped[int] = mapped_column(Integer)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    purchase: Mapped[Purchase] = relationship(back_populates="splits")
    user: Mapped[User] = relationship()


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    house_id: Mapped[int] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"), index=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    settled_on: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    method: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    from_user: Mapped[User] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped[User] = relationship(foreign_keys=[to_user_id])

