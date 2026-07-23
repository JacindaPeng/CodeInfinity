"""数据库初始化脚本：建表 + 默认 admin + 示例课程章节。

用法:
    cd backend
    python -m scripts.init_db            # 幂等初始化
    python -m scripts.init_db --reset    # 清库重建（删除所有数据后重新注入）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import secrets

from sqlalchemy import func, inspect, select, text

from app.database import Base, SessionLocal, engine
from app.models import (
    Agent,
    AgentClass,
    Chapter,
    ClassEnrollment,
    ClassTeacher,
    Course,
    ExamConfig,
    KnowledgePoint,
    LLMConfig,
    Material,
    QuestionBank,
    TeachingClass,
    User,
)
from app.security import hash_password


# 课本《C程序设计快速进阶大学教程》蒋光远，三篇 17 章
# (order_idx, title, description, [knowledge_points])
TEXTBOOK_CHAPTERS = [
    (0, "第0章 概述",
     "计算机由来及组成、C语言发展史、C程序基本结构、程序开发步骤、集成开发环境",
     ["计算机由来与组成", "C语言发展史", "C程序基本结构", "程序开发步骤", "集成开发环境"]),
    (1, "第1章 数据的基本操作",
     "数据的存储与输出、数据的输入与运算、数据的比较与判断",
     ["数据的存储与输出", "数据的输入与运算", "数据的比较与判断"]),
    (2, "第2章 结构化程序设计初探",
     "重复与循环语句、基本结构的组合、模块化编程",
     ["重复与循环语句", "基本结构的组合", "模块化编程"]),
    (3, "第3章 数据结构",
     "数组、结构体、文件",
     ["数组", "结构体", "文件"]),
    (4, "第4章 算法描述和编码规范",
     "算法描述方法、编码规范",
     ["算法描述", "编码规范"]),
    (5, "第5章 数据类型与输入输出",
     "C语言要素、数据类型、输入输出操作、编程错误",
     ["C语言要素", "数据类型", "输入输出操作", "编程错误"]),
    (6, "第6章 运算符与表达式",
     "运算符、表达式、类型转换、自增自减运算",
     ["运算符", "表达式", "类型转换", "自增自减运算"]),
    (7, "第7章 选择结构",
     "单分支if、双分支if-else、多分支、switch语句",
     ["单分支if语句", "双分支if-else语句", "多分支语句", "switch语句"]),
    (8, "第8章 循环结构",
     "while/do-while/for、循环条件、循环嵌套、break/continue",
     ["while语句", "do-while语句", "for语句", "循环嵌套", "break与continue"]),
    (9, "第9章 数组",
     "一维数组、二维数组、数组应用",
     ["一维数组", "二维数组", "数组应用"]),
    (10, "第10章 函数",
     "函数定义与分类、调用与声明、参数与返回值、递归、变量作用域",
     ["函数定义与分类", "函数调用与声明", "函数参数与返回值", "函数递归调用", "变量作用域与生存期"]),
    (11, "第11章 指针",
     "指针变量、数组与指针、函数与指针、指针数组",
     ["指针变量", "数组与指针", "函数与指针", "指针数组"]),
    (12, "第12章 自定义数据类型",
     "结构体、联合体、枚举、typedef",
     ["结构体", "联合体", "枚举", "typedef"]),
    (13, "第13章 文件",
     "文件概述、字符读写、格式化读写、随机读写",
     ["文件概述", "字符读写函数", "格式化读写函数", "文件的随机读写"]),
    (14, "第14章 函数进阶",
     "递归深入、模块化设计",
     ["递归深入", "模块化设计"]),
    (15, "第15章 数组进阶",
     "数据模型、查找算法、排序算法",
     ["数据模型", "查找算法", "排序算法"]),
    (16, "第16章 数据管理",
     "简单链表、数据文件",
     ["简单链表", "数据文件"]),
]


def migrate_users_class_id() -> None:
    """兼容已有数据库：为 users 表补充 class_id 列。"""
    insp = inspect(engine)
    if not insp.has_table("users"):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "class_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN class_id INTEGER REFERENCES teaching_classes(id)"))
        print("[ok] users.class_id 列已添加")


def migrate_users_phone() -> None:
    """兼容已有数据库：为 users 表补充 phone 列，并确保 sms_codes 表存在。"""
    from app.models import SmsCode  # noqa: F401

    insp = inspect(engine)
    if insp.has_table("users"):
        cols = {c["name"] for c in insp.get_columns("users")}
        if "phone" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(20)"))
            print("[ok] users.phone 列已添加")
        # SQLite 无法简单 ADD UNIQUE；create_all + 查询层唯一校验即可。新建索引（幂等）
        with engine.begin() as conn:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_phone ON users(phone)"))
    Base.metadata.create_all(bind=engine, tables=[SmsCode.__table__])
    print("[ok] sms_codes 表已就绪")


def migrate_call_logs_model_name() -> None:
    """兼容已有数据库：为 call_logs 表补充 model_name 列。"""
    insp = inspect(engine)
    if not insp.has_table("call_logs"):
        return
    cols = {c["name"] for c in insp.get_columns("call_logs")}
    if "model_name" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE call_logs ADD COLUMN model_name VARCHAR(128) DEFAULT ''"))
        print("[ok] call_logs.model_name 列已添加")


def migrate_call_logs_answer_full() -> None:
    """兼容已有数据库：为 call_logs 表补充 answer_full 列。"""
    insp = inspect(engine)
    if not insp.has_table("call_logs"):
        return
    cols = {c["name"] for c in insp.get_columns("call_logs")}
    if "answer_full" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE call_logs ADD COLUMN answer_full TEXT DEFAULT ''"))
        print("[ok] call_logs.answer_full 列已添加")


def migrate_call_logs_attachments_json() -> None:
    """兼容已有数据库：为 call_logs 表补充 attachments_json 列。"""
    insp = inspect(engine)
    if not insp.has_table("call_logs"):
        return
    cols = {c["name"] for c in insp.get_columns("call_logs")}
    if "attachments_json" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE call_logs ADD COLUMN attachments_json TEXT DEFAULT ''"))
        print("[ok] call_logs.attachments_json 列已添加")


def migrate_materials_class_id() -> None:
    """兼容已有数据库：为 materials 表补充 class_id 列。"""
    insp = inspect(engine)
    if not insp.has_table("materials"):
        return
    cols = {c["name"] for c in insp.get_columns("materials")}
    if "class_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE materials ADD COLUMN class_id INTEGER REFERENCES teaching_classes(id)"
            ))
        print("[ok] materials.class_id 列已添加")


def migrate_question_bank_class_id() -> None:
    """兼容已有数据库：为 question_bank 表补充 class_id 列。"""
    insp = inspect(engine)
    if not insp.has_table("question_bank"):
        return
    cols = {c["name"] for c in insp.get_columns("question_bank")}
    if "class_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE question_bank ADD COLUMN class_id INTEGER REFERENCES teaching_classes(id)"
            ))
        print("[ok] question_bank.class_id 列已添加")


def _recover_exam_configs_new_table() -> None:
    """恢复中断的 exam_configs 表迁移（遗留 exam_configs_new）。"""
    insp = inspect(engine)
    if not insp.has_table("exam_configs_new"):
        return
    with engine.begin() as conn:
        if insp.has_table("exam_configs"):
            cnt_new = conn.execute(text("SELECT COUNT(*) FROM exam_configs_new")).scalar() or 0
            cnt_old = conn.execute(text("SELECT COUNT(*) FROM exam_configs")).scalar() or 0
            if cnt_new >= cnt_old and cnt_new > 0:
                conn.execute(text("DROP TABLE exam_configs"))
                conn.execute(text("ALTER TABLE exam_configs_new RENAME TO exam_configs"))
                print("[ok] exam_configs 迁移已从 exam_configs_new 恢复")
            else:
                conn.execute(text("DROP TABLE exam_configs_new"))
                print("[ok] 已清理未完成的 exam_configs_new")
        else:
            conn.execute(text("ALTER TABLE exam_configs_new RENAME TO exam_configs"))
            print("[ok] exam_configs 表已从 exam_configs_new 重命名恢复")


def migrate_exam_configs_class_id() -> None:
    """兼容已有数据库：exam_configs 增加 class_id，并改为 (chapter_id, class_id) 唯一。"""
    _recover_exam_configs_new_table()
    insp = inspect(engine)
    if not insp.has_table("exam_configs"):
        return
    cols = {c["name"] for c in insp.get_columns("exam_configs")}
    if "class_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE exam_configs ADD COLUMN class_id INTEGER REFERENCES teaching_classes(id)"
            ))
        print("[ok] exam_configs.class_id 列已添加")

    with engine.connect() as conn:
        ddl = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='exam_configs'"
        )).scalar() or ""
    ddl_norm = ddl.replace(" ", "")
    if "UNIQUE(chapter_id,class_id)" in ddl_norm or "agent_id" in ddl_norm:
        return

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS exam_configs_new"))
        conn.execute(text("""
            CREATE TABLE exam_configs_new (
                id INTEGER PRIMARY KEY,
                chapter_id INTEGER NOT NULL REFERENCES chapters(id),
                class_id INTEGER REFERENCES teaching_classes(id),
                config_json JSON,
                max_attempts INTEGER DEFAULT 0,
                UNIQUE(chapter_id, class_id)
            )
        """))
        conn.execute(text("""
            INSERT INTO exam_configs_new (id, chapter_id, class_id, config_json, max_attempts)
            SELECT id, chapter_id, class_id, config_json, max_attempts FROM exam_configs
        """))
        conn.execute(text("DROP TABLE exam_configs"))
        conn.execute(text("ALTER TABLE exam_configs_new RENAME TO exam_configs"))
    print("[ok] exam_configs 已迁移为 (chapter_id, class_id) 唯一")


def migrate_knowledge_points_class_id() -> None:
    """兼容已有数据库：为 knowledge_points 表补充 class_id 列。"""
    insp = inspect(engine)
    if not insp.has_table("knowledge_points"):
        return
    cols = {c["name"] for c in insp.get_columns("knowledge_points")}
    if "class_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE knowledge_points ADD COLUMN class_id INTEGER REFERENCES teaching_classes(id)"
            ))
        print("[ok] knowledge_points.class_id 列已添加")


def migrate_agents_extend() -> None:
    """为 agents 表补充 course_id / slug / status 列，并回填默认 C 语言智能体。"""
    insp = inspect(engine)
    if not insp.has_table("agents"):
        return
    cols = {c["name"] for c in insp.get_columns("agents")}
    with engine.begin() as conn:
        if "course_id" not in cols:
            conn.execute(text(
                "ALTER TABLE agents ADD COLUMN course_id INTEGER REFERENCES courses(id)"
            ))
            print("[ok] agents.course_id 列已添加")
        if "slug" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN slug VARCHAR(32) DEFAULT ''"))
            print("[ok] agents.slug 列已添加")
        if "status" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN status VARCHAR(16) DEFAULT 'active'"))
            print("[ok] agents.status 列已添加")
    with SessionLocal() as db:
        _ensure_extra_courses(db)
        c_agent = db.scalar(select(Agent).where(Agent.slug == "c-lang"))
        if not c_agent:
            legacy = db.scalar(select(Agent).where(Agent.name.contains("C语言")))
            if legacy:
                legacy.slug = legacy.slug or "c-lang"
                legacy.status = legacy.status or "active"
                if not legacy.course_id:
                    course = db.scalar(select(Course).where(Course.id == 1))
                    if course:
                        legacy.course_id = course.id
        for slug, name, intro, status, course_name in (
            ("java", "Java课程智能体",
             "面向 Java 程序设计课程的智能问答、资源推荐与章节考核（筹备中）。", "planned",
             "Java程序设计"),
            ("python", "Python课程智能体",
             "面向 Python 程序设计课程的智能问答、资源推荐与章节考核（筹备中）。", "planned",
             "Python程序设计"),
        ):
            course = db.scalar(select(Course).where(Course.name == course_name))
            if not db.scalar(select(Agent).where(Agent.slug == slug)):
                db.add(Agent(
                    name=name, intro=intro, endpoint="/api/agents/course/ask",
                    slug=slug, status=status, course_id=course.id if course else None,
                ))
            else:
                agent = db.scalar(select(Agent).where(Agent.slug == slug))
                if agent and course and not agent.course_id:
                    agent.course_id = course.id
        db.commit()


def migrate_class_course_enrollment() -> None:
    """班级绑定课程、学生多班选课（每课程限一班）。"""
    insp = inspect(engine)
    if not insp.has_table("teaching_classes"):
        return
    tcols = {c["name"] for c in insp.get_columns("teaching_classes")}
    with engine.begin() as conn:
        if "course_id" not in tcols:
            conn.execute(text(
                "ALTER TABLE teaching_classes ADD COLUMN course_id INTEGER REFERENCES courses(id)"
            ))
            print("[ok] teaching_classes.course_id 列已添加")
        if not insp.has_table("class_enrollments"):
            conn.execute(text("""
                CREATE TABLE class_enrollments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    class_id INTEGER NOT NULL REFERENCES teaching_classes(id),
                    course_id INTEGER NOT NULL REFERENCES courses(id),
                    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, course_id)
                )
            """))
            print("[ok] class_enrollments 表已创建")

    with SessionLocal() as db:
        c_course = db.scalar(
            select(Course).where(Course.name.contains("C程序")).order_by(Course.id).limit(1)
        )
        if not c_course:
            c_course = db.scalar(select(Course).order_by(Course.id).limit(1))

        for cls in db.scalars(select(TeachingClass)).all():
            if cls.course_id is None and c_course:
                cls.course_id = c_course.id

        for student in db.scalars(
            select(User).where(User.role == "student", User.class_id.isnot(None))
        ).all():
            cls = db.get(TeachingClass, student.class_id)
            if not cls or not cls.course_id:
                continue
            exists = db.scalar(
                select(ClassEnrollment).where(
                    ClassEnrollment.user_id == student.id,
                    ClassEnrollment.course_id == cls.course_id,
                )
            )
            if not exists:
                db.add(ClassEnrollment(
                    user_id=student.id,
                    class_id=cls.id,
                    course_id=cls.course_id,
                ))
        db.commit()
    print("[ok] 班级课程与学生选课已迁移")


def migrate_agent_ownership() -> None:
    """智能体归属、班级绑定、资料 agent_id 迁移。"""
    insp = inspect(engine)
    if not insp.has_table("agents"):
        return
    cols = {c["name"] for c in insp.get_columns("agents")}
    with engine.begin() as conn:
        if "owner_id" not in cols:
            conn.execute(text(
                "ALTER TABLE agents ADD COLUMN owner_id INTEGER REFERENCES users(id)"
            ))
            print("[ok] agents.owner_id 列已添加")
        if "source_agent_id" not in cols:
            conn.execute(text(
                "ALTER TABLE agents ADD COLUMN source_agent_id INTEGER REFERENCES agents(id)"
            ))
            print("[ok] agents.source_agent_id 列已添加")
        if "is_shared" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN is_shared BOOLEAN DEFAULT 0"))
            print("[ok] agents.is_shared 列已添加")
        if "shared_at" not in cols:
            conn.execute(text("ALTER TABLE agents ADD COLUMN shared_at DATETIME"))
            print("[ok] agents.shared_at 列已添加")
        if not insp.has_table("agent_classes"):
            conn.execute(text("""
                CREATE TABLE agent_classes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    class_id INTEGER NOT NULL REFERENCES teaching_classes(id),
                    assigned_by INTEGER REFERENCES users(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_id, class_id)
                )
            """))
            print("[ok] agent_classes 表已创建")
        if insp.has_table("materials"):
            mcols = {c["name"] for c in insp.get_columns("materials")}
            if "agent_id" not in mcols:
                conn.execute(text(
                    "ALTER TABLE materials ADD COLUMN agent_id INTEGER REFERENCES agents(id)"
                ))
                print("[ok] materials.agent_id 列已添加")

    with SessionLocal() as db:
        teacher = db.scalar(select(User).where(User.username == "teacher"))
        if not teacher:
            return
        agents = db.scalars(select(Agent)).all()
        # 已占用 (owner_id, name)：避免回填 owner 时撞 UNIQUE(owner_id, name)
        taken: set[tuple[int, str]] = {
            (a.owner_id, a.name)
            for a in agents
            if a.owner_id is not None and a.name
        }

        def _unique_name_for_owner(owner_id: int, name: str, agent_id: int) -> str:
            base = (name or f"智能体-{agent_id}").strip() or f"智能体-{agent_id}"
            candidate = base
            n = 2
            while (owner_id, candidate) in taken:
                candidate = f"{base} ({n})"
                n += 1
                if n > 999:
                    candidate = f"{base} #{agent_id}"
                    break
            taken.add((owner_id, candidate))
            return candidate

        for a in agents:
            if a.owner_id is None:
                new_name = _unique_name_for_owner(teacher.id, a.name, a.id)
                if new_name != a.name:
                    print(f"[ok] 智能体 id={a.id} 重命名 {a.name!r} -> {new_name!r} 以避免归属冲突")
                    a.name = new_name
                else:
                    taken.add((teacher.id, a.name))
                a.owner_id = teacher.id
        db.flush()

        demo_class = db.scalar(select(TeachingClass).order_by(TeachingClass.id).limit(1))
        if demo_class:
            # 仅把「默认教师」名下的同课程智能体绑到示范班，勿污染其他教师的智能体
            for a in agents:
                if a.owner_id != teacher.id:
                    continue
                if a.course_id and demo_class.course_id and a.course_id != demo_class.course_id:
                    continue
                exists = db.scalar(
                    select(AgentClass).where(
                        AgentClass.agent_id == a.id,
                        AgentClass.class_id == demo_class.id,
                    )
                )
                if not exists:
                    db.add(AgentClass(
                        agent_id=a.id,
                        class_id=demo_class.id,
                        assigned_by=teacher.id,
                    ))

        from app.services.chapter_sync import resolve_original_c_lang_agent_id
        c_agent_id = resolve_original_c_lang_agent_id(db)
        c_agent = db.get(Agent, c_agent_id) if c_agent_id else None
        if c_agent:
            c_agent.is_shared = True
            if not c_agent.shared_at:
                from datetime import datetime
                c_agent.shared_at = datetime.utcnow()
            # 先提交归属/班级绑定，避免与大批量 materials 更新叠成一次超长锁
            db.commit()
            if c_agent.course_id:
                db.execute(
                    text("""
                        UPDATE materials
                        SET agent_id = :aid
                        WHERE agent_id IS NULL
                          AND chapter_id IN (
                            SELECT id FROM chapters WHERE course_id = :cid
                          )
                    """),
                    {"aid": c_agent.id, "cid": c_agent.course_id},
                )
                db.commit()
        else:
            db.commit()
    print("[ok] 智能体归属与班级绑定已迁移")


def migrate_agent_content_snapshot() -> None:
    """采纳快照：资源表增加 agent_id；agents 增加 source_snapshot_at；exam_configs 唯一约束扩展。"""
    _recover_exam_configs_new_table()
    insp = inspect(engine)
    with engine.begin() as conn:
        if insp.has_table("agents"):
            cols = {c["name"] for c in insp.get_columns("agents")}
            if "source_snapshot_at" not in cols:
                conn.execute(text(
                    "ALTER TABLE agents ADD COLUMN source_snapshot_at DATETIME"
                ))
                print("[ok] agents.source_snapshot_at 列已添加")

        for table in ("knowledge_points", "question_bank", "exam_configs"):
            if not insp.has_table(table):
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if "agent_id" not in cols:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN agent_id INTEGER REFERENCES agents(id)"
                ))
                print(f"[ok] {table}.agent_id 列已添加")

    if not insp.has_table("exam_configs"):
        return
    with engine.connect() as conn:
        ddl = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='exam_configs'"
        )).scalar() or ""
    ddl_norm = ddl.replace(" ", "")
    if "chapter_id,class_id,agent_id" in ddl_norm:
        return

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS exam_configs_new"))
        conn.execute(text("""
            CREATE TABLE exam_configs_new (
                id INTEGER PRIMARY KEY,
                chapter_id INTEGER NOT NULL REFERENCES chapters(id),
                class_id INTEGER REFERENCES teaching_classes(id),
                agent_id INTEGER REFERENCES agents(id),
                config_json JSON,
                max_attempts INTEGER DEFAULT 0,
                UNIQUE(chapter_id, class_id, agent_id)
            )
        """))
        conn.execute(text("""
            INSERT INTO exam_configs_new (id, chapter_id, class_id, agent_id, config_json, max_attempts)
            SELECT id, chapter_id, class_id, NULL, config_json, max_attempts FROM exam_configs
        """))
        conn.execute(text("DROP TABLE exam_configs"))
        conn.execute(text("ALTER TABLE exam_configs_new RENAME TO exam_configs"))
    print("[ok] exam_configs 已迁移为 (chapter_id, class_id, agent_id) 唯一")


def migrate_exam_feedback() -> None:
    """考核报告反馈：追问、判卷反馈、教师介入。"""
    insp = inspect(engine)
    with engine.begin() as conn:
        ucols = {c["name"] for c in insp.get_columns("users")} if insp.has_table("users") else set()
        if "feedback_credit" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN feedback_credit INTEGER DEFAULT 0"))
            print("[ok] users.feedback_credit 列已添加")
        if not insp.has_table("exam_question_followups"):
            conn.execute(text("""
                CREATE TABLE exam_question_followups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_id INTEGER NOT NULL REFERENCES exams(id),
                    question_idx INTEGER NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    question TEXT NOT NULL,
                    answer TEXT DEFAULT '',
                    recommendations_json JSON DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("[ok] exam_question_followups 表已创建")
        if not insp.has_table("exam_grading_feedbacks"):
            conn.execute(text("""
                CREATE TABLE exam_grading_feedbacks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_question_id INTEGER NOT NULL REFERENCES exam_questions(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    verdict VARCHAR(16) NOT NULL,
                    comment TEXT DEFAULT '',
                    reward_delta INTEGER DEFAULT 0,
                    teacher_confirmed BOOLEAN,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(exam_question_id, user_id)
                )
            """))
            print("[ok] exam_grading_feedbacks 表已创建")
        if not insp.has_table("exam_interventions"):
            conn.execute(text("""
                CREATE TABLE exam_interventions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exam_id INTEGER NOT NULL REFERENCES exams(id),
                    question_idx INTEGER NOT NULL,
                    student_id INTEGER NOT NULL REFERENCES users(id),
                    class_id INTEGER NOT NULL REFERENCES teaching_classes(id),
                    trigger VARCHAR(16) NOT NULL,
                    status VARCHAR(16) DEFAULT 'pending',
                    student_message TEXT DEFAULT '',
                    teacher_response TEXT DEFAULT '',
                    context_json JSON DEFAULT '{}',
                    resolved_by INTEGER REFERENCES users(id),
                    resolved_score REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME
                )
            """))
            print("[ok] exam_interventions 表已创建")
        if insp.has_table("exam_interventions"):
            idx_names = {i["name"] for i in insp.get_indexes("exam_interventions")}
            if "uq_exam_iv_per_question" not in idx_names:
                conn.execute(text("""
                    DELETE FROM exam_interventions
                    WHERE id NOT IN (
                        SELECT MIN(id)
                        FROM exam_interventions
                        GROUP BY exam_id, question_idx, student_id
                    )
                """))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_iv_per_question "
                    "ON exam_interventions (exam_id, question_idx, student_id)"
                ))
                print("[ok] exam_interventions 唯一约束已添加")
    print("[ok] 考核反馈表已迁移")


