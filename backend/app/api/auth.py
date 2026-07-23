"""认证路由：注册 / 登录 / 短信验证码。"""
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ..deps import DBSession, create_access_token
from ..models import User
from ..schemas import (
    UserCreate,
    UserLogin,
    UserOut,
    TokenOut,
    build_user_out,
    SmsSendIn,
    PhoneLoginIn,
)
from ..security import hash_password, verify_password
from ..services.sms_service import normalize_phone, send_code, verify_code

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/sms/send")
def sms_send(payload: SmsSendIn, db: DBSession) -> dict:
    return send_code(db, payload.phone, payload.scene)


@router.post("/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, db: DBSession) -> UserOut:
    if payload.role == "admin":
        raise HTTPException(status_code=403, detail="管理员账号仅能由系统管理员创建")
    phone = normalize_phone(payload.phone)
    verify_code(db, phone, "register", payload.code, consume=True)
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=400, detail="用户名已存在")
    if db.scalar(select(User).where(User.phone == phone)):
        raise HTTPException(status_code=400, detail="该手机号已注册")
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        display_name=payload.display_name or payload.username,
        phone=phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return build_user_out(user, db)


@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, db: DBSession) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user.id, user.role)
    return {"access_token": token, "user": build_user_out(user, db)}


@router.post("/login/phone", response_model=TokenOut)
def login_phone(payload: PhoneLoginIn, db: DBSession) -> dict:
    phone = normalize_phone(payload.phone)
    verify_code(db, phone, "login", payload.code, consume=True)
    user = db.scalar(select(User).where(User.phone == phone))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="该手机号尚未注册")
    token = create_access_token(user.id, user.role)
    return {"access_token": token, "user": build_user_out(user, db)}
