import os

from dotenv import load_dotenv

load_dotenv()

# ---- MySQL ----
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "shortlink")

# ---- Redis（v2 才用到，先放着）----
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# ---- 业务参数 ----
CODE_LEN = int(os.getenv("CODE_LEN", "6"))
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
URL_MAX_LEN = int(os.getenv("URL_MAX_LEN", "2048"))