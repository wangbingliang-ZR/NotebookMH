# BUILD_PLAN.md — NotebookMH 工程执行总纲（v1.0）

> **执行者**: DeepSeek V4
> **指挥官**: Cascade
> **验收人**: 用户
> **总步数**: 42 步，分 6 阶段

---

## 0. 必读文档（执行任何 Step 前）

1. `ARCHITECTURE.md` — **架构冻结**（最高约束，不可违反）
2. `BUILD_PLAN.md` — 本文件（执行总纲）
3. `plans/phase_X_*.md` — 当前阶段的详细步骤
4. `PROGRESS.md` — 你的执行记录（每步追加）

---

## 1. 阶段索引

| 阶段 | 步骤 | 主题 | 详细文档 |
|------|------|------|----------|
| 0 | 0-3 | 范围冻结 + 配置 | `plans/phase_0_setup.md` |
| A | 4-9 | 地基（DB / 启动 / 侧栏 / Vault） | `plans/phase_a_foundation.md` |
| B | 10-17 | 上传链路 | `plans/phase_b_ingest.md` |
| C | 18-24 | 对话链路 | `plans/phase_c_chat.md` |
| D | 25-32 | Studio 生成 | `plans/phase_d_studio.md` |
| E | 33-40 | 体验打磨 | `plans/phase_e_polish.md` |
| F | 41-42 | 终验 | `plans/phase_f_final.md` |

---

## 2. 执行规则（铁律）

### 顺序与节奏
- **必须按 Step 0 → 42 严格顺序**，不准跳步、不准并行。
- 每步完成后必须**真实运行验收命令**，输出贴到 `PROGRESS.md`。
- 验收不通过 → 修正同一步，**不准前进**。

### 三振机制（防止硬干）
- 同一 Step 连续 3 次验收失败 → 在 `PROGRESS.md` 写：
  ```
  [Step N] BLOCKED: <具体原因>
  - 尝试 1: <方案> | 失败原因: <详情>
  - 尝试 2: <方案> | 失败原因: <详情>
  - 尝试 3: <方案> | 失败原因: <详情>
  - 需要用户决定: <选项 A / 选项 B>
  ```
- **停止执行**，等待用户介入。不准硬干。

### 每 5 步锚点（防止跑偏）
- 完成 **Step 5 / 10 / 15 / 20 / 25 / 30 / 35 / 40** 后**必须**：
  1. 重读 `ARCHITECTURE.md` 全文
  2. 重读最近 5 步的 `PROGRESS.md`
  3. 在 `PROGRESS.md` 追加：
     ```
     [Checkpoint N] @ <时间戳>
     - 架构对齐：目录结构 = ARCHITECTURE 第 4 节？✅/❌
     - DB schema = ARCHITECTURE 第 5 节？✅/❌
     - 接口签名 = ARCHITECTURE 第 6 节？✅/❌
     - 偏离项：<列出，或写"无">
     - 修正动作：<列出，或写"无">
     ```
  4. 若有偏离 → 先修正再进入下一步。

### 每步三件物（缺一不可）
1. **代码改动**：具体到文件和函数
2. **验证操作**：精确到"运行什么命令"或"点击哪个按钮看到什么"
3. **PROGRESS.md 记录**：格式见下文

### PROGRESS.md 单步记录格式
```
[Step N] ✅ <步骤标题>
- 改动文件: file1.py, file2.py
- 验证命令: <粘贴实际运行的命令>
- 验证输出: <粘贴关键输出片段>
- 用时: <分钟>
```

或失败时：
```
[Step N] ❌ <步骤标题>
- 改动文件: ...
- 失败原因: <traceback 或现象>
- 修正方案: <下一次尝试的方案>
```

---

## 3. 死亡禁令（违反 = 任务作废）

1. ❌ 不准创建 `ARCHITECTURE.md` 第 4 节"目录结构"之外的文件
2. ❌ 不准引入新依赖（除 `requirements.txt` 已列）
3. ❌ 不准引入新概念（"神经/全息/认知/守护/沙箱/苏格拉底/MAB/UCB1/进化"等一律禁用）
4. ❌ 不准在 `PROGRESS.md` 写"完成"但未真正运行验收
5. ❌ 不准跳步
6. ❌ 不准修改 `BUILD_PLAN.md` / `ARCHITECTURE.md`（仅可在 PROGRESS.md 提建议给用户）
7. ❌ 不准用 mock 数据骗过验收（必须真实端到端）
8. ❌ 不准擅自加功能（"灵机一动"必须写入 PROGRESS.md 等用户拍板）

---

## 4. 工作目录

`c:\大饼的ai助手\zijiannotebookdb\NotebookMH`

所有相对路径以此为根。

---

## 5. 开始执行

1. 阅读 `ARCHITECTURE.md`
2. 阅读 `plans/phase_0_setup.md`
3. 执行 Step 0
4. 在 `PROGRESS.md` 记录
5. 阅读下一步……

**开工。**
