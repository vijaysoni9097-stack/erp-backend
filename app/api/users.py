"""Superadmin-only employee administration."""
from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.base import BaseAPI, RouteDefinition
from app.database import get_db
from app.models import AuthSession, PasswordResetToken, PharmacistProfile
from app.models.settings import EmployeeRole
from app.schemas import PharmacistProfileBase
from app.services.auth import get_current_profile
from app.services.security import hash_secret


class CreateUser(PharmacistProfileBase):
    model_config = ConfigDict(extra='forbid')
    role: EmployeeRole = EmployeeRole.pharmacist
    password: str = Field(min_length=12, max_length=128)


class AdminPassword(BaseModel):
    model_config = ConfigDict(extra='forbid')
    new_password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    first_name: str
    last_name: str
    email: str
    role: EmployeeRole


class UserCreated(UserRead):
    welcome_email_status: str


def superadmin(profile=Depends(get_current_profile)):
    if profile.role != EmployeeRole.superadmin:
        raise HTTPException(403, 'Superadmin access required')
    return profile


def target_user(db, user_id, actor):
    if user_id == actor.id:
        raise HTTPException(400, 'Use your own profile settings for this account')
    user = db.get(PharmacistProfile, user_id)
    if user is None:
        raise HTTPException(404, 'User not found')
    return user


class UsersAPI(BaseAPI):
    methods = ['GET', 'POST', 'DELETE']
    routes = [
        RouteDefinition('/api/v1/users', 'list_users', 'GET', response_model=list[UserRead], tags=['Users']),
        RouteDefinition('/api/v1/users', 'create_user', 'POST', response_model=UserCreated, status_code=201, tags=['Users']),
        RouteDefinition('/api/v1/users/{user_id}', 'delete_user', 'DELETE', status_code=204, tags=['Users']),
        RouteDefinition('/api/v1/users/{user_id}/reset-password', 'reset_user_password', 'POST', status_code=204, tags=['Users']),
    ]

    @staticmethod
    def list_users(response: Response, actor=Depends(superadmin), db: Session = Depends(get_db)):
        response.headers['Cache-Control'] = 'no-store'
        return db.scalars(select(PharmacistProfile).order_by(PharmacistProfile.id)).all()

    @staticmethod
    def create_user(payload: CreateUser, actor=Depends(superadmin), db: Session = Depends(get_db)):
        from app.services.cloud_sync import require_local_identity_mode
        require_local_identity_mode()
        if db.scalar(select(PharmacistProfile.id).where(func.lower(PharmacistProfile.email) == payload.email)):
            raise HTTPException(409, 'Email address is already in use')
        user = PharmacistProfile(**payload.model_dump(exclude={'password'}), password_hash=hash_secret(payload.password))
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'Email address or professional license number is already in use')
        db.refresh(user)
        from app.services.welcome_email import send_welcome_email
        # Delivery failure must not roll back the account or invite duplicate creation.
        status = send_welcome_email(user)
        return UserCreated(**UserRead.model_validate(user).model_dump(), welcome_email_status=status)

    @staticmethod
    def delete_user(user_id: int, actor=Depends(superadmin), db: Session = Depends(get_db)):
        from app.services.cloud_sync import require_local_identity_mode
        require_local_identity_mode()
        if user_id == actor.id:
            raise HTTPException(400, 'You cannot delete your own account')
        user = target_user(db, user_id, actor)
        if user.role == EmployeeRole.superadmin:
            raise HTTPException(403, 'Superadmin accounts cannot be deleted')
        db.execute(delete(AuthSession).where(AuthSession.profile_id == user.id))
        db.execute(delete(PasswordResetToken).where(PasswordResetToken.profile_id == user.id))
        db.delete(user)
        db.commit()

    @staticmethod
    def reset_user_password(user_id: int, payload: AdminPassword, actor=Depends(superadmin), db: Session = Depends(get_db)):
        from app.services.cloud_sync import require_local_identity_mode
        require_local_identity_mode()
        user = target_user(db, user_id, actor)
        if payload.new_password != payload.confirm_password:
            raise HTTPException(422, 'New password and confirmation must match')
        user.password_hash = hash_secret(payload.new_password)
        db.execute(delete(AuthSession).where(AuthSession.profile_id == user.id))
        db.execute(delete(PasswordResetToken).where(PasswordResetToken.profile_id == user.id))
        db.commit()
