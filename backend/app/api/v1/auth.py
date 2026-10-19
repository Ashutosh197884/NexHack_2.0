"""Auth routes — register, login, me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import get_db
from app.models import User
from app.schemas.transactions import (
    LoginRequest, RegisterRequest, TokenResponse, UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse,
             status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, detail={"error": "email already registered"})
    user = User(name=body.name.strip(), email=email,
                password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail={"error": "email already registered"})
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut(id=user.id, name=user.name, email=user.email,
                     created_at=user.created_at),
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if user is None or not user.password_hash or not verify_password(
            body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail={"error": "invalid email or password"})
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserOut(id=user.id, name=user.name, email=user.email,
                     created_at=user.created_at),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return UserOut(id=user.id, name=user.name, email=user.email,
                   created_at=user.created_at)
