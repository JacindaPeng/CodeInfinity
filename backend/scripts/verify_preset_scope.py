"""Verify preset chapter isolation for C language agents."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import engine
from app.main import app
from app.models import Agent, User
from app.services.chapter_sync import resolve_original_c_lang_agent_id, uses_course_level_preset_chapters

client = TestClient(app)
db = sessionmaker(bind=engine)()


def login(username: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": username, "password": f"{username}123"})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    teacher_h = login("teacher")
    preset_id = resolve_original_c_lang_agent_id(db)
    print(f"preset agent id: {preset_id}")

    teacher_id = db.scalar(select(User.id).where(User.username == "teacher"))
    print("--- teacher agents ---")
    for agent in db.scalars(select(Agent).where(Agent.owner_id == teacher_id).order_by(Agent.id)):
        preset = uses_course_level_preset_chapters(db, agent.course_id, agent.id)
        ch = client.get(
            "/api/chapters",
            params={"course_id": agent.course_id, "agent_id": agent.id},
            headers=teacher_h,
        )
        mat = client.get(
            "/api/materials",
            params={"course_id": agent.course_id, "agent_id": agent.id},
            headers=teacher_h,
        )
        info = client.get(f"/api/agents/{agent.id}", headers=teacher_h)
        ups = info.json().get("uses_preset_chapters")
        print(
            f"  id={agent.id} slug={agent.slug!r} course={agent.course_id} "
            f"preset={preset} uses_preset_chapters={ups} "
            f"chapters={len(ch.json())} materials={len(mat.json())}"
        )

    print("--- non-preset C agents (owner!=teacher) ---")
    for agent in db.scalars(
        select(Agent).where(Agent.course_id == 1, Agent.id != preset_id).order_by(Agent.id)
    ):
        ch = client.get(
            "/api/chapters",
            params={"course_id": 1, "agent_id": agent.id},
            headers=teacher_h,
        )
        mat = client.get(
            "/api/materials",
            params={"course_id": 1, "agent_id": agent.id},
            headers=teacher_h,
        )
        print(
            f"  id={agent.id} owner={agent.owner_id} "
            f"chapters={len(ch.json())} materials={len(mat.json())}"
        )

    db.close()


if __name__ == "__main__":
    main()
