from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import SESSION_USER_KEY, current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, UserResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = auth_service.authenticate(db, payload.email, payload.password)
    if user is None:
        # One message for unknown email and wrong password alike: never confirm
        # which addresses have accounts.
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    # Drop any previous session identifier before adopting the new one.
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    return user


@router.post("/logout", status_code=204)
def logout(request: Request):
    request.session.clear()


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return user
