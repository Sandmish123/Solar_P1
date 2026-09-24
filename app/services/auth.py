"""Password hashing and sign-in.

bcrypt directly rather than passlib: hashing is two calls, and passlib 1.7.4 breaks
against bcrypt 4.x. Session cookies rather than JWT, because the SPA is same-origin and
a cookie is simpler to revoke.
"""
import bcrypt
from sqlalchemy.orm import Session

from app.models.user import User

# bcrypt silently truncates at 72 bytes, which would make two different long passwords
# equivalent. Rejected at the schema boundary instead; this is the same limit.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in the row: treat as a failed login, never as a pass.
        return False


def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email.strip().lower()).first()


def authenticate(db: Session, email: str, password: str):
    """The signed-in user, or None. Verifies the password even when the account is
    missing or disabled, so timing does not reveal which emails exist."""
    user = get_user_by_email(db, email)
    candidate_hash = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(password, candidate_hash)

    if user is None or not user.is_active or not password_ok:
        return None
    return user


# Hashed once at import so a login for an unknown email costs the same as a real one.
_DUMMY_HASH = hash_password("invalid-placeholder-password")
