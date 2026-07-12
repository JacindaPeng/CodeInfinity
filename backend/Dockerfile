FROM python:3.11-slim

# ffmpeg 用于视频抽音频；whisper 转写需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir chromadb==0.5.23 \
    && pip install --no-cache-dir openai-whisper || echo "whisper install skipped (optional)"

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# 启动时自动建表 + 注入种子数据
CMD ["sh", "-c", "python -m scripts.init_db && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
