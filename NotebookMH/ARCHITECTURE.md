# ARCHITECTURE.md — 架构冻结文档（Frozen Spec v1.0）

> 本文档是**最高约束**。任何代码改动若与本文档冲突，必须先修改本文档并经用户确认。
> DeepSeek V4 执行任何 Step 前必须先阅读本文档，每 5 步重读一次。

---

## 1. 产品定位（不准偏离）

**一句话**：1:1 对标 Google NotebookLM 的中文版个人知识助手。

**核心交互流（用户视角）**：
```
1. 输入用户名 → 选/建笔记库
2. 上传来源（PDF/DOCX/TXT/MD/PPTX/CSV/JSON/URL/粘贴）
3. 直接问答（带引用、流式、多轮）
4. 一键生成 Studio 内容（摘要/FAQ/思维导图/闪卡/测验等）
5. 保存为笔记 → 导出
```

**禁止偏离的设计原则**：
- 默认就是"问答"模式，不存在"认知模式切换"
- AI 是助手，不是老师，**直接回答**问题（不强制反问、不强制苏格拉底）
- 简洁 UI，无任何"遥测/神经/全息/沙箱/守护"等术语
- 不引入"音频概述"（本期）

---

## 2. 12 项核心功能清单（范围冻结）

| ID | 功能 | 验收标准（NotebookLM 等价） |
|----|------|----------|
| F1 | 多用户切换 | 侧边栏输入用户名即切换，数据隔离 |
| F2 | 多笔记库 (Vault) | 创建/切换/删除，数据按 vault 隔离 |
| F3 | 多源上传 | 支持 PDF/DOCX/PPTX/TXT/MD/CSV/JSON/URL/粘贴文本 |
| F4 | 文档解析+向量入库 | 解析→chunk→embedding→ChromaDB |
| F5 | 来源列表 + 详情 + 删除 | 侧边栏可见、点击查看片段、可删除 |
| F6 | 对话（引用+流式+多轮） | 回答含 [1][2] 引用、字符流出、记得历史 |
| F7 | 来源筛选 | 勾选哪些源参与对话 |
| F8 | Studio：摘要 | 一键生成 300 字摘要 |
| F9 | Studio：FAQ/学习指南/简报/时间线 | 一键生成对应内容 |
| F10 | Studio：思维导图 | Mermaid mindmap 渲染 |
| F11 | Studio：闪卡+测验+错题本 | 生成 → 答题 → 错题入本 → 重练 |
| F12 | 笔记保存+导出 | 保存 AI 回复，导出 MD/Word/PDF |

**清单外功能一律不做**。如果 DeepSeek 在执行中"灵机一动"想加功能，必须先记入 PROGRESS.md 的"灵机一动暂存区"，由用户决定。

---

## 3. 技术栈（冻结）

| 层 | 技术 | 版本约束 |
|----|------|----------|
| 前端 | Streamlit | >=1.30 |
| 后端 | Python 3.11+ | — |
| 关系库 | SQLite (via SQLAlchemy 2.x) | — |
| 向量库 | ChromaDB | >=0.4 |
| Embedding | sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` | 支持中文 |
| LLM | DeepSeek API (`deepseek-chat`) | OpenAI-compatible |
| 文档解析 | pdfplumber / python-docx / python-pptx / 自带 csv,json | — |
| 中文分词 | jieba | — |

**禁止引入**：FastAPI、Flask、Vue、React、其它向量库、其它 LLM SDK。

---

## 4. 目标目录结构（冻结）

```
NotebookMH/
├── app.py                      # 入口，3 栏布局
├── config.py                   # 路径/模型名/常量
├── .env                        # API Key（用户自填）
├── .env.example                # 模板
├── .streamlit/config.toml      # 主题
├── requirements.txt
├── README.md
├── BUILD_PLAN.md               # 工程计划（本系列）
├── PROGRESS.md                 # 执行进度
├── ARCHITECTURE.md             # 本文件
│
├── core/
│   ├── __init__.py
│   ├── db.py                   # SQLAlchemy ORM + DBManager 单例
│   ├── vector_store.py         # ChromaDB 包装
│   ├── ingest.py               # 解析+chunk+embed 入库
│   ├── parsers.py              # 各格式文件解析
│   ├── rag.py                  # 混合检索 (BM25 + dense + RRF)
│   ├── llm.py                  # DeepSeek 客户端
│   ├── chat.py                 # 对话编排（RAG → LLM → 引用）
│   └── studio.py               # Studio 内容生成
│
├── ui/
│   ├── __init__.py
│   ├── sidebar.py              # 用户 + Vault + 来源 + 上传
│   ├── chat_panel.py           # 中间对话栏
│   ├── studio_panel.py         # 右侧 Studio
│   └── components.py           # 复用 UI 片段
│
├── data/                       # 运行时数据（gitignore）
│   ├── sys.db
│   ├── chroma_db/
│   └── uploads/
│
└── archive_legacy/             # Step 0 备份的旧代码
```

**目录不在清单外的文件一律不准创建**。

---

## 5. 数据库 Schema（冻结）

仅保留以下 8 张表。其余全部删除。

```sql
vault_registry      (id, vault_uuid, user_id, vault_name, created_at)
document_registry   (id, vault_uuid, file_name, content_hash, doc_size, page_count,
                     source_type, source_url, summary, key_topics, suggested_questions,
                     full_text, created_at)
