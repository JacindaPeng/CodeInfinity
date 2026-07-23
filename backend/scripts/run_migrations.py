"""启动前执行数据库迁移（供 dev.bat 调用）。"""
from scripts.init_db import run_all_migrations

if __name__ == "__main__":
    run_all_migrations()
