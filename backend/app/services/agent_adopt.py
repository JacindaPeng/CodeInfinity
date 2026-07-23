"""共享智能体采纳：快照源教师资料库/题库/考核配置，与源智能体解耦。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Agent, Chapter, ExamConfig, KnowledgePoint, Material, QuestionBank
from .agent_access import _material_class_ids_for_agent, is_adopted_snapshot
from .chapter_sync import (
    requires_agent_scoped_chapters,
    uses_course_level_preset_chapters,
)
from .indexer import index_material


def _source_chapters(db: Session, source: Agent) -> list[Chapter]:
    """源智能体可见章节：预置 C 用课程级章节，否则优先源 agent 章节。"""
    if not source.course_id:
        return []
    if uses_course_level_preset_chapters(db, source.course_id, source.id):
        return list(
            db.scalars(
                select(Chapter)
                .where(Chapter.course_id == source.course_id, Chapter.agent_id.is_(None))
                .order_by(Chapter.order_idx, Chapter.id)
            ).all()
        )
    rows = list(
        db.scalars(
            select(Chapter)
            .where(Chapter.course_id == source.course_id, Chapter.agent_id == source.id)
            .order_by(Chapter.order_idx, Chapter.id)
        ).all()
    )
    if rows:
        return rows
    return list(
        db.scalars(
            select(Chapter)
            .where(Chapter.course_id == source.course_id, Chapter.agent_id.is_(None))
            .order_by(Chapter.order_idx, Chapter.id)
        ).all()
    )


def _clone_chapters_for_adopted(
    db: Session, source: Agent, adopted: Agent
) -> dict[int, int]:
    """把源课程章节克隆到采纳副本名下，返回 old_chapter_id -> new_chapter_id。"""
    mapping: dict[int, int] = {}
    if not adopted.course_id:
        return mapping

    existing = {
        (ch.title, ch.order_idx): ch.id
        for ch in db.scalars(
            select(Chapter).where(
                Chapter.course_id == adopted.course_id,
                Chapter.agent_id == adopted.id,
            )
        ).all()
    }

    for ch in _source_chapters(db, source):
        key = (ch.title, ch.order_idx)
        if key in existing:
            mapping[ch.id] = existing[key]
            continue
        nc = Chapter(
            course_id=adopted.course_id,
            agent_id=adopted.id,
            title=ch.title,
            order_idx=ch.order_idx,
            description=ch.description or "",
        )
        db.add(nc)
        db.flush()
        mapping[ch.id] = nc.id
        existing[key] = nc.id
    return mapping


def _remap_chapter(mapping: dict[int, int], chapter_id: int | None) -> int | None:
    if chapter_id is None:
        return None
    return mapping.get(chapter_id, chapter_id)


def _source_class_ids(db: Session, source: Agent) -> list[int]:
    ids = _material_class_ids_for_agent(db, source)
    if ids:
        return ids
    # 资料可能只在 class 上带 agent 以外字段；用课程班级兜底
    from ..models import TeachingClass

    if not source.course_id:
        return []
    return list(
        db.scalars(
            select(TeachingClass.id).where(TeachingClass.course_id == source.course_id)
        ).all()
    )


def clone_agent_content_snapshot(db: Session, source: Agent, adopted: Agent) -> list[int]:
    """将源智能体资料/题库/考核配置复制为采纳副本快照（class_id=NULL 模板）。

    若副本需要 agent 级章节隔离，会同步克隆章节并重写 chapter_id，
    否则绑定班级后资料管理看不到内容。
    """
    chapter_map = _clone_chapters_for_adopted(db, source, adopted)
    source_chapters = _source_chapters(db, source)
    chapter_ids = [c.id for c in source_chapters]
    source_class_ids = _source_class_ids(db, source)
    kp_map: dict[int, int] = {}

    # 若尚无章节但有课程章节，仍按课程全量章节克隆内容
    if not chapter_ids and source.course_id:
        chapter_ids = list(
            db.scalars(select(Chapter.id).where(Chapter.course_id == source.course_id)).all()
        )

    if chapter_ids:
        kp_q = select(KnowledgePoint).where(KnowledgePoint.chapter_id.in_(chapter_ids))
        if source_class_ids:
            kp_q = kp_q.where(
                (KnowledgePoint.class_id.in_(source_class_ids))
                | (KnowledgePoint.class_id.is_(None))
            )
        if source.id:
            kp_q = kp_q.where(
                (KnowledgePoint.agent_id == source.id) | (KnowledgePoint.agent_id.is_(None))
            )
        for kp in db.scalars(kp_q).all():
            new_ch = _remap_chapter(chapter_map, kp.chapter_id) or kp.chapter_id
            new_kp = KnowledgePoint(
                chapter_id=new_ch,
                class_id=None,
                agent_id=adopted.id,
                name=kp.name,
            )
            db.add(new_kp)
            db.flush()
            kp_map[kp.id] = new_kp.id

    materials = list(
        db.scalars(select(Material).where(Material.agent_id == source.id)).all()
    )
    if not materials and chapter_ids:
        mq = select(Material).where(Material.chapter_id.in_(chapter_ids))
        if source_class_ids:
            mq = mq.where(Material.class_id.in_(source_class_ids))
        materials = list(db.scalars(mq).all())

    # 去重：同一路径同一章节只留一条模板
    seen_mat: set[tuple[int | None, str]] = set()
    cloned_materials: list[Material] = []
    for m in materials:
        new_ch = _remap_chapter(chapter_map, m.chapter_id) or m.chapter_id
        key = (new_ch, m.file_path or "")
        if key in seen_mat:
            continue
        seen_mat.add(key)
        nm = Material(
            chapter_id=new_ch,
            class_id=None,
            agent_id=adopted.id,
            type=m.type,
            title=m.title,
            file_path=m.file_path,
            meta_json=dict(m.meta_json or {}),
        )
        db.add(nm)
        db.flush()
        cloned_materials.append(nm)

    if chapter_ids:
        ec_q = select(ExamConfig).where(ExamConfig.chapter_id.in_(chapter_ids))
        if source_class_ids:
            ec_q = ec_q.where(
                (ExamConfig.class_id.in_(source_class_ids)) | (ExamConfig.class_id.is_(None))
            )
        if source.id:
            ec_q = ec_q.where(
                (ExamConfig.agent_id == source.id) | (ExamConfig.agent_id.is_(None))
            )
        seen_ec: set[int] = set()
        for cfg in db.scalars(ec_q).all():
            new_ch = _remap_chapter(chapter_map, cfg.chapter_id) or cfg.chapter_id
            if new_ch in seen_ec:
                continue
            seen_ec.add(new_ch)
            db.add(
                ExamConfig(
                    chapter_id=new_ch,
                    class_id=None,
                    agent_id=adopted.id,
                    config_json=dict(cfg.config_json or {}),
                    max_attempts=cfg.max_attempts,
                )
            )

        qb_q = select(QuestionBank).where(QuestionBank.chapter_id.in_(chapter_ids))
        if source_class_ids:
            qb_q = qb_q.where(
                (QuestionBank.class_id.in_(source_class_ids))
                | (QuestionBank.class_id.is_(None))
            )
        if source.id:
            qb_q = qb_q.where(
                (QuestionBank.agent_id == source.id) | (QuestionBank.agent_id.is_(None))
            )
        seen_stem: set[tuple[int, str, str]] = set()
        for q in db.scalars(qb_q).all():
            new_ch = _remap_chapter(chapter_map, q.chapter_id) or q.chapter_id
            key = (new_ch, q.type, (q.stem or "")[:200])
            if key in seen_stem:
                continue
            seen_stem.add(key)
            db.add(
                QuestionBank(
                    chapter_id=new_ch,
                    class_id=None,
                    agent_id=adopted.id,
                    kp_id=kp_map.get(q.kp_id) if q.kp_id else None,
                    type=q.type,
                    stem=q.stem,
                    options_json=list(q.options_json or []),
                    answer=q.answer,
                    analysis=q.analysis or "",
                )
            )

    adopted.source_snapshot_at = datetime.utcnow()
    db.flush()
    return [m.id for m in cloned_materials]


def dedupe_agent_content(db: Session, agent: Agent) -> int:
    """清理采纳副本中重复的模板/班级资料（同章同路径只留最早一条）。"""
    if not agent or not agent.id:
        return 0
    removed = 0
    rows = list(
        db.scalars(
            select(Material)
            .where(Material.agent_id == agent.id)
            .order_by(Material.id)
        ).all()
    )
    seen: set[tuple[int | None, int | None, str]] = set()
    for m in rows:
        key = (m.chapter_id, m.class_id, m.file_path or "")
        if key in seen:
            db.delete(m)
            removed += 1
        else:
            seen.add(key)
    if removed:
        db.flush()
    return removed


def repair_adopted_chapter_links(db: Session, agent: Agent) -> bool:
    """修复历史采纳副本：内容仍挂在课程章节上、未指向本智能体章节。"""
    if not is_adopted_snapshot(agent) or not agent.source_agent_id or not agent.course_id:
        return False
    if not requires_agent_scoped_chapters(db, agent.course_id, agent.id):
        return False

    source = db.get(Agent, agent.source_agent_id)
    if not source:
        return False

    chapter_map = _clone_chapters_for_adopted(db, source, agent)
    if not chapter_map:
        return False

    # 只要本智能体内容仍引用「非本智能体章节」，就批量 remap
    foreign = db.scalar(
        select(Material.id)
        .outerjoin(Chapter, Chapter.id == Material.chapter_id)
        .where(
            Material.agent_id == agent.id,
            (Chapter.id.is_(None))
            | (Chapter.agent_id.is_(None))
            | (Chapter.agent_id != agent.id),
        )
        .limit(1)
    )
    if not foreign:
        # 再查题库/配置是否还有外链
        for Model in (QuestionBank, ExamConfig, KnowledgePoint):
            foreign = db.scalar(
                select(Model.id)
                .outerjoin(Chapter, Chapter.id == Model.chapter_id)
                .where(
                    Model.agent_id == agent.id,
                    (Chapter.id.is_(None))
                    | (Chapter.agent_id.is_(None))
                    | (Chapter.agent_id != agent.id),
                )
                .limit(1)
            )
            if foreign:
                break
    if not foreign:
        return False

    changed = False
    for old_id, new_id in chapter_map.items():
        if old_id == new_id:
            continue
        for Model in (Material, QuestionBank, ExamConfig, KnowledgePoint):
            res = db.execute(
                update(Model)
                .where(Model.agent_id == agent.id, Model.chapter_id == old_id)
                .values(chapter_id=new_id)
            )
            if res.rowcount:
                changed = True
    if changed:
        db.flush()
    return changed


def index_adopted_materials(material_ids: list[int]) -> None:
    """后台索引采纳快照资料（避免采纳接口超时）。"""
    if not material_ids:
        return
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        for mid in material_ids:
            m = db.get(Material, mid)
            if not m:
                continue
            try:
                index_material(db, m)
            except Exception:
                pass
    finally:
        db.close()


def schedule_index_adopted_materials(material_ids: list[int]) -> None:
    """守护线程索引，不阻塞 uvicorn 退出/热重载。"""
    if not material_ids:
        return
    import threading

    threading.Thread(
        target=index_adopted_materials,
        args=(material_ids,),
        daemon=True,
        name="index-adopted-materials",
    ).start()


def _kp_id_for_class(
    db: Session,
    agent_id: int,
    chapter_id: int,
    class_id: int,
    template_kp_id: int | None,
) -> int | None:
    if not template_kp_id:
        return None
    template = db.get(KnowledgePoint, template_kp_id)
    if not template or template.agent_id != agent_id:
        return template_kp_id
    existing = db.scalar(
        select(KnowledgePoint).where(
            KnowledgePoint.agent_id == agent_id,
            KnowledgePoint.chapter_id == chapter_id,
            KnowledgePoint.class_id == class_id,
            KnowledgePoint.name == template.name,
        )
    )
    if existing:
        return existing.id
    new_kp = KnowledgePoint(
        chapter_id=chapter_id,
        class_id=class_id,
        agent_id=agent_id,
        name=template.name,
    )
    db.add(new_kp)
    db.flush()
    return new_kp.id


def propagate_snapshot_to_classes(db: Session, agent: Agent, class_ids: list[int]) -> list[int]:
    """将采纳快照模板复制到已绑定班级（仅新增绑定时调用）。

    返回新建资料 id；索引请在 commit 后后台执行，避免绑定接口超时。
    """
    if not agent.source_agent_id or not agent.source_snapshot_at:
        return []

    repair_adopted_chapter_links(db, agent)
    new_material_ids: list[int] = []

    for cid in class_ids:
        # 资料：同一章同一路径只传播一次
        seen_mat: set[tuple[int | None, str]] = set()
        for t in db.scalars(
            select(Material).where(
                Material.agent_id == agent.id,
                Material.class_id.is_(None),
            )
        ).all():
            key = (t.chapter_id, t.file_path or "")
            if key in seen_mat:
                continue
            seen_mat.add(key)
            exists = db.scalar(
                select(Material.id).where(
                    Material.agent_id == agent.id,
                    Material.chapter_id == t.chapter_id,
                    Material.class_id == cid,
                    Material.file_path == t.file_path,
                )
            )
            if exists:
                continue
            nm = Material(
                chapter_id=t.chapter_id,
                class_id=cid,
                agent_id=agent.id,
                type=t.type,
                title=t.title,
                file_path=t.file_path,
                meta_json=dict(t.meta_json or {}),
            )
            db.add(nm)
            db.flush()
            new_material_ids.append(nm.id)

        seen_kp: set[tuple[int | None, str]] = set()
        for t in db.scalars(
            select(KnowledgePoint).where(
                KnowledgePoint.agent_id == agent.id,
                KnowledgePoint.class_id.is_(None),
            )
        ).all():
            key = (t.chapter_id, t.name)
            if key in seen_kp:
                continue
            seen_kp.add(key)
            exists = db.scalar(
                select(KnowledgePoint.id).where(
                    KnowledgePoint.agent_id == agent.id,
                    KnowledgePoint.chapter_id == t.chapter_id,
                    KnowledgePoint.class_id == cid,
                    KnowledgePoint.name == t.name,
                )
            )
            if not exists:
                db.add(KnowledgePoint(
                    chapter_id=t.chapter_id,
                    class_id=cid,
                    agent_id=agent.id,
                    name=t.name,
                ))
        db.flush()

        # 考核配置：每章每班最多一条（与唯一索引一致）
        seen_ec: set[int | None] = set()
        for t in db.scalars(
            select(ExamConfig).where(
                ExamConfig.agent_id == agent.id,
                ExamConfig.class_id.is_(None),
            )
        ).all():
            if t.chapter_id in seen_ec:
                continue
            seen_ec.add(t.chapter_id)
            exists = db.scalar(
                select(ExamConfig.id).where(
                    ExamConfig.agent_id == agent.id,
                    ExamConfig.chapter_id == t.chapter_id,
                    ExamConfig.class_id == cid,
                )
            )
            if not exists:
                db.add(ExamConfig(
                    chapter_id=t.chapter_id,
                    class_id=cid,
                    agent_id=agent.id,
                    config_json=dict(t.config_json or {}),
                    max_attempts=t.max_attempts,
                ))
        db.flush()

        seen_qb: set[tuple[int | None, str, str]] = set()
        for t in db.scalars(
            select(QuestionBank).where(
                QuestionBank.agent_id == agent.id,
                QuestionBank.class_id.is_(None),
            )
        ).all():
            key = (t.chapter_id, t.type, (t.stem or "")[:200])
            if key in seen_qb:
                continue
            seen_qb.add(key)
            exists = db.scalar(
                select(QuestionBank.id).where(
                    QuestionBank.agent_id == agent.id,
                    QuestionBank.chapter_id == t.chapter_id,
                    QuestionBank.class_id == cid,
                    QuestionBank.stem == t.stem,
                    QuestionBank.type == t.type,
                )
            )
            if exists:
                continue
            kp_id = _kp_id_for_class(db, agent.id, t.chapter_id, cid, t.kp_id)
            db.add(QuestionBank(
                chapter_id=t.chapter_id,
                class_id=cid,
                agent_id=agent.id,
                kp_id=kp_id,
                type=t.type,
                stem=t.stem,
                options_json=list(t.options_json or []),
                answer=t.answer,
                analysis=t.analysis or "",
            ))
        db.flush()
    return new_material_ids
