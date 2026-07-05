"""调用历史日志。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ..deps import CurrentUser, DBSession, require_role
from ..models import CallLog

router = APIRouter(prefix="/logs", tags=["logs"],
                   dependencies=[Depends(require_role("teacher", "admin"))])


@router.get("")
def list_logs(
    db: DBSession,
    _u: CurrentUser,
    endpoint: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    base = select(CallLog)
    if endpoint:
        base = base.where(CallLog.endpoint == endpoint)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(CallLog.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return {
        "total": total, "page": page, "size": size,
        "items": [
            {
                "id": r.id, "user_id": r.user_id, "endpoint": r.endpoint,
                "req_summary": r.req_summary, "resp_summary": r.resp_summary,
                "tokens": r.tokens, "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