def migrate_clear_legacy_exam_feedback() -> None:
    """规则变更后一次性清空历史判卷反馈、介入记录及学生信誉分。"""
    insp = inspect(engine)
    if not insp.has_table("exam_grading_feedbacks"):
        return
    with engine.begin() as conn:
        if not insp.has_table("_app_migrations"):
            conn.execute(text("CREATE TABLE _app_migrations (name VARCHAR(64) PRIMARY KEY)"))
        done = conn.execute(text(
            "SELECT 1 FROM _app_migrations WHERE name = 'clear_exam_feedback_v2'"
        )).fetchone()
        if done:
            return
        if insp.has_table("exam_grading_feedbacks"):
            conn.execute(text("DELETE FROM exam_grading_feedbacks"))
        if insp.has_table("exam_interventions"):
            conn.execute(text("DELETE FROM exam_interventions"))
        if insp.has_table("users"):
            conn.execute(text("UPDATE users SET feedback_credit = 0"))
        conn.execute(text("INSERT INTO _app_migrations (name) VALUES ('clear_exam_feedback_v2')"))
        print("[ok] 已清空历史判卷反馈与介入数据")


def migrate_agent_multi_per_lang() -> None:
    """同一教师可创建多个同语言智能体：唯一约束改为 (owner_id, name)。"""
    insp = inspect(engine)
    if not insp.has_table("agents"):
        return
    with engine.begin() as conn:
        for idx in insp.get_indexes("agents"):
            if idx.get("unique") and set(idx.get("column_names") or []) == {"owner_id", "slug"}:
                conn.execute(text(f"DROP INDEX IF EXISTS {idx['name']}"))
                print(f"[ok] 已移除 agents.{idx['name']}（owner_id+slug）")
        names = {i["name"] for i in insp.get_indexes("agents")}
        if "uq_agent_owner_name" not in names:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_owner_name ON agents(owner_id, name)"
            ))
            print("[ok] agents(owner_id, name) 唯一索引已创建")


