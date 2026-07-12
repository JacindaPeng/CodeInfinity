"""密码哈希工具（直接使用 bcrypt 4.x 原生 API，避免 passlib 与新版 bcrypt 的兼容问题）。"""
import bcrypt


def hash_password(raw: str) -> str:
    # bcrypt 限制密码最长 72 字节，超出部分截断（与 passlib 默认行为一致）
    pw = raw.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    pw = raw.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
