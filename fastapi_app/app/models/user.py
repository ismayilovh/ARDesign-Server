import enum
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.patent import Patent


class UserRole(str, enum.Enum):
    """Application role. Replaces the dormant Django-era is_staff/is_superuser
    flags as the single source of truth for authorization.

    EXPERT is strictly separate from ADMIN: experts evaluate design submissions
    but get no admin panel; admins run the admin panel (and assign the EXPERT
    role) but cannot evaluate submissions."""
    USER = "USER"
    ADMIN = "ADMIN"
    EXPERT = "EXPERT"


class User(Base):
    __tablename__ = "users_user"

    # --- identity ---
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, default="")
    password: Mapped[str] = mapped_column(String(128), nullable=False)

    # --- personal info ---
    first_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # --- permissions ---
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Active admin-panel authorization gate. The is_staff/is_superuser columns
    # below are inherited from the Django schema and intentionally unused.
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole_enum"),
        nullable=False,
        default=UserRole.USER,
        server_default=UserRole.USER.value,
    )
    is_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- timestamps ---
    date_joined: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- relationships ---
    patents: Mapped[List["Patent"]] = relationship(
        "Patent", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"
