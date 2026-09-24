from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.auth import MAX_PASSWORD_BYTES


class LoginRequest(BaseModel):
    # Plain str, not EmailStr: that needs the email-validator package, and the address
    # is only ever looked up, never sent to.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def within_bcrypt_limit(cls, value: str) -> str:
        # bcrypt truncates past 72 bytes, which would make two long passwords
        # equivalent. Reject rather than silently accept a weaker password.
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
        return value


class UserResponse(BaseModel):
    id: int
    org_id: int
    email: str
    name: str | None = None
    role: str

    model_config = ConfigDict(from_attributes=True)
