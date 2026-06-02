# Phase F — 终验（Step 41-42）

> **执行前必读**: `ARCHITECTURE.md` + 全部 PROGRESS.md
> **本阶段目标**: 端到端跑通 + 完成 README + 最终验收

---

## Step 41：端到端完整流程（Smoke Test）

**目标**: 用全新数据库跑通 NotebookLM 等价的核心流程，全程不出错。

**操作**:
1. **清理环境**:
   ```powershell
   # 备份现有数据后删除
   Move-Item "data\sys.db" "data\sys.db.backup_$(Get-Date -Format yyyyMMdd)" -ErrorAction SilentlyContinue
   Remove-Item -Recurse -Force "data\chroma_db" -ErrorAction SilentlyContinue
   ```

2. **启动应用**:
   ```powershell
   streamlit run app.py --server.headless true
   ```

3. **按以下脚本严格执行**（每一步都要在 PROGRESS.md 记录"通过/失败"）:

| # | 操作 | 期望结果 |
|---|------|---------|
| 1 | 浏览器打开 http://localhost:8501 | 显示欢迎页 |
| 2 | 侧栏输入用户名 `e2e_user` | 顶部显示 `用户: e2e_user` |
| 3 | 新建笔记库 `测试库` | 下拉框出现该库 |
| 4 | 上传一个 PDF（≥3 页中文文档） | 成功摄入 N 个片段 |
| 5 | 上传一个 TXT（几段中文） | 成功摄入 |
| 6 | 抓取一个 URL（如 https://example.com） | 成功摄入 |
| 7 | 粘贴一段文本 | 成功摄入 |
| 8 | 顶部统计: 来源 4/50 | 数字正确 |
| 9 | 点击 PDF 来源 → 弹窗 | 显示片段 |
| 10 | 取消 URL 来源的勾选 | `已选 3 个源` |
| 11 | 对话: "总结一下这些资料的核心内容" | 流式回答，包含引用 [1] [2] |
| 12 | 引用展开 | 显示来源文件名和片段 |
| 13 | 第二轮对话: "刚才提到的第一点能详细解释吗" | AI 应理解上下文 |
| 14 | "保存为笔记" | 笔记区出现 |
| 15 | Studio 点"摘要" | 返回 200+ 字摘要 |
| 16 | 摘要"保存为笔记" | 笔记区 2 条 |
| 17 | Studio 点"思维导图" | 显示 Mermaid 图 |
| 18 | Studio 点"闪卡" | 返回 ≥5 张卡 |
| 19 | "保存到闪卡库" | 闪卡库出现 |
| 20 | 闪卡库展开任一卡 → 点"已掌握" | mastery 字段更新 |
| 21 | Studio 点"测验" | 返回 ≥3 题 |
| 22 | "加入测验库" | 测验库出现 |
| 23 | 答错 1 题 | 显示正确答案，错题本 +1 |
| 24 | 错题本展开 → 点"已掌握" | 错题本减少 |
| 25 | 笔记 → 导出 MD | 下载成功，文件可打开 |
| 26 | 笔记 → 导出 Word | 下载成功，Word 可打开 |
| 27 | 笔记 → 导出 PDF | 下载成功，PDF 中文不乱码 |
| 28 | 删除一条来源 → 顶部统计 -1 | 数字同步 |
| 29 | 清空对话 | 历史清空 |
| 30 | 浏览器刷新 → 重新进入 | 所有数据持久（库、来源、笔记、闪卡、错题） |
| 31 | 切换用户为 `another_user` | 看不到 e2e_user 的数据（隔离） |
| 32 | 切回 `e2e_user` | 数据回来 |

**任一步失败 → 不准过 Step 41**。修复后重跑该步。

**记录到 PROGRESS.md**: 把上表 32 行的"通过/失败"全部记录。

---

## Step 42：README + 最终验收 + 交付

**目标**: 写 README，对照 NotebookLM 12 项功能逐条打勾，向用户交付。

**操作**:

