from pydantic import BaseModel, Field

from app.models.enums import UserRole, UserStatus
from app.schemas.auth import UserSummary


class UserListResponse(BaseModel):
    users: list[UserSummary]
    total: int
    limit: int
    offset: int


class UpdateUserStatusRequest(BaseModel):
    status: UserStatus


class UpdateUserRoleRequest(BaseModel):
    role: UserRole


class AdminActionResponse(BaseModel):
    user: UserSummary
    message: str = Field(default="Updated")
