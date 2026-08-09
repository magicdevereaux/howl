import re

from pydantic import BaseModel, field_validator

# Expo's own shape: "ExponentPushToken[...]" (the common case) or the older
# "ExpoPushToken[...]" alias, wrapping a non-empty opaque identifier. This is
# not a proof of device -- GAPS #57 is explicit that a signed device
# attestation is a separate, out-of-scope design decision -- it just stops
# garbage strings from accumulating in the table and being sent to Expo's API
# on every notification for no reason.
_EXPO_TOKEN_RE = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_-]+\]$")


class PushTokenIn(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def token_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("token must not be blank")
        return v

    @field_validator("token")
    @classmethod
    def token_matches_expo_shape(cls, v: str) -> str:
        if not _EXPO_TOKEN_RE.match(v):
            raise ValueError(
                "token must look like ExponentPushToken[...] or ExpoPushToken[...]"
            )
        return v

