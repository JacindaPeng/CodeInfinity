"""依赖注入：当前用户、DB 会话、调用日志写入。"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import CallLog, ClassTeacher, ExamConfig, Material, QuestionBank, TeachingClass, User
from .services.enrollment import (
    assert_student_enrolled,
    get_class_student_user_ids,
    get_student_class_for_course,
    get_student_class_ids,
    get_student_enrollments,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc).timestamp() + settings.jwt_expire_minutes * 60
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return user_from_access_token(token, db)


def user_from_access_token(token: str | None, db: Session) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未认证或凭证已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise cred_exc
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", "0"))
    except JWTError:
        raise cred_exc
    user = db.get(User, user_id)
    if not user:
        raise cred_exc
    return user


def require_role(*roles: str):
    """角色守卫：require_role('teacher','admin')。"""
    def _dep(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return _dep


def get_managed_class_ids(db: Session, user: User) -> list[int] | None:
    """admin 返回 None（不限制）；teacher 返回所管班级 id 列表（含任教与自建）。"""
    if user.role == "admin":
        return None
    if user.role != "teacher":
        return []
    linked = set(db.scalars(
        select(ClassTeacher.class_id).where(ClassTeacher.user_id == user.id)
    ).all())
    created = set(db.scalars(
        select(TeachingClass.id).where(TeachingClass.created_by == user.id)
    ).all())
    return sorted(linked | created)


def get_class_student_ids(db: Session, class_ids: list[int]) -> list[int]:
    return get_class_student_user_ids(db, class_ids)


def resolve_teacher_scope(
    db: Session,
    user: User,
    class_id: int | None = None,
) -> tuple[list[int] | None, list[int]]:
    """返回 (managed_class_ids, allowed_student_ids)。admin 不限制学生。"""
    managed = get_managed_class_ids(db, user)
    if managed is None:
        if class_id:
            return None, get_class_student_ids(db, [class_id])
        return None, []
    if not managed:
        return managed, []
    if class_id:
        if class_id not in managed:
            raise HTTPException(status_code=403, detail="无权访问该班级")
        return managed, get_class_student_ids(db, [class_id])
    return managed, get_class_student_ids(db, managed)


def assert_teacher_manages_class(db: Session, user: User, class_id: int) -> None:
    if user.role == "admin":
        return
    managed = get_managed_class_ids(db, user)
    if not managed or class_id not in managed:
        raise HTTPException(status_code=403, detail="无权管理该班级")


def assert_teacher_can_view_student(db: Session, user: User, student_id: int) -> None:
    if user.role == "admin":
        return
    student = db.get(User, student_id)
    if not student or student.role != "student":
        raise HTTPException(status_code=403, detail="无权查看该学生")
    managed = get_managed_class_ids(db, user) or []
    enrolled = get_student_class_ids(db, student)
    if enrolled and any(cid in managed for cid in enrolled):
        return
    if student.class_id and student.class_id in managed:
        return
    raise HTTPException(status_code=403, detail="无权查看该学生")


def resolve_resource_class_ids(
    db: Session,
    user: User,
    class_id: int | None = None,
) -> list[int] | None:
    """资料/题库可见班级范围。admin 返回 None（不限制）；其余返回班级 id 列表。"""
    if user.role == "admin":
        if class_id:
            return [class_id]
        return None
    if user.role == "teacher":
        managed = get_managed_class_ids(db, user) or []
        if not managed:
            return []
        if class_id:
            if class_id not in managed:
                raise HTTPException(status_code=403, detail="无权访问该班级")
            return [class_id]
        return managed
    if user.role == "student":
        class_ids = get_student_class_ids(db, user)
        if not class_ids and user.class_id:
            class_ids = [user.class_id]
        if not class_ids:
            return []
        if class_id:
            if class_id not in class_ids:
                raise HTTPException(status_code=403, detail="无权访问该班级")
            return [class_id]
        return class_ids
    return []


def assert_teacher_upload_class(db: Session, user: User, class_id: int) -> None:
    """教师上传资料/题库时必须指定且有权管理的班级。"""
    if user.role == "admin":
        return
    assert_teacher_manages_class(db, user, class_id)


def assert_can_access_class_resource(
    db: Session,
    user: User,
    resource_class_id: int | None,
) -> None:
    """校验用户能否访问带 class_id 的资料或题库条目。"""
    if user.role == "admin":
        return
    allowed = resolve_resource_class_ids(db, user)
    if allowed is None:
        return
    if not resource_class_id or resource_class_id not in allowed:
        raise HTTPException(status_code=403, detail="无权访问该资源")


def assert_can_access_material(db: Session, user: User, material: Material) -> None:
    assert_can_access_class_resource(db, user, material.class_id)


def assert_can_access_question(db: Session, user: User, question: QuestionBank) -> None:
    assert_can_access_class_resource(db, user, question.class_id)


def resolve_config_class_id(
    db: Session,
    user: User,
    class_id: int | None = None,
    course_id: int | None = None,
    agent_id: int | None = None,
) -> int:
    """考核配置/知识点/开考使用的单一班级 id。学生取所在班；教师/admin 需指定 class_id。"""
    if user.role == "student":
        if class_id:
            assert_student_enrolled(db, user, class_id)
            return class_id
        if course_id:
            cid = get_student_class_for_course(db, user, course_id)
            if cid:
                return cid
        enrollments = get_student_enrollments(db, user)
        if len(enrollments) == 1:
            return enrollments[0].class_id
        raise HTTPException(
            status_code=400,
            detail="尚未加入该课程班级或需指定班级，无法使用考核功能",
        )
    if user.role == "teacher":
        managed = get_managed_class_ids(db, user) or []
        if not class_id:
            raise HTTPException(status_code=400, detail="请指定班级")
        if class_id in managed:
            if agent_id:
                from .services.agent_access import assert_teacher_class_bound_to_agent
                assert_teacher_class_bound_to_agent(db, user, agent_id, class_id)
            return class_id
        # 体验他人共享智能体：可读源侧考核配置（只读浏览）
        if agent_id:
            from .services.agent_access import (
                assert_agent_access,
                get_shared_content_class_ids,
                is_shared_agent_preview,
            )
            agent = assert_agent_access(db, user, agent_id)
            if is_shared_agent_preview(agent, user):
                shared_ids = get_shared_content_class_ids(db, agent)
                if class_id in shared_ids:
                    return class_id
        if not managed:
            raise HTTPException(status_code=403, detail="无权管理任何班级")
        raise HTTPException(status_code=403, detail="无权访问该班级")
    if user.role == "admin":
        if not class_id:
            raise HTTPException(status_code=400, detail="请指定班级")
        return class_id
    raise HTTPException(status_code=403, detail="权限不足")


def get_exam_config(
    db: Session,
    chapter_id: int,
    class_id: int | None,
) -> ExamConfig | None:
    if not class_id:
        return None
    return db.scalar(
        select(ExamConfig).where(
            ExamConfig.chapter_id == chapter_id,
            ExamConfig.class_id == class_id,
        )
    )


def log_call(
    db: Session,
    endpoint: str,
    user_id: int | None = None,
    req_summary: str = "",
    resp_summary: str = "",
    tokens: int = 0,
    model_name: str = "",
    answer_full: str = "",
    attachments_json: str = "",
    latency_ms: int = 0,
) -> None:
    db.add(CallLog(
        user_id=user_id, endpoint=endpoint,
        req_summary=req_summary[:2000], resp_summary=resp_summary[:500],
        tokens=tokens, model_name=model_name[:128],
        answer_full=answer_full[:50000],
        attachments_json=attachments_json[:200000],
        latency_ms=latency_ms,
    ))
    db.commit()


CurrentUser = Annotated[User, Depends(get_current_user)]
DBSession = Annotated[Session, Depends(get_db)]
