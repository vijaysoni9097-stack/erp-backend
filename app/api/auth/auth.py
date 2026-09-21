from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import PharmacistProfile
from app.schemas import LoginRequest, LoginResponse
from app.services.security import verify_secret


class AuthAPI(BaseAPI):
    methods = ["POST"]
    routes = [
        RouteDefinition(
            "/api/v1/auth/login",
            "login",
            "POST",
            response_model=LoginResponse,
            status_code=status.HTTP_200_OK,
            summary="Authenticate a pharmacist and return the profile",
            tags=["Authentication"],
        )
    ]

    @staticmethod
    def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
        """Validate a pharmacist email/password pair and return the profile on success."""
        profile = db.scalar(
            select(PharmacistProfile).where(PharmacistProfile.email.ilike(payload.email))
        )

        if profile is None or profile.password_hash is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        if not verify_secret(payload.password, profile.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

        return LoginResponse(success=True, profile=profile)
