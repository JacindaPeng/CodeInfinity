"""数据库初始化脚本：建表 + 默认 admin + 示例课程章节。

用法:
    cd backend
    python -m scripts.init_db
"""
import sys
from pathlib import Path

# 让脚本可以从 backend/ 目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import (
    Agent,
    Chapter,
    Course,
    ExamConfig,
    KnowledgePoint,
    LLMConfig,
    QuestionBank,
    User,
)
from app.security import hash_password


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    print("[ok] 表已创建")


def seed_admin(db) -> None:
    if db.scalar(select(User).where(User.username == "admin")):
        print("[skip] admin 已存在")
        return
    db.add(User(
        username="admin",
        password_hash=hash_password("admin123"),
        role="admin",
        display_name="系统管理员",
    ))
    db.add(User(
        username="teacher",
        password_hash=hash_password("teacher123"),
        role="teacher",
        display_name="默认教师",
    ))
    db.add(User(
        username="student",
        password_hash=hash_password("student123"),
        role="student",
        display_name="示例学生",
    ))
    db.commit()
    print("[ok] 默认账号: admin/admin123, teacher/teacher123, student/student123")


def seed_course(db) -> None:
    if db.scalar(select(Course).where(Course.id == 1)):
        print("[skip] 示例课程已存在")
        return
    course = Course(name="C语言程序设计", description="面向初学者的 C 语言入门课程")
    db.add(course)
    db.flush()

    chapters_data = [
        ("第一章 C语言概述", "C 语言发展史、特点、开发环境"),
        ("第二章 数据类型与运算符", "基本类型、运算符、表达式"),
        ("第三章 控制结构", "顺序、选择、循环"),
        ("第四章 数组与函数", "一维/二维数组、函数定义与调用"),
        ("第五章 指针与结构体", "指针、结构体、链表基础"),
        ("第六章 树与AVL树", "二叉树、AVL 树平衡调整"),
    ]
    for idx, (title, desc) in enumerate(chapters_data, start=1):
        ch = Chapter(course_id=course.id, title=title, order_idx=idx, description=desc)
        db.add(ch)
        db.flush()
        # 第六章配置示例知识点与考核配置
        if idx == 6:
            for kp_name in ["二叉树", "AVL树", "平衡调整"]:
                db.add(KnowledgePoint(chapter_id=ch.id, name=kp_name))
            db.add(ExamConfig(chapter_id=ch.id, config_json={
                "选择题": 2, "判断题": 2, "简答题": 2,
                "knowledge_points": ["二叉树", "AVL树", "平衡调整"],
            }))
    db.commit()
    print("[ok] 示例课程与章节已注入")


def seed_agent(db) -> None:
    if db.scalar(select(Agent)):
        print("[skip] 智能体已存在")
        return
    db.add(Agent(
        name="C语言课程智能体",
        intro="基于 RAG 的 C 语言程序设计课程问答、资源推荐与章节考核智能体。",
        endpoint="/api/agents/course/ask",
    ))
    db.commit()
    print("[ok] 智能体介绍已注入")


def seed_llm_config(db) -> None:
    if db.scalar(select(LLMConfig)):
        print("[skip] LLM 配置已存在")
        return
    from app.config import settings
    db.add(LLMConfig(
        provider=settings.llm_default_provider,
        api_key=settings.deepseek_api_key or "",
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        is_default=True,
    ))
    db.commit()
    print("[ok] 默认 LLM 配置已注入（请前往前端填入 API Key）")


def main() -> None:
    create_tables()
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_course(db)
        seed_agent(db)
        seed_llm_config(db)
    finally:
        db.close()
    print("\n[done] 初始化完成")


if __name__ == "__main__":
    main()
