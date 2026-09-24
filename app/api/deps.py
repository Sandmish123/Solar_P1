"""Request dependencies shared by the routers."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.user import User

SESSION_USER_KEY = "user_id"


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The signed-in user, or 401. Every data route depends on this."""
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not signed in")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        # Deleted or disabled since the cookie was issued.
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not signed in")
    return user