chunk_registry      (id, vault_uuid, doc_hash, chunk_index, chunk_text,
                     source_page, header_hierarchy, chunk_size, created_at)
chat_history        (id, vault_uuid, user_id, role, content, citations, created_at)
note_registry       (id, vault_uuid, user_id, title, content, pinned, tags, created_at)
flashcard_registry  (id, vault_uuid, question, answer, mastery, review_count, created_at)
quiz_history        (id, vault_uuid, question, options, correct, explanation,
                     user_answer, is_correct, created_at)
wrong_answer_registry (id, vault_uuid, question, user_answer, correct_answer,
                       explanation, mastered, created_at)
```

**删除以下表**：`user_stats`、`concept_mastery`、`interaction_logs`、`concept_dependencies`。

---

## 6. 核心模块接口（冻结）

任何模块只准暴露下表列出的函数/类。其余全部 `_` 前缀私有。

### `core/db.py`
```python
class DBManager:
    # Vault
    def list_vaults(user_id: str) -> list[Vault]
    def create_vault(user_id: str, name: str) -> str  # 返回 uuid
    def delete_vault(vault_uuid: str) -> None
    # Document
    def list_documents(vault_uuid: str) -> list[Document]
    def register_document(...) -> int
    def delete_document(vault_uuid: str, content_hash: str) -> None
    def document_exists(vault_uuid: str, content_hash: str) -> bool
    # Chunk
    def register_chunks(vault_uuid: str, doc_hash: str, chunks: list[dict]) -> None
    def get_chunks(vault_uuid: str, doc_hash: str) -> list[Chunk]
    # Chat
    def save_chat(vault_uuid: str, user_id: str, role: str, content: str, citations: list) -> None
    def load_chat(vault_uuid: str, user_id: str, limit: int = 50) -> list[ChatMsg]
    def clear_chat(vault_uuid: str, user_id: str) -> None
    # Note / Flashcard / Quiz / WrongAnswer  ← 各 CRUD（见 db.py 实现）

db_manager: DBManager  # 模块级单例
```

### `core/llm.py`
```python
class LLMClient:
    async def chat(prompt: str, system: str = "", history: list = None, temperature: float = 0.7) -> str
    async def chat_stream(prompt: str, system: str = "", history: list = None, temperature: float = 0.7) -> AsyncIterator[str]
    async def chat_json(prompt: str, system: str = "", temperature: float = 0.3) -> dict

llm: LLMClient  # 模块级单例
```

### `core/rag.py`
```python
async def retrieve(query: str, vault_uuid: str, top_k: int = 5,
                   source_hashes: list[str] | None = None) -> list[Chunk]
```

### `core/chat.py`
```python
async def answer(query: str, vault_uuid: str, user_id: str,
                 history: list, source_hashes: list[str] | None) -> AsyncIterator[dict]
