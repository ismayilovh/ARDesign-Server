# Import all models here so that Base.metadata is fully populated
# before Alembic or create_all() is called.
from app.models.locarno import LocarnoMainClassRow, LocarnoSubclassRow
from app.models.patent import Patent
from app.models.review import DesignReview
from app.models.user import User

__all__ = ["LocarnoMainClassRow", "LocarnoSubclassRow", "Patent", "DesignReview", "User"]