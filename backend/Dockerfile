# 国内网络拉 Docker Hub 易超时：使用 DaoCloud 代理官方 library 镜像
# 不 apt 装 ffmpeg、不 pip 装 whisper/torch：体积过大且易拖垮本机 Docker。
# 核心 API（问答/考核/资料文本索引）可正常验收；视频 ASR 用本机 backend\dev.bat 演示。
FROM docker.m.daocloud.io/library/python:3.11-slim

WORKDIR /app

COPY requirements.txt chromadb-deps.txt ./
RUN pip install --no-cache-dir --upgrade pip \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
    && pip install --no-cache-dir chroma-hnswlib==0.7.5 \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
    && pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
    && pip install --no-cache-dir -r chromadb-deps.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn \
    && pip install --no-cache-dir chromadb==0.5.23 --no-deps \
        -i https://pypi.tuna.tsinghua.edu.cn/simple \
        --trusted-host pypi.tuna.tsinghua.edu.cn

COPY . .

ENV PYTHONUNBUFFERED=1 \
    SMS_DEV_MODE=1 \
    SQLITE_PATH=/data/course.db \
    CHROMA_PATH=/data/chroma \
    UPLOAD_DIR=/data/uploads

EXPOSE 8000

CMD ["sh", "-c", "python -m scripts.init_db && python -m scripts.run_migrations && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
