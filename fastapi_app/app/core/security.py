from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# Capability tokens for the media routes. Distinct scope and NO `sub`, so a
# leaked media token can't be used as a login (get_current_user rejects it) and
# an access token can't be used as a media token (verify checks the scope).
MEDIA_TOKEN_SCOPE = "media"
MEDIA_TOKEN_TTL = timedelta(minutes=60)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return pwd_context.verify(raw, hashed)


def create_access_token(subject: int, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    return jwt.encode(
        {"sub": str(subject), "exp": expire},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token(subject: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return jwt.encode(
        {"sub": str(subject), "exp": expire, "type": "refresh"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_media_token(patent_id: int, expires_delta: timedelta | None = None) -> str:
    """A short-lived, read-only capability token for one patent's media. Encoded
    in QR links so an unauthenticated scanner can fetch a not-yet-public design's
    model. Scoped to a single patent and expires (default 60 min)."""
    expire = datetime.now(timezone.utc) + (expires_delta or MEDIA_TOKEN_TTL)
    return jwt.encode(
        {"pid": patent_id, "scope": MEDIA_TOKEN_SCOPE, "exp": expire},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_media_token(token: str, patent_id: int) -> bool:
    """True if `token` is a valid, unexpired media token for exactly this patent."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return False
    return payload.get("scope") == MEDIA_TOKEN_SCOPE and payload.get("pid") == patent_id
