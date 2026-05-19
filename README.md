# NotebookMH AI 学习系统

一个真正陪伴孩子和成人学习的 AI 工具，核心在于**教学内容**和**交互体验**，而非花哨技术。

## 项目概述

NotebookMH 是一个基于 FastAPI + SQLite + LLM 的苏格拉底式 AI 教学系统。它通过**启发型**或**严师型**两种教师人格，以提问引导代替直接灌输，帮助学习者自主探索知识。

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 后端框架 | FastAPI | 高性能异步 Web 框架 |
| 数据库 | SQLite + SQLAlchemy | WAL 模式保障并发安全 |
| 数据校验 | Pydantic V2 | 强类型边界校验 |
| AI 调用 | httpx + DeepSeek/OpenAI | 异步 HTTP 调用 |
| 前端 | 原生 HTML/CSS/JS | 轻量、快速加载 |

## 项目结构

```
notebookmh/
├── main.py              # FastAPI 主程序，/chat 等 API 接口
├── ai.py                # AI 模型调用封装，Mock 模式支持无 Key 测试
├── prompt.py            # 提示词模板（任务指令 + JSON 格式）
├── teacher_profiles.py  # 教师角色人格系统（启发型/严师型 + 动态切换）
├── memory.py            # 用户会话状态 + 情绪推断
├── database.py          # SQLite + SQLAlchemy ORM，WAL 模式
├── core/
│   └── llm_engine.py    # UnifiedNeuralCore 扩展抽象层
├── templates/
│   └── index.html       # 聊天界面
├── static/
│   ├── app.js           # 前端交互逻辑
│   └── style.css        # 温馨简洁 UI
├── data/                # SQLite 数据库目录（自动创建）
├── tests/               # 测试脚本
├── requirements.txt     # Python 依赖
└── .env.example         # 环境变量模板
```

## 核心流程

```
用户输入 → /chat → 设置 teacher_type + 推断 emotion
                    → generate_teacher_prompt() → system_prompt
                    → ask_model(user_prompt, system_prompt)
                    → AI 以对应人格回复 + 出题
用户答题 → /chat(answer_to_question) → 判断对错
                    → update_concept_mastery()
                    → 记录交互日志 → 生成反馈 + 下一题
思考空窗 → /proactive(轮询) → 触发温和提示/鼓励
```

## 教师角色系统

| 角色 | 风格 | 适用场景 |
|------|------|----------|
| 启发型（Socratic） | 温暖、鼓励、生活化类比 | 沮丧、困惑时 |
| 严师型（Strict） | 严格、要求高、强调理解 | 懒散、走神时 |
| 自适应（Auto） | 根据情绪自动切换 | 默认模式 |

两种角色均遵循：**绝不直接给答案、苏格拉底式提问、避免羞辱**。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 3. 启动服务

```bash
python main.py
```

访问 `http://localhost:8000` 即可使用。

### 无 API Key 测试（Mock 模式）

不配置 API Key 时，系统会自动进入 Mock 模式，返回预设的模拟数据，方便调试前端和数据库流程：

```bash
# 直接启动，无需配置 Key
python main.py
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 前端聊天页面 |
| `/chat` | POST | 核心对话接口（讲解/出题/判断） |
| `/proactive` | POST | 思考空窗主动提示 |
| `/stats` | GET | 用户学习进度统计 |
| `/switch_teacher` | POST | 手动切换教师角色 |
| `/health` | GET | 健康检查 |

### /chat 请求示例

```json
{
  "user_id": "user_abc123",
  "query": "什么是光合作用",
  "mode": "child",
  "teacher_type": "auto",
  "emotion_state": "",
  "answer_to_question": ""
}
```

### /stats 响应示例

```json
{
  "user_id": "user_abc123",
  "total_questions": 12,
  "correct_count": 8,
  "wrong_count": 4,
  "accuracy": 66.7,
  "concepts": [
    {"name": "光合作用", "mastery": 75.0, "status": "learning"}
  ],
  "current_teacher": "启发型·儿童",
  "emotion": "专注"
}
```

## 数据库模型

- **user_stats**: 用户累计答题数、正确率、策略权重
- **concept_mastery**: 每个知识点掌握度 (0-100)、状态 (learning/mastered/struggling)
- **interaction_logs**: 每次交互的详细记录，含认知负荷 c_load 和情感效价 e_valence

## 部署建议

- 生产环境使用 `gunicorn + uvicorn worker`
- Nginx 反向代理 + Let's Encrypt HTTPS
- 定期备份 `data/learning.db` 文件
- 环境变量中管理 API Key，切勿硬编码

## 扩展方向

- **语音交互**: 预留 WebSocket + STT/TTS 接口
- **3D 沙盒**: visual_engine/ 符号几何可视化
- **多用户并发**: 当前 SQLite WAL 可应对基本并发，用户量大时迁移 PostgreSQL
- **更精细的情绪识别**: 接入情感分析模型替代启发式推断

## License

MIT
