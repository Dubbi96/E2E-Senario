from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import re

from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password, decode_access_token
from app.db.session import get_db
from app.db.models import User


router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


class RegisterIn(BaseModel):
    """
    회원가입 요청 모델.

    비밀번호 정책:
    - 최소 12자
    - 영문 1개 이상 + 숫자 1개 이상 포함
    - 최대 128자 (DoS 방지)
    """

    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # 정책(초기 서비스 기본값):
        # - 최소 12자
        # - 영문/숫자 포함
        # - 너무 긴 값(DoS 방지 차원)
        if len(v) < 12:
            raise ValueError("비밀번호는 최소 12자 이상이어야 합니다.")
        if len(v) > 128:
            raise ValueError("비밀번호는 최대 128자까지 허용됩니다.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("비밀번호는 영문을 1개 이상 포함해야 합니다.")
        if not re.search(r"\d", v):
            raise ValueError("비밀번호는 숫자를 1개 이상 포함해야 합니다.")
        return v


class TokenOut(BaseModel):
    """로그인 성공 시 반환되는 액세스 토큰(JWT) 응답."""

    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """사용자 기본 정보(민감정보 제외)."""

    id: str
    email: EmailStr


def get_current_user(db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)) -> User:
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid token")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="inactive user")
    return user


@router.post("/register", response_model=UserOut)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """
    ## 회원가입

    - **권한**: 인증 불필요
    - **처리**:
      - 이메일 중복 확인
      - 비밀번호 정책 검증(최소 12자/영문+숫자 포함/최대 128자)
      - 비밀번호는 DB에 평문 저장하지 않고 **해시(bcrypt_sha256)** 로 저장
    - **응답**: 생성된 user id/email
    - **에러**:
      - 409: 이메일 중복
      - 422: 입력 검증 실패(이메일 형식/비밀번호 정책)
    """
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="email already registered")
    user = User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut(id=user.id, email=user.email)


@router.post("/token", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    ## 로그인(OAuth2 Password Flow)

    - **권한**: 인증 불필요
    - **요청 형식**: `application/x-www-form-urlencoded`
      - `username`: 이메일
      - `password`: 비밀번호
    - **처리**:
      - 이메일로 사용자 조회
      - 비밀번호 해시 검증
      - 성공 시 JWT access token 발급
    - **응답**: `{ access_token, token_type="bearer" }`
    - **에러**:
      - 401: 자격증명 오류
    """
    # OAuth2PasswordRequestForm uses `username` field; we treat it as email.
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = create_access_token(subject=user.id)
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """
    ## 내 정보 조회

    - **권한**: 로그인 필요(Bearer JWT)
    - **처리**: 토큰의 `sub`(user_id)로 사용자 조회 후 반환
    - **에러**:
      - 401: 토큰이 없거나/유효하지 않거나/비활성 사용자
    """
    return UserOut(id=user.id, email=user.email)


