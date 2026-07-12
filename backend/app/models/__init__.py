"""ORM 模型：覆盖全部业务表。"""
from datetime import datetime
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="student")  # student/teacher/admin
    display_name: Mapped[str] = mapped_column(String(64), default="")
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    progress: Mapped[list["ChapterProgress"]] = relationship(back_populates="user")
    exams: Mapped[list["Exam"]] = relationship(back_populates="user")
    teaching_class: Mapped["TeachingClass | None"] = relationship(
        back_populates="students",
        foreign_keys=[class_id],
    )
    managed_classes: Mapped[list["ClassTeacher"]] = relationship(
        back_populates="teacher",
        foreign_keys="ClassTeacher.user_id",
    )


class TeachingClass(Base):
    __tablename__ = "teaching_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    invite_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    students: Mapped[list["User"]] = relationship(
        back_populates="teaching_class",
        foreign_keys="User.class_id",
    )
    teachers: Mapped[list["ClassTeacher"]] = relationship(back_populates="teaching_class", cascade="all, delete-orphan")
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])


class ClassTeacher(Base):
    __tablename__ = "class_teachers"

    class_id: Mapped[int] = mapped_column(ForeignKey("teaching_classes.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)

    teaching_class: Mapped["TeachingClass"] = relationship(back_populates="teachers")
    teacher: Mapped["User"] = relationship(
        back_populates="managed_classes",
        foreign_keys=[user_id],
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")

    chapters: Mapped[list["Chapter"]] = relationship(back_populates="course", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    title: Mapped[str] = mapped_column(String(128))
    order_idx: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")

    course: Mapped["Course"] = relationship(back_populates="chapters")
    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    materials: Mapped[list["Material"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")
    exam_configs: Mapped[list["ExamConfig"]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128))

    chapter: Mapped["Chapter"] = relationship(back_populates="knowledge_points")


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(16))  # ppt/pdf/video/word
    title: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chapter: Mapped["Chapter"] = relationship(back_populates="materials")
    teaching_class: Mapped["TeachingClass | None"] = relationship(foreign_keys=[class_id])
    video_segments: Mapped[list["VideoSegment"]] = relationship(back_populates="material", cascade="all, delete-orphan")


class VideoSegment(Base):
    __tablename__ = "video_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    start_sec: Mapped[int] = mapped_column(Integer)
    end_sec: Mapped[int] = mapped_column(Integer)
    subtitle_text: Mapped[str] = mapped_column(Text, default="")

    material: Mapped["Material"] = relationship(back_populates="video_segments")


class ExamConfig(Base):
    __tablename__ = "exam_configs"
    __table_args__ = (UniqueConstraint("chapter_id", "class_id", name="uq_exam_config_chapter_class"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # {"选择题": 2, "判断题": 2, "简答题": 2, "knowledge_points": ["AVL树", ...]}
    max_attempts: Mapped[int] = mapped_column(Integer, default=0)  # 0=无限次

    chapter: Mapped["Chapter"] = relationship(back_populates="exam_configs")


class QuestionBank(Base):
    __tablename__ = "question_bank"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    class_id: Mapped[int | None] = mapped_column(ForeignKey("teaching_classes.id"), nullable=True)
    kp_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(16))  # 选择题/判断题/简答题
    stem: Mapped[str] = mapped_column(Text)
    options_json: Mapped[dict] = mapped_column(JSON, default=list)  # ["A. ...", ...]
    answer: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str] = mapped_column(Text, default="")


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    status: Mapped[str] = mapped_column(String(16), default="ongoing")  # ongoing/submitted
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="exams")
    questions: Mapped[list["ExamQuestion"]] = relationship(back_populates="exam", cascade="all, delete-orphan", order_by="ExamQuestion.idx")
    report: Mapped["ExamReport | None"] = relationship(back_populates="exam", uselist=False, cascade="all, delete-orphan")


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    idx: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(8), default="bank")  # bank/llm
    type: Mapped[str] = mapped_column(String(16))
    stem: Mapped[str] = mapped_column(Text)
    options_json: Mapped[dict] = mapped_column(JSON, default=list)
    correct_answer: Mapped[str] = mapped_column(Text, default="")
    user_answer: Mapped[str] = mapped_column(Text, default="")
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_score: Mapped[float | None] = mapped_column(nullable=True)
    ai_feedback: Mapped[str] = mapped_column(Text, default="")
    analysis: Mapped[str] = mapped_column(Text, default="")
    kp_name: Mapped[str] = mapped_column(String(128), default="")

    exam: Mapped["Exam"] = relationship(back_populates="questions")


class ExamReport(Base):
    __tablename__ = "exam_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), unique=True)
    dimensions_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    suggestions: Mapped[str] = mapped_column(Text, default="")
    total_score: Mapped[float | None] = mapped_column(nullable=True)
    weak_points: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    exam: Mapped["Exam"] = relationship(back_populates="report")


class ChapterProgress(Base):
    __tablename__ = "chapter_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id"))
    status: Mapped[str] = mapped_column(String(16), default="未完成")  # 未完成/已完成/待学习
    last_exam_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped["User"] = relationship(back_populates="progress")


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))  # deepseek/qwen/openai/moonshot/...
    api_key: Mapped[str] = mapped_column(String(255))
    base_url: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(64))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    intro: Mapped[str] = mapped_column(Text, default="")
    endpoint: Mapped[str] = mapped_column(String(128), default="")  # 调用入口标识
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    slug: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / planned


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    endpoint: Mapped[str] = mapped_column(String(128))
    req_summary: Mapped[str] = mapped_column(Text, default="")
    resp_summary: Mapped[str] = mapped_column(Text, default="")
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(128), default="")
    answer_full: Mapped[str] = mapped_column(Text, default="")
    attachments_json: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
