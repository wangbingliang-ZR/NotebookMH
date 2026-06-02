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

首次运行需联网下载 embedding 模型（约 480MB）。若网络受限，系统会自动降级为本地 HashingVectorizer（不影响接口）。

## 配置

复制 `.env.example` 为 `.env`，填入 DeepSeek API Key：

```
DEEPSEEK_API_KEY=sk-xxx
```

无 Key 时以 Mock 模式运行，可体验全部 UI 但 AI 返回固定提示文本。

## 启动

```bash
streamlit run app.py
```

浏览器自动打开 http://localhost:8501

## 技术栈

- Streamlit + SQLAlchemy + ChromaDB + DeepSeek API
- sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) 或 sklearn HashingVectorizer 降级
- jieba 中文分词 + BM25 + dense retrieval + RRF 融合

## 目录结构

见 `ARCHITECTURE.md`。

## 快速上手

1. 左侧输入用户名
2. 左侧新建笔记库
3. 左侧上传资料（文件/URL/粘贴文本）
4. 中间对话区提问
5. 右侧 Studio 生成摘要/闪卡/测验等
6. 顶部统计实时查看数据概况

## OCR 支持（扫描件 PDF）

对于扫描件/图片型 PDF，系统会自动尝试 OCR 识别。需要额外安装：

```bash
pip install pdf2image pytesseract pillow
```

**Windows 用户还需安装 Tesseract-OCR 引擎**：
1. 下载安装包：https://github.com/UB-Mannheim/tesseract/wiki
2. 安装时勾选中文语言包 `chi_sim`
3. 将安装目录（如 `C:\Program Files\Tesseract-OCR`）加入系统 PATH

**Linux/macOS**：
```bash
sudo apt install tesseract-ocr tesseract-ocr-chi-sim  # Debian/Ubuntu
brew install tesseract  # macOS
```

## 已知限制

- Mock 模式下 Studio 生成内容固定，配置 API Key 后启用真实生成
- Embedding 模型首次下载约 480MB，网络差时可自动降级本地向量器
- PDF 导出依赖 Windows 字体 `C:/Windows/Fonts/simhei.ttf`
- 移动端 < 1100px 时双栏自动堆叠为单栏

## License

MIT
