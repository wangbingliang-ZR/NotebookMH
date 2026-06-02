# NotebookMH 服务器部署 - 需要确认的信息

## 基本信息
1. **服务器操作系统**：Linux（CentOS/Ubuntu/Debian）还是 Windows Server？
2. **服务器架构**：x86_64（最常见）还是 ARM？
3. **是否有 root/管理员权限？**
4. **连接方式**：SSH（Linux）还是 远程桌面（Windows）？
5. **服务器配置**：CPU 几核？内存多大？（Streamlit 至少需 2G 内存）

## 已安装软件
6. **Python 是否已安装？** 版本多少？（运行 `python --version` 或 `python3 --version`）
7. **pip 是否可用？**
8. **Nginx 是否已安装？** 版本多少？（运行 `nginx -v`）
9. **Git 是否已安装？**（运行 `git --version`）
10. **是否安装了宝塔面板、PM2、Docker 等工具？**

## 域名与网络
11. **域名 hiroai.cn 的 DNS 管理在哪？**（阿里云/腾讯云/其他 DNS 服务商？）
12. **能否添加子域名解析？** 例如 `notebook.hiroai.cn` 指向服务器 IP
13. **服务器是否已有公网 IP？**
14. **服务器防火墙是否放行了 80/443 端口？**
15. **域名是否已配置 SSL 证书（HTTPS）？**

## 现有网站
16. **当前 hiroai.cn 的网站文件放在哪个目录？**（例如 `/var/www/html/`）
17. **当前网站是用什么部署的？**（Nginx 静态文件 / Apache / 宝塔面板 / 其他）
18. **当前 Nginx 配置文件位置？**（Linux 一般在 `/etc/nginx/nginx.conf` 或 `/etc/nginx/sites-available/`）
19. **能否直接修改 Nginx 配置添加反向代理？**

## 敏感信息
20. **服务器上是否有现成的 .env 文件或 API Key？**（部署时需要配置 DeepSeek API Key）
21. **是否需要我生成部署脚本，你在服务器上执行？** 还是你直接给我 SSH 访问权限？

---

**请把上述问题的答案整理后回复给我，我会立刻生成对应的部署脚本。**
