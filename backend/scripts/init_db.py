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

from sqlalchemy import inspect, select, text

from app.database import Base, SessionLocal, engine
from app.models import (
    Agent,
    Chapter,
    ClassTeacher,
    Course,
    ExamConfig,
    KnowledgePoint,
    LLMConfig,
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


def migrate_exam_configs_class_id() -> None:
    """兼容已有数据库：exam_configs 增加 class_id，并改为 (chapter_id, class_id) 唯一。"""
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
    if "UNIQUE(chapter_id,class_id)" in ddl_norm:
        return

    with engine.begin() as conn:
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
        for slug, name, intro, status in (
            ("java", "Java课程智能体",
             "面向 Java 程序设计课程的智能问答、资源推荐与章节考核（筹备中）。", "planned"),
            ("python", "Python课程智能体",
             "面向 Python 程序设计课程的智能问答、资源推荐与章节考核（筹备中）。", "planned"),
        ):
            if not db.scalar(select(Agent).where(Agent.slug == slug)):
                db.add(Agent(
                    name=name, intro=intro, endpoint="/api/agents/course/ask",
                    slug=slug, status=status, course_id=None,
                ))
        db.commit()


def backfill_resource_class_ids() -> None:
    """将无班级归属的旧资料/题库/考核配置/知识点归入首个班级（便于迁移后继续使用）。"""
    insp = inspect(engine)
    if not insp.has_table("teaching_classes"):
        return
    with engine.begin() as conn:
        first_class = conn.execute(
            text("SELECT id FROM teaching_classes ORDER BY id LIMIT 1")
        ).scalar()
        if not first_class:
            return
        if insp.has_table("materials"):
            conn.execute(text(
                "UPDATE materials SET class_id = :cid WHERE class_id IS NULL"
            ), {"cid": first_class})
        if insp.has_table("question_bank"):
            conn.execute(text(
                "UPDATE question_bank SET class_id = :cid WHERE class_id IS NULL"
            ), {"cid": first_class})
        if insp.has_table("exam_configs"):
            conn.execute(text(
                "UPDATE exam_configs SET class_id = :cid WHERE class_id IS NULL"
            ), {"cid": first_class})
        if insp.has_table("knowledge_points"):
            conn.execute(text(
                "UPDATE knowledge_points SET class_id = :cid WHERE class_id IS NULL"
            ), {"cid": first_class})
    print("[ok] 已回填无班级归属的资料、题库、考核配置与知识点")


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_users_class_id()
    migrate_call_logs_model_name()
    migrate_call_logs_answer_full()
    migrate_call_logs_attachments_json()
    migrate_materials_class_id()
    migrate_question_bank_class_id()
    migrate_exam_configs_class_id()
    migrate_knowledge_points_class_id()
    migrate_agents_extend()
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
            "course_id": None,
        },
        {
            "slug": "python",
            "name": "Python课程智能体",
            "intro": "面向 Python 程序设计课程的智能问答、资源推荐与章节考核（筹备中，可扩展接入教材与题库）。",
            "status": "planned",
            "course_id": None,
        },
    ]
    created = 0
    for item in agents_data:
        if db.scalar(select(Agent).where(Agent.slug == item["slug"])):
            continue
        db.add(Agent(
            name=item["name"],
            intro=item["intro"],
            endpoint="/api/agents/course/ask",
            slug=item["slug"],
            status=item["status"],
            course_id=item["course_id"],
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
    )
    db.add(cls)
    db.flush()
    db.add(ClassTeacher(class_id=cls.id, user_id=teacher.id))
    if student:
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
        seed_demo_class(db)
        seed_question_bank_demo(db)
        seed_agent(db)
        seed_llm_config(db)
    finally:
        db.close()
    print("\n[done] 初始化完成")


if __name__ == "__main__":
    main()
