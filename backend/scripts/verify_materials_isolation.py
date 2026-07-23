"""Verify materials/chapters isolation for preset vs new agents."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Agent, Material
from app.services.agent_access import apply_agent_content_scope
from app.services.chapter_sync import (
    is_original_c_lang_agent,
    requires_agent_scoped_chapters,
    resolve_original_c_lang_agent_id,
)


def count_materials(db, agent_id: int, course_id: int) -> int:
    from app.models import Chapter

    agent = db.get(Agent, agent_id)
    allowed = [1]  # demo class
    q = select(Material)
    if course_id:
        if not requires_agent_scoped_chapters(db, course_id, agent_id):
            ch_ids = db.scalars(select(Chapter.id).where(Chapter.course_id == course_id)).all()
            q = q.where(Material.chapter_id.in_(ch_ids))
    q = apply_agent_content_scope(Material, q, agent, allowed, db=db)
    return db.scalar(select(func.count()).select_from(q.subquery())) or 0


def main() -> None:
    db = SessionLocal()
    try:
        preset_id = resolve_original_c_lang_agent_id(db)
        print(f"preset agent id: {preset_id}")

        agents = db.scalars(select(Agent).where(Agent.course_id == 1).order_by(Agent.id)).all()
        for a in agents:
            n = count_materials(db, a.id, 1)
            print(
                f"  agent {a.id} slug={a.slug!r} original={is_original_c_lang_agent(db, a)} "
                f"scoped={requires_agent_scoped_chapters(db, 1, a.id)} materials={n}"
            )

        python_agents = db.scalars(
            select(Agent).where(Agent.slug == "python").order_by(Agent.id)
        ).all()
        for a in python_agents[:2]:
            n = count_materials(db, a.id, a.course_id or 0)
            print(f"  python agent {a.id} course={a.course_id} materials={n}")

        preset_n = count_materials(db, preset_id, 1)
        non_preset = [a for a in agents if a.id != preset_id]
        assert preset_n > 0, "original C agent should have preset materials"
        for a in non_preset:
            scoped_n = count_materials(db, a.id, 1)
            own_n = db.scalar(select(func.count()).where(Material.agent_id == a.id)) or 0
            assert scoped_n == own_n, f"agent {a.id} should only see own materials ({own_n}), got {scoped_n}"
        print("\n[pass] materials isolation checks OK")
    finally:
        db.close()


if __name__ == "__main__":
    main()
