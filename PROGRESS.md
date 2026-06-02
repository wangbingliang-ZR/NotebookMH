# Hiro AI / NotebookMH 项目进度记录

> 记录时间：2026-06-02 傍晚
> 状态：网站已就绪，等待服务器部署

---

## ✅ 今天已完成

### 1. GitHub 同步
- 本地代码库和 GitHub (`wangbingliang-ZR/NotebookMH`) 已同步
- 提交：`0d7da83` → `bfb9adc`

### 2. 公司网站创建
- 位置：`/website/`
- 文件：
  - `index.html` — 首页（公司介绍 + Hiro Lab 产品工坊）
  - `about.html` — 关于我们
  - `product-notebookmh.html` — 超级笔记本产品详情页
  - `css/style.css` — 统一样式（深蓝暗色主题）
- 品牌：Hiro AI / 河北春暖科春暖龙树科技有限公司
- 产品：超级笔记本（NotebookMH）已上线，AI 助手（开发中）

### 3. 部署脚本
- 位置：`/website/deploy.sh`
- 功能：一键在 Ubuntu 服务器上部署 NotebookMH
- 包含：代码拉取、虚拟环境、依赖安装、.env 配置、systemd 服务、Nginx 反向代理

### 4. 推送 GitHub
- `website/` 目录已提交并推送到 `master` 分支

---

## ⏳ 明天待办（优先级高）

### 任务 1：服务器部署 NotebookMH
**目标**：让 `notebook.hiroai.cn` 能打开超级笔记本

**步骤**：
1. SSH 登录 Ubuntu 服务器（`ssh root@服务器IP`）
2. 执行：
   ```bash
   cd /tmp
   curl -fsSL -o deploy.sh https://raw.githubusercontent.com/wangbingliang-ZR/NotebookMH/master/website/deploy.sh
   sudo bash deploy.sh
   ```
3. 腾讯云 DNSPod 添加解析：
   - 记录类型：`A`
   - 主机记录：`notebook`
   - 记录值：服务器公网 IP

**部署脚本说明**：
- 安装路径：`/opt/notebookmh`
- Streamlit 端口：`8501`（本地）
- Nginx 代理：`notebook.hiroai.cn → 127.0.0.1:8501`
- 服务名：`notebookmh`（systemd，开机自启）
- 日志查看：`journalctl -u notebookmh -f`

### 任务 2：更新主站静态文件
- 部署完成后，把 `website/` 文件上传到服务器 `/var/www/hiroai/`
- 确保 `www.hiroai.cn` 显示更新后的首页

### 任务 3：SSL 证书（可选）
- 用 Certbot 给 `notebook.hiroai.cn` 配置 HTTPS
- 命令：`sudo certbot --nginx -d notebook.hiroai.cn`

---

## 📋 已知信息汇总

| 项目 | 值 |
|---|---|
| 域名 | hiroai.cn |
| 子域名规划 | notebook.hiroai.cn → NotebookMH |
| 服务器 OS | Ubuntu 22.04.1 LTS |
| Python | 3.10.4 |
| Nginx | 1.18.0 |
| 内存 | 7.8GB |
| DNS | 腾讯云 DNSPod |
| 网站目录 | /var/www/hiroai |
| DeepSeek API Key | 已确认，脚本中已配置 |
| GitHub 仓库 | wangbingliang-ZR/NotebookMH |

---

## 🔗 相关文件

- 网站首页：`/website/index.html`
- 关于页面：`/website/about.html`
- 产品详情：`/website/product-notebookmh.html`
- 部署脚本：`/website/deploy.sh`
- 样式文件：`/website/css/style.css`

---

## ⚠️ 注意事项

1. **deploy.sh 脚本必须在 Linux 服务器上执行**，不是本地 Windows
2. DNS 解析生效可能需要 1-10 分钟
3. 首次运行 NotebookMH 会下载 embedding 模型（约 480MB），需联网
4. 服务器上已有 `hiroai-main` 和 `hiroai-studio` Nginx 站点，部署脚本会新增 `notebookmh` 站点