def migrate_chapters_agent_id() -> None:
    """动态课程章节按智能体隔离：chapters 增加 agent_id 并从资料回填。"""
    insp = inspect(engine)
    if not insp.has_table("chapters"):
        return
    cols = {c["name"] for c in insp.get_columns("chapters")}
    if "agent_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE chapters ADD COLUMN agent_id INTEGER REFERENCES agents(id)"
            ))
        print("[ok] chapters.agent_id 列已添加")

    db = SessionLocal()
    try:
        chapters = db.scalars(
            select(Chapter).where(Chapter.course_id != 1)
        ).all()
        updated = 0
        for ch in chapters:
            if ch.agent_id is not None:
                continue
            agent_ids = db.scalars(
                select(Material.agent_id)
                .where(Material.chapter_id == ch.id, Material.agent_id.isnot(None))
                .distinct()
            ).all()
            if len(agent_ids) == 1:
                ch.agent_id = agent_ids[0]
                updated += 1
        if updated:
            db.commit()
            print(f"[ok] 已回填 {updated} 个章节的 agent_id")
    finally:
        db.close()


def migrate_preset_content_agent_ids() -> None:
    """C 语言预置资料/题库归属原智能体（agent_id 为空的历史数据）。"""
    insp = inspect(engine)
    if not insp.has_table("materials"):
        return
    from app.services.chapter_sync import C_LANG_COURSE_ID, resolve_original_c_lang_agent_id

    with SessionLocal() as db:
        preset_id = resolve_original_c_lang_agent_id(db)
        if not preset_id:
            return
        updated = 0
        for model in (Material, QuestionBank):
            if not insp.has_table(model.__tablename__):
                continue
            cols = {c["name"] for c in insp.get_columns(model.__tablename__)}
            if "agent_id" not in cols:
                continue
            q = select(model).join(Chapter).where(
                Chapter.course_id == C_LANG_COURSE_ID,
                model.agent_id.is_(None),
            )
            for row in db.scalars(q).all():
                row.agent_id = preset_id
                updated += 1
        if updated:
            db.commit()
            print(f"[ok] 已将 {updated} 条 C 语言预置资料/题库归属原智能体 id={preset_id}")


