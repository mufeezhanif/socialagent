"""Print fresh random values for the secret env vars."""

import secrets

for name in ("JWT_SECRET", "TOKEN_ENCRYPTION_KEY", "MEDIA_SIGNING_SECRET", "INTERNAL_SHARED_SECRET"):
    print(f"{name}={secrets.token_urlsafe(48)}")
