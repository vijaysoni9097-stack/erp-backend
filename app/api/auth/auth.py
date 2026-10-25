"""Hosted authentication and revocable sessions."""

from hashlib import sha256

from fastapi import Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import AuthSession, PharmacistProfile
from app.schemas import LoginRequest, LoginResponse, PharmacistProfileRead
from app.services.auth import bearer_scheme, create_session, get_current_profile
from app.services.security import hash_secret, verify_secret
from app.schemas import ForgotPasswordRequest, ForgotPasswordResponse, ResetPasswordRequest
from app.services.password_reset import request_password_reset, reset_password

# Perform password hashing even for unknown accounts to reduce timing differences.
DUMMY_HASH = hash_secret("unused-dummy-password")


class AuthAPI(BaseAPI):
    public = True
    methods = ["POST", "GET"]
    routes = [
        RouteDefinition("/api/v1/auth/forgot-password", "forgot_password", "POST",
                        response_model=ForgotPasswordResponse, status_code=202, tags=["Authentication"]),
        RouteDefinition("/api/v1/auth/reset-password", "reset_password", "POST",
                        status_code=204, tags=["Authentication"]),
        RouteDefinition("/api/v1/auth/login", "login", "POST", response_model=LoginResponse,
                        tags=["Authentication"]),
        RouteDefinition("/api/v1/auth/me", "me", "GET", response_model=PharmacistProfileRead,
                        tags=["Authentication"]),
        RouteDefinition("/api/v1/auth/logout", "logout", "POST", status_code=204,
                        tags=["Authentication"]),
    ]

    @staticmethod
    def forgot_password(payload: ForgotPasswordRequest, response: Response,
                        db: Session = Depends(get_db)) -> ForgotPasswordResponse:
        response.headers["Cache-Control"] = "no-store"
        request_password_reset(db, payload.email)
        return ForgotPasswordResponse()

    @staticmethod
    def reset_password(payload: ResetPasswordRequest, response: Response,
                       db: Session = Depends(get_db)) -> None:
        response.headers["Cache-Control"] = "no-store"
        reset_password(db, payload.token, payload.new_password)

    @staticmethod
    def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> LoginResponse:
        profile = db.scalar(select(PharmacistProfile).where(
            func.lower(PharmacistProfile.email) == payload.email.strip().lower()
        ))
        valid = verify_secret(payload.password, profile.password_hash if profile and profile.password_hash else DUMMY_HASH)
        if not valid or profile is None or profile.password_hash is None:
            raise HTTPException(status_code=401, detail="Invalid email or password",
                                headers={"WWW-Authenticate": "Bearer"})
        from app.config import get_settings
        token, expires_at = create_session(db, profile)
        response.headers["Cache-Control"] = "no-store"
        return LoginResponse(access_token=token, expires_at=expires_at, profile=profile)

    @staticmethod
    def me(profile: PharmacistProfile = Depends(get_current_profile)):
        return profile

    @staticmethod
    def logout(profile: PharmacistProfile = Depends(get_current_profile),
               credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
               db: Session = Depends(get_db)) -> None:
        db.execute(delete(AuthSession).where(
            AuthSession.profile_id == profile.id,
            AuthSession.token_hash == sha256(credentials.credentials.encode()).hexdigest(),
        ))
        db.commit()
