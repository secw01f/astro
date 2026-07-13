from pydantic import BaseModel
from typing import Optional

from lib.auth.enums import Role
from src.db.models import UserPublic

class Login(BaseModel):
    username: str
    password: str

class CreateUser(BaseModel):
    username: str
    email: str
    password: Optional[str] = None
    role: Role


class CreateUserResponse(BaseModel):
    user: UserPublic
    temporary_password: Optional[str] = None

class ResetPassword(BaseModel):
    token: str
    new_password: str

class UpdateUser(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    role: Optional[Role] = None
    enabled: Optional[bool] = None

class UpdateMe(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    new_password: Optional[str] = None
    current_password: Optional[str] = None
