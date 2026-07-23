"""SQLAlchemy 引擎与会话。"""
from collections.abc import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

engine = create_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False, "timeout": 60},
    echo=False,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_on_connect(dbapi_conn, _connection_record) -> None:
    """先 busy_timeout 再尝试 WAL，减轻 Windows 下多进程/热重载时的 database is locked。"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA busy_timeout=60000")
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except Exception:
        # 有其它连接独占锁时跳过；timeout 已保证后续读写可排队等待
        pass
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def shutdown_db() -> None:
    """释放连接池，避免 Windows 下 Ctrl+C 后进程挂起。"""
    engine.dispose()