def migrate_knowledge_push() -> None:
    """知识推送：白名单源 / 文章 / 推送记录表 + 种子 RSS。"""
    insp = inspect(engine)
    with engine.begin() as conn:
        if not insp.has_table("knowledge_sources"):
            conn.execute(text("""
                CREATE TABLE knowledge_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(128) NOT NULL,
                    base_url VARCHAR(512) DEFAULT '',
                    rss_url VARCHAR(512) NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    tags VARCHAR(255) DEFAULT '',
                    resource_type VARCHAR(16) DEFAULT 'article',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            print("[ok] knowledge_sources 表已创建")
        if not insp.has_table("knowledge_articles"):
            conn.execute(text("""
                CREATE TABLE knowledge_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES knowledge_sources(id),
                    url VARCHAR(1024) NOT NULL,
                    title VARCHAR(512) DEFAULT '',
                    summary TEXT DEFAULT '',
                    published_at DATETIME,
                    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    keywords_json JSON DEFAULT '[]',
                    resource_type VARCHAR(16) DEFAULT 'article',
                    UNIQUE(url)
                )
            """))
            print("[ok] knowledge_articles 表已创建")
        if not insp.has_table("knowledge_pushes"):
            conn.execute(text("""
                CREATE TABLE knowledge_pushes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    agent_id INTEGER REFERENCES agents(id),
                    course_id INTEGER REFERENCES courses(id),
                    article_id INTEGER NOT NULL REFERENCES knowledge_articles(id),
                    reason TEXT DEFAULT '',
                    kp_names_json JSON DEFAULT '[]',
                    status VARCHAR(16) DEFAULT 'unread',
                    pushed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    read_at DATETIME,
                    UNIQUE(user_id, article_id)
                )
            """))
            print("[ok] knowledge_pushes 表已创建")
        source_cols = {c["name"] for c in inspect(engine).get_columns("knowledge_sources")}
        if "resource_type" not in source_cols:
            conn.execute(text(
                "ALTER TABLE knowledge_sources "
                "ADD COLUMN resource_type VARCHAR(16) DEFAULT 'article'"
            ))
            print("[ok] knowledge_sources.resource_type 已添加")
        article_cols = {c["name"] for c in inspect(engine).get_columns("knowledge_articles")}
        if "resource_type" not in article_cols:
            conn.execute(text(
                "ALTER TABLE knowledge_articles "
                "ADD COLUMN resource_type VARCHAR(16) DEFAULT 'article'"
            ))
            print("[ok] knowledge_articles.resource_type 已添加")

    from app.models import KnowledgeSource

    seeds = (
        ("Real Python", "https://realpython.com", "https://realpython.com/atom.xml", "python,general,en"),
        ("Python.org Blog", "https://blog.python.org", "https://blog.python.org/feeds/posts/default?alt=rss", "python,general,en"),
        ("阮一峰的网络日志", "https://www.ruanyifeng.com/blog", "https://www.ruanyifeng.com/blog/atom.xml", "general,c,python,zh"),
        ("酷壳 CoolShell", "https://coolshell.cn", "https://coolshell.cn/feed", "general,c,python,zh"),
        ("美团技术团队", "https://tech.meituan.com", "https://tech.meituan.com/feed/", "general,python,zh"),
        ("阿里云开发者社区-技术", "https://developer.aliyun.com", "https://developer.aliyun.com/article/rss.xml", "general,python,zh"),
    )
    db = SessionLocal()
    try:
        for name, base, rss, tags in seeds:
            exists = db.scalar(select(KnowledgeSource.id).where(KnowledgeSource.rss_url == rss))
            if not exists:
                db.add(KnowledgeSource(name=name, base_url=base, rss_url=rss, enabled=True, tags=tags))
        db.commit()
        from app.services.knowledge_fetch_service import (
            upsert_bestblogs_whitelist,
            upsert_runoob_tutorials,
        )

        result = upsert_bestblogs_whitelist(db)
        runoob_result = upsert_runoob_tutorials(db)
        print("[ok] 知识推送 RSS 种子已就绪")
        print(
            "[ok] BestBlogs 编程精选白名单已就绪"
            f"（新增 {result['created']}，更新 {result['updated']}）"
        )
        print(
            "[ok] 菜鸟教程薄弱点推荐库已就绪"
            f"（新增 {runoob_result['created']}，更新 {runoob_result['updated']}）"
        )
    finally:
        db.close()


def migrate_class_chat() -> None:
    """课程群聊：群消息 / 私信 / 已读游标。"""
    insp = inspect(engine)
    with engine.begin() as conn:
        if not insp.has_table("class_chat_messages"):
            conn.execute(text("""
                CREATE TABLE class_chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL REFERENCES teaching_classes(id),
                    sender_id INTEGER NOT NULL REFERENCES users(id),
                    msg_type VARCHAR(16) DEFAULT 'text',
                    content TEXT DEFAULT '',
                    title VARCHAR(256),
                    parent_id INTEGER REFERENCES class_chat_messages(id),
                    knowledge_point_id INTEGER REFERENCES knowledge_points(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_class_chat_messages_class_id ON class_chat_messages(class_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_class_chat_messages_parent_id ON class_chat_messages(parent_id)"
            ))
            print("[ok] class_chat_messages 表已创建")
        if not insp.has_table("class_chat_dms"):
            conn.execute(text("""
                CREATE TABLE class_chat_dms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL REFERENCES teaching_classes(id),
                    sender_id INTEGER NOT NULL REFERENCES users(id),
                    receiver_id INTEGER NOT NULL REFERENCES users(id),
                    content TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    read_at DATETIME
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_class_chat_dms_class_id ON class_chat_dms(class_id)"
            ))
            print("[ok] class_chat_dms 表已创建")
        if not insp.has_table("class_chat_reads"):
            conn.execute(text("""
                CREATE TABLE class_chat_reads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    class_id INTEGER NOT NULL REFERENCES teaching_classes(id),
                    channel VARCHAR(64) DEFAULT 'group',
                    last_read_message_id INTEGER DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, class_id, channel)
                )
            """))
            print("[ok] class_chat_reads 表已创建")


def migrate_exam_import_schema() -> None:
    """考卷导入：建新表并为 question_bank 补充溯源/多标签列。"""
    Base.metadata.create_all(bind=engine)
    insp = inspect(engine)
    if not insp.has_table("question_bank"):
        return
    cols = {c["name"] for c in insp.get_columns("question_bank")}
    alters = []
    if "source_import_job_id" not in cols:
        alters.append(
            "ALTER TABLE question_bank ADD COLUMN source_import_job_id "
            "INTEGER REFERENCES exam_import_jobs(id)"
        )
    if "source_page" not in cols:
        alters.append("ALTER TABLE question_bank ADD COLUMN source_page INTEGER")
    if "original_number" not in cols:
        alters.append("ALTER TABLE question_bank ADD COLUMN original_number VARCHAR(32)")
    if "content_hash" not in cols:
        alters.append("ALTER TABLE question_bank ADD COLUMN content_hash VARCHAR(64)")
    if "extra_chapter_ids_json" not in cols:
        alters.append("ALTER TABLE question_bank ADD COLUMN extra_chapter_ids_json JSON")
    if "extra_kp_names_json" not in cols:
        alters.append("ALTER TABLE question_bank ADD COLUMN extra_kp_names_json JSON")
    if alters:
        with engine.begin() as conn:
            for sql in alters:
                conn.execute(text(sql))
        print("[ok] question_bank 导入溯源列已添加")
    # SQLite 无法轻松改 VARCHAR 长度；新增列与表已足够


def run_all_migrations() -> None:
    """启动时幂等迁移（schema 先于 data，避免 ORM 列不存在）。"""
    migrate_users_class_id()
    migrate_users_phone()
    migrate_call_logs_model_name()
    migrate_call_logs_answer_full()
    migrate_call_logs_attachments_json()
    migrate_materials_class_id()
    migrate_question_bank_class_id()
    # 考卷导入相关列/表须尽早创建，后续 ORM 查询会引用新列
    migrate_exam_import_schema()
    migrate_exam_configs_class_id()
    migrate_knowledge_points_class_id()
    migrate_agent_content_snapshot()
    migrate_chapters_agent_id()
    migrate_agents_extend()
    migrate_exam_feedback()
    migrate_clear_legacy_exam_feedback()
    migrate_class_course_enrollment()
    migrate_agent_ownership()
    migrate_agent_multi_per_lang()
    migrate_preset_content_agent_ids()
    backfill_resource_class_ids()
    migrate_knowledge_push()
    migrate_class_chat()


def _ensure_extra_courses(db) -> None:
    """确保 Java / Python 课程记录存在（不预置章节，章节由整本教材上传时从 PDF 生成）。"""
    extras = (
        ("Java程序设计", "Java 程序设计课程：上传整本教材 PDF 后自动分析并生成章节"),
        ("Python程序设计", "Python 程序设计课程：上传整本教材 PDF 后自动分析并生成章节"),
    )
    for name, desc in extras:
        course = db.scalar(select(Course).where(Course.name == name))
        if not course:
            db.add(Course(name=name, description=desc))
    db.flush()
    from app.services.chapter_sync import cleanup_placeholder_chapters
    cleanup_placeholder_chapters(db)


def backfill_resource_class_ids() -> None:
    """将无班级归属的旧资料/题库/考核配置/知识点按课程归入对应首个班级（跳过快照模板）。"""
    insp = inspect(engine)
    if not insp.has_table("teaching_classes"):
        return
    with SessionLocal() as db:
        classes_by_course: dict[int, int] = {}
        for cls in db.scalars(select(TeachingClass).order_by(TeachingClass.id)).all():
            if cls.course_id and cls.course_id not in classes_by_course:
                classes_by_course[cls.course_id] = cls.id
        if not classes_by_course:
            first = db.scalar(select(TeachingClass.id).order_by(TeachingClass.id).limit(1))
            if not first:
                return
            classes_by_course[0] = first

        def class_for_chapter(chapter_id: int | None) -> int | None:
            if not chapter_id:
                return list(classes_by_course.values())[0] if classes_by_course else None
            ch = db.get(Chapter, chapter_id)
            if ch and ch.course_id and ch.course_id in classes_by_course:
                return classes_by_course[ch.course_id]
            return list(classes_by_course.values())[0] if classes_by_course else None

        def _assign_class_id(row, chapter_id: int | None) -> None:
            target = class_for_chapter(chapter_id)
            if target is None:
                return
            row.class_id = target

        if insp.has_table("materials"):
            mcols = {c["name"] for c in insp.get_columns("materials")}
            q = select(Material).where(Material.class_id.is_(None))
            if "agent_id" in mcols:
                q = q.where(Material.agent_id.is_(None))
            for m in db.scalars(q).all():
                _assign_class_id(m, m.chapter_id)

        if insp.has_table("question_bank"):
            qcols = {c["name"] for c in insp.get_columns("question_bank")}
            q = select(QuestionBank).where(QuestionBank.class_id.is_(None))
            if "agent_id" in qcols:
                q = q.where(QuestionBank.agent_id.is_(None))
            for item in db.scalars(q).all():
                _assign_class_id(item, item.chapter_id)

        if insp.has_table("exam_configs"):
            ecols = {c["name"] for c in insp.get_columns("exam_configs")}
            q = select(ExamConfig).where(ExamConfig.class_id.is_(None))
            if "agent_id" in ecols:
                q = q.where(ExamConfig.agent_id.is_(None))
            for ec in db.scalars(q).all():
                target = class_for_chapter(ec.chapter_id)
                if target is None:
                    continue
                conflict = db.scalar(
                    select(ExamConfig.id).where(
                        ExamConfig.chapter_id == ec.chapter_id,
                        ExamConfig.class_id == target,
                        ExamConfig.agent_id.is_(None),
                        ExamConfig.id != ec.id,
                    )
                )
                if conflict:
                    db.delete(ec)
                    continue
                ec.class_id = target

        if insp.has_table("knowledge_points"):
            kcols = {c["name"] for c in insp.get_columns("knowledge_points")}
            q = select(KnowledgePoint).where(KnowledgePoint.class_id.is_(None))
            if "agent_id" in kcols:
                q = q.where(KnowledgePoint.agent_id.is_(None))
            for kp in db.scalars(q).all():
                _assign_class_id(kp, kp.chapter_id)

        db.commit()
    print("[ok] 已按课程回填无班级归属的资料、题库、考核配置与知识点")


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_users_class_id()
    migrate_users_phone()
    migrate_call_logs_model_name()
    migrate_call_logs_answer_full()
    migrate_call_logs_attachments_json()
    migrate_materials_class_id()
    migrate_question_bank_class_id()
    migrate_exam_configs_class_id()
    migrate_knowledge_points_class_id()
    migrate_agent_content_snapshot()
    migrate_agents_extend()
    migrate_class_course_enrollment()
    migrate_agent_ownership()
    migrate_agent_multi_per_lang()
    backfill_resource_class_ids()
    print("[ok] 表已创建")


def drop_tables() -> None:
    Base.metadata.drop_all(bind=engine)
    print("[ok] 已清空所有表")


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
    course = Course(
        name="C程序设计快速进阶大学教程",
        description="基于《C程序设计快速进阶大学教程》（蒋光远，清华大学出版社），三篇 17 章结构",
    )
    db.add(course)
    db.flush()

    for order_idx, title, desc, kps in TEXTBOOK_CHAPTERS:
        ch = Chapter(
            course_id=course.id,
            title=title,
            order_idx=order_idx,
            description=desc,
        )
        db.add(ch)
        db.flush()

        for kp_name in kps:
            db.add(KnowledgePoint(chapter_id=ch.id, name=kp_name))

        db.add(ExamConfig(
            chapter_id=ch.id,
            config_json={
                "选择题": 2,
                "判断题": 2,
                "简答题": 1,
                "knowledge_points": kps,
            },
        ))

    db.commit()
    print(f"[ok] 已注入课程《{course.name}》：{len(TEXTBOOK_CHAPTERS)} 章 + 知识点 + 考核配置")


def seed_question_bank_demo(db) -> None:
    """为关键章节录入示例题库，保证开考不依赖 LLM 也能出题。"""
    if db.scalar(select(QuestionBank)):
        print("[skip] 题库已存在示例题")
        return

    # 通过章节标题查找 chapter_id
    def ch_id(title: str) -> int:
        ch = db.scalar(select(Chapter).where(Chapter.title == title))
        return ch.id if ch else 0

    kp_id = lambda ch_id_, name: (
        db.scalar(select(KnowledgePoint).where(
            KnowledgePoint.chapter_id == ch_id_, KnowledgePoint.name == name
        )) and db.scalar(select(KnowledgePoint).where(
            KnowledgePoint.chapter_id == ch_id_, KnowledgePoint.name == name
        )).id or None
    )

    samples = [
        # 第5章 数据类型与输入输出
        (ch_id("第5章 数据类型与输入输出"), "数据类型", "选择题",
         "下列哪个不是C语言的基本数据类型？",
         ["A. int", "B. float", "C. string", "D. char"],
         "C", "C语言没有string类型，字符串用char数组表示。"),
        (ch_id("第5章 数据类型与输入输出"), "数据类型", "判断题",
         "在C语言中，int类型变量可以存储任意大小的整数。",
         ["对", "错"],
         "错", "int类型有取值范围，通常为-2147483648~2147483647，不能存储任意大小整数。"),
        # 第7章 选择结构
        (ch_id("第7章 选择结构"), "switch语句", "选择题",
         "switch语句中，用于终止当前case分支的关键字是？",
         ["A. break", "B. continue", "C. return", "D. exit"],
         "A", "break用于跳出switch结构，避免case穿透。"),
        (ch_id("第7章 选择结构"), "单分支if语句", "判断题",
         "if语句的条件表达式必须用圆括号括起来。",
         ["对", "错"],
         "对", "C语言规定if后面的条件表达式必须用()括起。"),
        # 第11章 指针
        (ch_id("第11章 指针"), "指针变量", "选择题",
         "若有定义 int *p; 则 p 可以存储什么？",
         ["A. 一个整数", "B. 一个整型变量的地址", "C. 一个字符", "D. 一个字符串"],
         "B", "int *p 声明p为指向int类型变量的指针，存储的是地址。"),
        (ch_id("第11章 指针"), "指针变量", "判断题",
         "指针变量必须先初始化或赋值后才能使用，否则会访问非法内存。",
         ["对", "错"],
         "对", "未初始化的野指针解引用会导致未定义行为或程序崩溃。"),
    ]

    for chap_id, kp_name, qtype, stem, options, answer, analysis in samples:
        if not chap_id:
            continue
        kp = kp_id(chap_id, kp_name)
        demo_class_id = db.scalar(select(TeachingClass.id).order_by(TeachingClass.id).limit(1))
        db.add(QuestionBank(
            chapter_id=chap_id,
            class_id=demo_class_id,
            kp_id=kp,
            type=qtype,
            stem=stem,
            options_json=options,
            answer=answer,
            analysis=analysis,
        ))

    db.commit()
    print(f"[ok] 已注入 {len(samples)} 道示例题（第5、7、11章）")


def seed_agent(db) -> None:
    course = db.scalar(select(Course).where(Course.id == 1))
    agents_data = [
        {
            "slug": "c-lang",
            "name": "C语言课程智能体",
            "intro": "基于 RAG 的 C 语言程序设计课程问答、资源推荐与章节考核智能体，"
                     "知识库来源于《C程序设计快速进阶大学教程》。",
            "status": "active",
            "course_id": course.id if course else None,
        },
        {
            "slug": "java",
            "name": "Java课程智能体",
            "intro": "面向 Java 程序设计课程的智能问答、资源推荐与章节考核（筹备中，可扩展接入教材与题库）。",
            "status": "planned",
            "course_name": "Java程序设计",
        },
        {
            "slug": "python",
            "name": "Python课程智能体",
            "intro": "面向 Python 程序设计课程的智能问答、资源推荐与章节考核（筹备中，可扩展接入教材与题库）。",
            "status": "planned",
            "course_name": "Python程序设计",
        },
    ]
    created = 0
    for item in agents_data:
        if db.scalar(select(Agent).where(Agent.slug == item["slug"])):
            continue
        course_id = item.get("course_id")
        if not course_id and item.get("course_name"):
            c = db.scalar(select(Course).where(Course.name == item["course_name"]))
            course_id = c.id if c else None
        db.add(Agent(
            name=item["name"],
            intro=item["intro"],
            endpoint="/api/agents/course/ask",
            slug=item["slug"],
            status=item["status"],
            course_id=course_id,
        ))
        created += 1
    if created:
        db.commit()
        print(f"[ok] 已注入 {created} 个课程智能体")
    else:
        print("[skip] 智能体已存在")


def seed_demo_class(db) -> None:
    """创建示例班级并将 student 加入、teacher 设为管理教师。"""
    if db.scalar(select(TeachingClass)):
        print("[skip] 示例班级已存在")
        return
    teacher = db.scalar(select(User).where(User.username == "teacher"))
    student = db.scalar(select(User).where(User.username == "student"))
    if not teacher:
        print("[skip] 未找到 teacher 账号，跳过示例班级")
        return

    cls = TeachingClass(
        name="2025软院C语言1班",
        invite_code=secrets.token_hex(3).upper(),
        created_by=teacher.id,
        course_id=db.scalar(
            select(Course.id).where(Course.name.contains("C程序")).order_by(Course.id).limit(1)
        ),
    )
    db.add(cls)
    db.flush()
    db.add(ClassTeacher(class_id=cls.id, user_id=teacher.id))
    if student and cls.course_id:
        db.add(ClassEnrollment(
            user_id=student.id, class_id=cls.id, course_id=cls.course_id
        ))
        student.class_id = cls.id
    db.commit()
    print(f"[ok] 示例班级已创建，邀请码: {cls.invite_code}")


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
    reset = "--reset" in sys.argv
    if reset:
        drop_tables()
    create_tables()
    db = SessionLocal()
    try:
        seed_admin(db)
        seed_course(db)
        _ensure_extra_courses(db)
        seed_demo_class(db)
        seed_question_bank_demo(db)
        seed_agent(db)
        seed_llm_config(db)
    finally:
        db.close()
    print("\n[done] 初始化完成")


if __name__ == "__main__":
    main()
