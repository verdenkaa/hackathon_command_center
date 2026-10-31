"""Аутентификация: вход, выход, текущий пользователь."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.deps import SESSION_COOKIE, active_roles, get_current_user, get_db
from app.schemas import LoginRequest, MeOut, RoleOut, UserOut
from app.security import hash_token
from app.config import settings
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> UserOut:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user, raw_token = auth_service.authenticate(db, body.login, body.password, ip, user_agent)
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=request.url.scheme == "https" or (settings.app_managed and request.headers.get("x-forwarded-proto") == "https"),
        samesite="lax",
        max_age=int(auth_service.SESSION_TTL.total_seconds()),
    )
    return UserOut.model_validate(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_service.revoke_session(db, hash_token(token))
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


@router.get("/me", response_model=MeOut)
def me(user=Depends(get_current_user), db: Session = Depends(get_db)) -> MeOut:
    roles = [RoleOut.model_validate(a) for a in active_roles(db, user.id)]
    out = MeOut.model_validate(user)
    out.roles = roles
    out.managed = settings.app_managed
    return out
