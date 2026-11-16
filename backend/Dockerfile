FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（psycopg2 或 asyncpg 编译可能需要的组件）
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制剩下的代码
COPY . .

# 暴露端口
EXPOSE 8000

# 默认启动命令（会被 docker-compose 里的 command 覆盖）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]