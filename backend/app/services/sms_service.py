"""短信验证码业务：生成、发送、校验。"""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import SmsCode, User
from .aliyun_sms import check_pnvs_verify_code, send_pnvs_verify_code

PHONE_RE = re.compile(r"^1\d{10}$")
_PNVS_SENTINEL = "pnvs"


def normalize_phone(phone: str) -> str:
    raw = (phone or "").strip().replace(" ", "").replace("-", "")
    if raw.startswith("+86"):
        raw = raw[3:]
    if not PHONE_RE.fullmatch(raw):
        raise HTTPException(status_code=400, detail="请输入有效的中国大陆手机号")
    return raw


def _hash_code(phone: str, scene: str, code: str) -> str:
    material = f"{phone}:{scene}:{code}:{settings.jwt_secret}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def send_code(db: Session, phone: str, scene: str) -> dict:
    if scene not in ("register", "login"):
        raise HTTPException(status_code=400, detail="无效的验证码场景")
    phone = normalize_phone(phone)
    now = _utcnow()

    existing = db.scalar(select(User).where(User.phone == phone))
    if scene == "register" and existing:
        raise HTTPException(status_code=400, detail="该手机号已注册，请直接登录")
    if scene == "login" and not existing:
        raise HTTPException(status_code=400, detail="该手机号尚未注册")

    latest = db.scalar(
        select(SmsCode)
        .where(SmsCode.phone == phone, SmsCode.scene == scene, SmsCode.consumed.is_(False))
        .order_by(SmsCode.id.desc())
    )
    if latest and (now - latest.created_at).total_seconds() < settings.sms_send_interval_seconds:
        wait = settings.sms_send_interval_seconds - int((now - latest.created_at).total_seconds())
        raise HTTPException(status_code=429, detail=f"发送过于频繁，请 {max(wait, 1)} 秒后再试")

    dev_code = settings.sms_dev_code if settings.sms_dev_mode else None
    code_hash = _hash_code(phone, scene, dev_code) if dev_code else _PNVS_SENTINEL

    row = SmsCode(
        phone=phone,
        scene=scene,
        code_hash=code_hash,
        expires_at=now + timedelta(seconds=settings.sms_code_ttl_seconds),
        attempts=0,
        consumed=False,
        created_at=now,
    )
    db.add(row)
    db.commit()

    try:
        send_pnvs_verify_code(phone, scene)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result: dict = {
        "ok": True,
        "phone": phone,
        "expires_in": settings.sms_code_ttl_seconds,
        "cooldown": settings.sms_send_interval_seconds,
    }
    if settings.sms_dev_mode:
        result["dev_hint"] = f"开发模式验证码: {dev_code}"
    return result


def verify_code(db: Session, phone: str, scene: str, code: str, *, consume: bool = True) -> None:
    phone = normalize_phone(phone)
    code = (code or "").strip()
    if not re.fullmatch(r"\d{4,8}", code):
        raise HTTPException(status_code=400, detail="验证码格式不正确")

    now = _utcnow()
    row = db.scalar(
        select(SmsCode)
        .where(SmsCode.phone == phone, SmsCode.scene == scene, SmsCode.consumed.is_(False))
        .order_by(SmsCode.id.desc())
    )
    if not row:
        raise HTTPException(status_code=400, detail="请先获取验证码")
    if row.expires_at < now:
        raise HTTPException(status_code=400, detail="验证码已过期，请重新获取")
    if row.attempts >= settings.sms_max_verify_attempts:
        raise HTTPException(status_code=400, detail="验证码错误次数过多，请重新获取")

    if settings.sms_dev_mode:
        expected = row.code_hash
        actual = _hash_code(phone, scene, code)
        if not hmac.compare_digest(expected, actual):
            row.attempts += 1
            db.commit()
            raise HTTPException(status_code=400, detail="验证码错误")
    else:
        try:
            passed = check_pnvs_verify_code(phone, scene, code)
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not passed:
            row.attempts += 1
            db.commit()
            raise HTTPException(status_code=400, detail="验证码错误或已失效")

    if consume:
        row.consumed = True
        db.commit()
