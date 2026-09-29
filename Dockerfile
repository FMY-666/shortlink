# 基础镜像的版本要和本地对齐 —— 本地 venv 是 3.14，镜像也用 3.14。
# 别用 latest：体积大，而且哪天上游一升级，会悄悄换掉你已经验证过的运行时。
FROM python:3.14-slim

# 容器里的工作目录
WORKDIR /app

# 环境变量：不写 .pyc、日志不缓冲（不然 docker logs 看不到实时输出）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 先只拷依赖清单再装依赖 —— 这一层能被缓存住。
# 只要你没改 requirements.txt，以后改代码时重建镜像不会重装依赖，快很多。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码
COPY app ./app

EXPOSE 8000

# 生产环境：不要 --reload，要指定 worker 数
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
