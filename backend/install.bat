@echo off
chcp 65001 >nul
REM Windows 一键安装脚本
REM
REM 规避两个问题：
REM   1) chroma-hnswlib==0.7.6 在 Py3.12 win 下无预编译 wheel，源码构建需 Visual C++。
REM      改用 0.7.5（有 cp312 win_amd64 wheel，API 兼容）。
REM   2) langchain-chroma 会传递性引入 chromadb，再触发 hnswlib 0.7.6 构建。
REM      已从 requirements.txt 移除 langchain-chroma（代码中未使用）。
REM
REM 安装顺序：
REM   [1] chroma-hnswlib==0.7.5（强制 wheel，不编译）
REM   [2] requirements.txt 核心依赖（不再含 langchain-chroma，不会传递拉 chromadb）
REM   [3] chromadb 的其余依赖（chromadb-deps.txt，已排除 hnswlib）
REM   [4] chromadb==0.5.23 --no-deps（复用已装的 hnswlib 0.7.5 与其余依赖）

echo [1/4] 安装 chroma-hnswlib==0.7.5（强制使用预编译 wheel）
pip install chroma-hnswlib==0.7.5 --only-binary chroma-hnswlib
if errorlevel 1 ( echo [X] chroma-hnswlib 安装失败 & exit /b 1 )

echo [2/4] 安装核心依赖 requirements.txt
pip install -r requirements.txt
if errorlevel 1 ( echo [X] 核心依赖安装失败 & exit /b 1 )

echo [3/4] 安装 chromadb 其余依赖 chromadb-deps.txt
pip install -r chromadb-deps.txt
if errorlevel 1 ( echo [X] chromadb 依赖安装失败 & exit /b 1 )

echo [4/4] 安装 chromadb==0.5.23（--no-deps，复用已装依赖）
pip install chromadb==0.5.23 --no-deps
if errorlevel 1 ( echo [X] chromadb 安装失败 & exit /b 1 )

echo.
echo === 验证 ===
python -c "import chromadb; print('chromadb', chromadb.__version__)"
python -c "import hnswlib; print('hnswlib OK')"
python -c "import sqlalchemy, fastapi; from langchain_text_splitters import RecursiveCharacterTextSplitter; print('core deps OK')"
echo.
echo 下一步: python -m scripts.init_db
