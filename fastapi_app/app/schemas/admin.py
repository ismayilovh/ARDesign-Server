"""Schemas for the admin panel. Response models never expose the password hash."""
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.patent import ConversionStatus, FileType
from app.models.review import ReviewState
from app.models.user import UserRole


# -- Users ---------------------------------------------------------------------

class AdminUserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: UserRole
    is_active: bool
    date_of_birth: date | None = None
    date_joined: datetime
    last_login: datetime | None = None
    patent_count: int


class AdminUserUpdate(BaseModel):
    """PATCH payload — only the provided fields are changed."""
    role: UserRole | None = None
    is_active: bool | None = None


# -- Designs -------------------------------------------------------------------

class AdminPatentItem(BaseModel):
    id: int
    user_id: int
    owner_username: str
    owner_email: str
    model_filename: str | None = None
    file_type: FileType | None = None
    status: ConversionStatus
    review_state: ReviewState
    uploaded_at: datetime
    locarno_main_class: str | None = None
    locarno_subclass: str | None = None
    conversion_error: str | None = None


# -- Locarno: main classes -----------------------------------------------------

class MainClassCreate(BaseModel):
    value: str = Field(min_length=1, max_length=32)
    number: int
    label: str = Field(min_length=1, max_length=255)
    sort_index: int | None = None


class MainClassUpdate(BaseModel):
    number: int | None = None
    label: str | None = Field(default=None, min_length=1, max_length=255)
    sort_index: int | None = None


class MainClassOut(BaseModel):
    value: str
    number: int
    label: str
    sort_index: int

    class Config:
        from_attributes = True


# -- Locarno: subclasses -------------------------------------------------------

class SubclassCreate(BaseModel):
    value: str = Field(min_length=1, max_length=255)
    main_class_value: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=512)
    locarno_id: int | None = None
    sort_index: int | None = None


class SubclassUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=512)
    locarno_id: int | None = None
    sort_index: int | None = None


class SubclassOut(BaseModel):
    value: str
    main_class_value: str
    label: str
    locarno_id: int | None
    sort_index: int

    class Config:
        from_attributes = True


# -- Locarno: reorder ----------------------------------------------------------

class ReorderRequest(BaseModel):
    """Ordered list of entry `value`s; the server rewrites sort_index to match."""
    ordered_values: list[str] = Field(min_length=1)


# -- Locarno: whole-tree transactional update ----------------------------------

class TreeSubclassInput(BaseModel):
    value: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=512)
    # Position in the list implies sort_index; omitting locarno_id preserves the
    # existing value (it is never cleared by an edit).
    locarno_id: int | None = None


class TreeMainClassInput(BaseModel):
    value: str = Field(min_length=1, max_length=32)
    number: int
    label: str = Field(min_length=1, max_length=255)
    subclasses: list[TreeSubclassInput] = Field(default_factory=list)


class LocarnoTreeUpdate(BaseModel):
    """Desired end-state of the whole tree. The server diffs it against the DB
    and applies inserts/updates/deletes in one transaction. List order is the
    sort order. Entry identity is `value` (immutable); a changed label is a
    rename, a missing value is a delete, a new value is an insert."""
    main_classes: list[TreeMainClassInput] = Field(default_factory=list)
