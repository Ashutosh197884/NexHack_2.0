"""Shared dependencies: current-user bearer auth."""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.base import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing bearer token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = decode_access_token(creds.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, detail={"error": "token expired"}) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, detail={"error": "invalid token"}) from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, detail={"error": "unknown user"})
    return user
