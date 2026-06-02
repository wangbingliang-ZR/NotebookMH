"""config.py — 全局配置与常量"""
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# ── 路径 ───────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()

# 加载 .env（从脚本所在目录找，不受 Streamlit CWD 影响）
_env_path = BASE_DIR / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)
else:
    # fallback：向上查找
    load_dotenv(find_dotenv(), override=True)
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma_db"
DB_PATH = DATA_DIR / "sys.db"

for p in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR):
    p.mkdir(parents=True, exist_ok=True)

# ── LLM ─────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")
USE_MOCK_LLM = not DEEPSEEK_API_KEY

# ── Embedding ───────────────────────────────────────
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # 384 维，支持中文
USE_SEMANTIC_EMBEDDING = False  # 禁用语义模型，直接用 HashingVectorizer（避免加载失败日志噪音）

# ── Chunk 参数 ───────────────────────────────────────
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# ── 检索 ─────────────────────────────────────────────
RAG_TOP_K = 5
RERANK_TOP_K = 3   # RRF 融合后再用语义重排取前 3
BM25_WEIGHT = 0.4
DENSE_WEIGHT = 0.6

# ── 业务限制 ─────────────────────────────────────────
MAX_SOURCES_PER_VAULT = 50
MAX_FILE_SIZE_MB = 500
MIN_CONTENT_LENGTH = 30  # 少于 30 字视为无效来源
MAX_CHAT_HISTORY = 50

# ── 支持的文件类型 ────────────────────────────────────
SUPPORTED_EXTS = ["pdf", "docx", "pptx", "txt", "md", "csv", "json"]
