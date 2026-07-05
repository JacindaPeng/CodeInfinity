"""LLM 配置 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from ..deps import CurrentUser, DBSession, require_role
from ..models import LLMConfig
from ..services.llm_provider import list_available_providers

router = APIRouter(prefix="/llm-configs", tags=["llm"])


class LLMConfigIn(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    is_default: bool = False


class LLMConfigOut(BaseModel):
    id: int
    provider: str
    api_key: str
    base_url: str
    model: str
    is_default: bool
    model_config = {"from_attributes": True}


@router.get("/providers")
def providers(_u: CurrentUser) -> list[dict]:
    return list_available_providers()


@router.get("", response_model=list[LLMConfigOut])
def list_configs(_u: CurrentUser, db: DBSession) -> list[LLMConfig]:
    return db.scalars(select(LLMConfig).order_by(LLMConfig.id)).all()


@router.post("", response_model=LLMConfigOut, status_code=201,
             dependencies=[Depends(require_role("teacher", "admin"))])
def create_cfg(payload: LLMConfigIn, db: DBSession) -> LLMConfig:
    if payload.is_default:
        db.execute(update(LLMConfig).values(is_default=False))
    cfg = LLMConfig(**payload.model_dump())
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.put("/{cfg_id}", response_model=LLMConfigOut,
            dependencies=[Depends(require_role("teacher", "admin"))])
def update_cfg(cfg_id: int, payload: LLMConfigIn, db: DBSession) -> LLMConfig:
    cfg = db.get(LLMConfig, cfg_id)
    if not cfg:
        raise HTTPException(404, "配置不存在")
    if payload.is_default:
        db.execute(update(LLMConfig).where(LLMConfig.id != cfg_id).values(is_default=False))
    for k, v in payload.model_dump().items():
        setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.delete("/{cfg_id}", dependencies=[Depends(require_role("teacher", "admin"))])
def delete_cfg(cfg_id: int, db: DBSession) -> dict:
    cfg = db.get(LLMConfig, cfg_id)
    if cfg:
        db.delete(cfg)
        db.commit()
    return {"ok": True}
