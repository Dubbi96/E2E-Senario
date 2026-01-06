from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings


# NOTE:
# bcrypt는 입력을 72 bytes로 제한합니다. (UTF-8 기준 한글/이모지 포함 시 쉽게 초과)
# 서비스 입력 비밀번호를 그대로 bcrypt에 넣으면 500이 발생할 수 있어,
# passlib의 bcrypt_sha256(사전 SHA-256 후 bcrypt 적용)로 전환합니다.
#
# 이미 생성된 계정이 bcrypt 해시를 가지고 있을 수 있으므로,
# verify 호환을 위해 bcrypt도 함께 허용합니다(신규 hash는 bcrypt_sha256 사용).
pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(*, subject: str, expires_minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": exp}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


