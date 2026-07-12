@echo off
chcp 65001 >nul
cd /d %~dp0
call venv\Scripts\activate
echo 启动后端开发服务（仅监听 app/ 与 scripts/ 变更，避免频繁重启）
echo 若登录超时，请先停止其他 uvicorn 进程，再重新运行本脚本
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --reload-dir scripts --reload-exclude "**/__pycache__/**" --reload-delay 1.0