# yield {"type": "delta", "text": "..."} | {"type": "citations", "data": [...]} | {"type": "done"}
```

### `core/studio.py`
```python
async def generate_summary(vault_uuid: str) -> str
async def generate_faq(vault_uuid: str) -> str
async def generate_study_guide(vault_uuid: str) -> str
async def generate_briefing(vault_uuid: str) -> str
async def generate_timeline(vault_uuid: str) -> str
async def generate_mindmap(vault_uuid: str) -> str  # 返回 mermaid 代码
async def generate_flashcards(vault_uuid: str, count: int = 10) -> list[dict]
async def generate_quiz(vault_uuid: str, count: int = 5) -> list[dict]
```

### `core/ingest.py`
```python
async def ingest_file(vault_uuid: str, file_name: str, file_bytes: bytes) -> dict
async def ingest_url(vault_uuid: str, url: str) -> dict
async def ingest_text(vault_uuid: str, title: str, text: str) -> dict
# 返回 {"status": "ok"|"duplicate"|"error", "doc_hash": str, "chunks": int, "msg": str}
```

---

## 7. UI 布局（冻结）

```
┌──────────────────────────────────────────────────────────────┐
│                        Top Bar (logo + 库名)                  │
├─────────┬────────────────────────────────────┬───────────────┤
│ Sidebar │            Chat Panel              │ Studio Panel  │
│         │                                    │               │
│ 用户名   │  消息流（用户气泡 / AI 气泡 +     │  [摘要]       │
│ ───     │   引用 [1][2] 可点击）              │  [FAQ]        │
│ 笔记库   │                                    │  [学习指南]    │
│ ───     │                                    │  [简报]       │
│ 来源列表 │                                    │  [时间线]      │
│ ───     │                                    │  [思维导图]    │
│ 上传区   │                                    │  [闪卡]       │
│         │                                    │  [测验]       │
│         │                                    │  ───          │
│         │  [输入框 + 提交]                    │  我的笔记      │
└─────────┴────────────────────────────────────┴───────────────┘
```

宽度比例：`sidebar 自动 | chat 5 | studio 3`

---

## 8. 执行纪律（DeepSeek V4 必须遵守）

### 死亡禁令（违反即任务失败）
1. ❌ 不准创建本文档"目录结构"之外的文件
2. ❌ 不准引入新的依赖库（除 requirements.txt 已列）
3. ❌ 不准引入新概念（"神经/全息/认知/守护/沙箱"等一律禁用）
4. ❌ 不准在 PROGRESS.md 写"完成"但未真正运行验收
5. ❌ 不准跳步（必须按 Step N → N+1 顺序）
6. ❌ 不准修改 BUILD_PLAN.md / ARCHITECTURE.md（仅可建议给用户）
7. ❌ 不准使用 mock 数据骗过验收（必须真实端到端）

### 强制三件物（每步完成必须）
1. 实际代码改动（具体到文件和函数）
2. 一条人工/自动验证操作（精确到操作步骤）
3. PROGRESS.md 追加一行：`[Step N] ✅/❌ 标题 | 验证结果摘要 | 文件路径`

### 三振机制（防止硬干）
- 同一 Step 连续 3 次验收失败 → 在 PROGRESS.md 写 `BLOCKED: <原因>` → 停止，等待用户介入

### 每 5 步锚点
- Step 5/10/15/20/25/30/35/40 完成后，**必须**：
  1. 重读 ARCHITECTURE.md
  2. 重读最近 5 步的 PROGRESS.md
  3. 在 PROGRESS.md 写 `[Checkpoint N] 当前实现 vs 架构 差异审计：...`
  4. 若发现偏离 → 立即修正再进入下一步

---

## 9. 验收方式约定

| 类型 | 操作 | 通过标准 |
|------|------|----------|
| 启动验收 | `streamlit run app.py --server.headless true` | 终端无 Traceback，浏览器加载成功 |
| UI 验收 | 浏览器手动操作 | 按指定步骤操作能看到指定元素 |
| 数据验收 | `sqlite3 data/sys.db "SELECT ..."` | 查询返回预期行 |
| 端到端验收 | 完整流程跑一遍 | 各环节按预期返回 |

每个 Step 的"验收"段落给出**确切操作命令**，DeepSeek 必须**真的执行**并把输出贴到 PROGRESS.md。

---

**本文档结束。任何修改需经用户书面确认。**
