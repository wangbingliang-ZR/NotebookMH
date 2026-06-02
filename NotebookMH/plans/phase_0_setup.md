# Phase 0 — 范围冻结与配置（Step 0-3）

> **执行前必读**: `ARCHITECTURE.md` + `BUILD_PLAN.md`
> **本阶段目标**: 备份旧代码、建立新骨架、加载环境变量
> **本阶段无 Checkpoint**（Step 5 完成时做第一次）

---

## Step 0：备份旧代码

**目标**: 把现有所有非文档代码原样移入 `archive_legacy/`，不删除，仅归档。

**工作目录**: `c:\大饼的ai助手\zijiannotebookdb\NotebookMH`

**操作**:
1. 创建目录 `archive_legacy/`
2. 把以下目录整体移入 `archive_legacy/`（保持目录结构）:
   - `core/`
   - `frontend/`
   - `utils/`
   - `tests/`（如果存在）
3. 把根目录 `app.py` 移入 `archive_legacy/`
4. 不动的文件: `requirements.txt`、`.streamlit/`、`data/`、所有 `*.md`、`PROGRESS_legacy_v1.md`

**禁止**:
- ❌ 删除任何文件
- ❌ 修改 archive 中的内容

**验收命令**:
```powershell
Get-ChildItem -Path "archive_legacy" -Directory | Select-Object Name
Get-ChildItem -Path "." -Filter "*.py" | Select-Object Name
```

**预期输出**:
- 第一条: 列出 `core`, `frontend`, `utils`（可能含 `tests`）
- 第二条: 根目录无 `.py` 文件

**PROGRESS.md 记录模板**:
```
[Step 0] ✅ 备份旧代码
- 改动: archive_legacy/ 创建，移入 core/ frontend/ utils/ app.py
- 验证输出: <粘贴 ls 结果>
```

---

## Step 1：创建新目录骨架

**目标**: 按 `ARCHITECTURE.md` 第 4 节创建空目录和占位文件。

**操作**:
1. 创建目录: `core/`、`ui/`、`plans/`（若不存在）、`data/uploads/`
2. 创建以下文件，**每个文件仅含一行 docstring**（不写任何业务代码）:
   - `core/__init__.py`（内容: `"""core package"""`）
   - `core/db.py`
   - `core/vector_store.py`
   - `core/ingest.py`
   - `core/parsers.py`
   - `core/rag.py`
   - `core/llm.py`
   - `core/chat.py`
   - `core/studio.py`
   - `ui/__init__.py`
   - `ui/sidebar.py`
   - `ui/chat_panel.py`
   - `ui/studio_panel.py`
   - `ui/components.py`
   - `config.py`
3. 创建 `app.py`，内容如下:
   ```python
   """app.py — NotebookMH 入口（占位）"""
   import streamlit as st
   st.set_page_config(page_title="NotebookMH", layout="wide")
   st.title("NotebookMH（构建中）")
   ```
4. 创建 `.env.example`:
   ```
   DEEPSEEK_API_KEY=
   AI_BASE_URL=https://api.deepseek.com/v1
   AI_MODEL=deepseek-chat
   ```

**禁止**:
- ❌ 在占位文件中写业务代码
- ❌ 创建不在 ARCHITECTURE 第 4 节列表中的文件

**验收命令**:
```powershell
streamlit run app.py --server.headless true
```
等待 10 秒后用 curl 或浏览器访问 http://localhost:8501

**预期**: 浏览器看到 "NotebookMH（构建中）"，终端无 Traceback。

**截图/输出**: 把 streamlit 终端首 10 行粘到 PROGRESS.md

---

## Step 2：编写 config.py

**目标**: 所有路径、模型名、常量集中到 `config.py`。

**操作**: 把 `config.py` 内容完全替换为:

