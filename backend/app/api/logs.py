"""调用历史日志。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from ..deps import CurrentUser, DBSession, require_role, resolve_teacher_scope
from ..models import CallLog, User

router = APIRouter(prefix="/logs", tags=["logs"],
                   dependencies=[Depends(require_role("teacher"))])


@router.get("")
def list_logs(
    user: CurrentUser,
    db: DBSession,
    endpoint: str | None = Query(default=None),
    class_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> dict:
    _, allowed_students = resolve_teacher_scope(db, user, class_id)
    if not allowed_students:
        return {"total": 0, "page": page, "size": size, "items": []}
    base = select(CallLog).where(CallLog.user_id.in_(allowed_students))
    if endpoint:
        base = base.where(CallLog.endpoint == endpoint)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(CallLog.id.desc()).offset((page - 1) * size).limit(size)
    ).all()

    user_map: dict[int, User] = {}
    user_ids = {r.user_id for r in rows if r.user_id}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            user_map[u.id] = u

    return {
        "total": total, "page": page, "size": size,
        "items": [
            {
                "id": r.id, "user_id": r.user_id,
                "username": user_map[r.user_id].username if r.user_id and r.user_id in user_map else "",
                "display_name": user_map[r.user_id].display_name if r.user_id and r.user_id in user_map else "",
                "endpoint": r.endpoint,
                "req_summary": r.req_summary, "resp_summary": r.resp_summary,
                "model_name": r.model_name or "", "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
