"""Server-side Google ID token verification (signature, issuer, audience, expiry via google-auth)."""
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleAuthError(Exception):
    pass


def verify_google_id_token(token: str) -> dict:
    """Return validated claims: {sub, email, email_verified, name}. Raises GoogleAuthError."""
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise GoogleAuthError("Google sign-in is not configured.")
    try:
        claims = id_token.verify_oauth2_token(token, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID)
    except ValueError as exc:  # bad signature / audience / issuer / expired
        raise GoogleAuthError("Invalid Google token.") from exc
    if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleAuthError("Invalid issuer.")
    if not claims.get("sub") or not claims.get("email"):
        raise GoogleAuthError("Missing claims.")
    return {"sub": claims["sub"], "email": claims["email"].lower(),
            "email_verified": claims.get("email_verified") is True, "name": claims.get("name", "")}
