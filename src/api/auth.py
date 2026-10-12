"""Shared authentication without importing the production application."""
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from config.settings import get_settings

bearer = HTTPBearer(auto_error=False)


def require_fantasy_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    token = get_settings().fantasy_api_token
    if (not token or credentials is None or credentials.scheme.lower() != 'bearer'
            or not secrets.compare_digest(credentials.credentials.encode(), token.encode())):
        raise HTTPException(status_code=401, detail='Fantasy API authentication required')