1. 编辑 `README.md`（完全替换）:
   ```markdown
   # NotebookMH

   中文版个人知识助手，对标 Google NotebookLM。

   ## 功能

   - ✅ 多用户切换 + 多笔记库
   - ✅ 9 种来源（PDF / DOCX / PPTX / TXT / MD / CSV / JSON / URL / 粘贴文本）
   - ✅ 智能对话（流式、多轮、带引用）
   - ✅ 来源筛选
   - ✅ Studio：摘要 / FAQ / 学习指南 / 简报 / 时间线 / 思维导图 / 闪卡 / 测验
   - ✅ 错题本 + 复习
   - ✅ 笔记保存 + 导出 MD/Word/PDF

   ## 安装

   ```bash
   pip install -r requirements.txt
   ```

   首次运行需联网下载 embedding 模型（约 480MB）。

   ## 配置

   复制 `.env.example` 为 `.env`，填入 DeepSeek API Key:
   ```
   DEEPSEEK_API_KEY=sk-xxx
   ```

   ## 启动

   ```bash
   streamlit run app.py
   ```

   浏览器自动打开 http://localhost:8501

   ## 技术栈

   - Streamlit + SQLAlchemy + ChromaDB + DeepSeek API
   - sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
   - jieba 中文分词 + BM25 + dense retrieval + RRF 融合

   ## 目录结构

   见 `ARCHITECTURE.md`。
   ```

2. **12 项功能对照打勾**: 在 PROGRESS.md 写最终验收报告:
   ```
   [Step 42] ✅ 最终验收
   - F1 多用户: ✅
   - F2 多笔记库: ✅
   - F3 多源上传: ✅
   - F4 解析+入库: ✅
   - F5 来源列表+详情+删除: ✅
   - F6 对话(引用+流式+多轮): ✅
   - F7 来源筛选: ✅
   - F8 Studio 摘要: ✅
   - F9 FAQ/学习指南/简报/时间线: ✅
   - F10 思维导图: ✅
   - F11 闪卡+测验+错题本: ✅
   - F12 笔记+导出: ✅
   ```

3. **清理临时文件**:
   ```powershell
   # 删除 streamlit 缓存（如有）
   Remove-Item -Recurse -Force ".streamlit\cache" -ErrorAction SilentlyContinue
   # 确认 archive_legacy 保留（不删）
   ```

4. **交付清单**:
   - 在 PROGRESS.md 末尾写:
     ```
     ## 项目交付
     - 完成时间: 2026-XX-XX
     - 总步数: 42 / 42
     - BLOCKED 数: <N>
     - 灵机一动条数: <N>（等待用户拍板）
     - 已知问题: <列出>
     - 建议后续: <列出，如 "音频概述功能、移动端 App、协作功能">
     ```

**验收**: 用户运行 README 中的命令能成功启动并跑通 Step 41 的 32 步流程。

---

## Step 42 完成

🎉 **项目交付完毕**。

通知用户验收。等待用户反馈，**不准擅自启动 Phase G 或新增功能**。

---

## 附录：常见问题排查清单（如终验失败可对照）

### 上传失败
- 检查 sentence-transformer 模型是否下载完成（首次约 480MB）
- 检查 `data/chroma_db` 目录权限
- 检查文件大小是否超 500MB
- 检查 `.streamlit/config.toml` 的 `maxUploadSize`

### 对话无响应
- 检查 `.env` 的 `DEEPSEEK_API_KEY` 是否生效
- 检查 LLM API 是否可访问（公司网络可能拦截）
- 检查 ChromaDB collection 是否存在
- 查看 streamlit 终端日志

### 引用为空
- 检查 retrieval 是否返回结果（`python -c "from core.rag import retrieve; ..."`）
- 检查 `source_hashes` 筛选是否过严

### Studio 生成报错
- 检查 LLM 返回是否 JSON 格式（mindmap/flashcards/quiz 需要）
- Mock 模式下 Studio 功能受限，正常

### 中文乱码
- 检查 `app.py` 是否注入 `<meta name="google" content="notranslate">`
- 检查 Chrome 翻译扩展是否关闭
- 检查 PDF 导出字体（Windows 路径 `C:/Windows/Fonts/simhei.ttf` 是否存在）

### 数据库迁移问题
- 删除 `data/sys.db` 重建（开发期可接受）
- 生产环境用 Alembic 迁移（本期不做）