```python
"""config.py — 全局配置与常量"""
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# 加载 .env（向上查找，支持根目录 .env）
load_dotenv(find_dotenv(usecwd=True))

# ── 路径 ───────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
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
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# ── Chunk 参数 ───────────────────────────────────────
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

# ── 检索 ─────────────────────────────────────────────
RAG_TOP_K = 5
BM25_WEIGHT = 0.4
DENSE_WEIGHT = 0.6

# ── 业务限制 ─────────────────────────────────────────
MAX_SOURCES_PER_VAULT = 50
MAX_FILE_SIZE_MB = 500
MAX_CHAT_HISTORY = 50

# ── 支持的文件类型 ────────────────────────────────────
SUPPORTED_EXTS = ["pdf", "docx", "pptx", "txt", "md", "csv", "json"]
```

**禁止**:
- ❌ 在其它文件硬编码这里定义的常量

**验收命令**:
```powershell
python -c "import config; print('DATA_DIR:', config.DATA_DIR); print('USE_MOCK:', config.USE_MOCK_LLM); print('EXTS:', config.SUPPORTED_EXTS); print('CHUNK_SIZE:', config.CHUNK_SIZE)"
```

**预期**:
```
DATA_DIR: c:\大饼的ai助手\zijiannotebookdb\NotebookMH\data
USE_MOCK: True 或 False
EXTS: ['pdf', 'docx', 'pptx', 'txt', 'md', 'csv', 'json']
CHUNK_SIZE: 500
```
无 ImportError。

---

## Step 3：修复 .env 加载 + 防翻译

**目标**: 解决 (a) 根目录 `.env` 加载不到 (b) Chrome 翻译扩展乱码两个问题。

**操作**:

1. **检查 .env**:
   - 查看 `c:\大饼的ai助手\zijiannotebookdb\.env` 是否存在
   - 若存在且含 `DEEPSEEK_API_KEY=xxx` → 复制到 `c:\大饼的ai助手\zijiannotebookdb\NotebookMH\.env`
   - 若都不存在 → 创建 `NotebookMH\.env`，留 `DEEPSEEK_API_KEY=` 空值（用户后填）

2. **更新 app.py**:
   ```python
   """app.py — NotebookMH 入口"""
   import streamlit as st
   import config  # 必须最先 import，确保 .env 已加载

   st.set_page_config(
       page_title="NotebookMH",
       page_icon="📓",
       layout="wide",
       initial_sidebar_state="expanded",
   )

   # 防翻译扩展乱码
   st.markdown(
       '<meta name="google" content="notranslate">'
       '<style>body, .stApp, [class*="st-"] { translate: no !important; }</style>',
       unsafe_allow_html=True,
   )

   st.title("NotebookMH")
   st.write(f"API Key 已加载: {bool(config.DEEPSEEK_API_KEY)}")
   st.write(f"Mock 模式: {config.USE_MOCK_LLM}")
   st.caption("Step 3 占位页 — 下一步开始建数据库")
   ```

**禁止**:
- ❌ 把 API Key 硬编码进代码
- ❌ 把 `.env` 内容写入任何 `*.md`

**验收命令**:
```powershell
streamlit run app.py --server.headless true
```

**预期**:
- 浏览器打开 http://localhost:8501
- 看到 "API Key 已加载: True"（如果 .env 配了 key）或 "False"
- 看到 "Mock 模式: False" 或 "True"，与上面一致
- 用 Chrome 翻译插件触发翻译，文字应**保持中文不变**

**记录到 PROGRESS.md**:
```
[Step 3] ✅ .env + 防翻译
- 改动: app.py, .env (若新建)
- 验证: API Key 加载=<True/False>, Mock=<对应>
- 浏览器截图(可选): <如有>
```

---

## 阶段 0 完成

完成 Step 3 后：
1. 把 PROGRESS.md 中"当前 Step"更新为"Step 4 (阶段 A)"
2. 阅读 `plans/phase_a_foundation.md`
3. 开始 Step 4
