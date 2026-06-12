from pydantic import BaseModel, field_validator


class PushTokenIn(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def token_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("token must not be blank")
        return v
