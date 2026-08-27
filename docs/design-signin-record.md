# 雨云自动签到 · 分批执行 + 飞书数据记录 设计方案

> 状态：**设计定稿；方案改动（飞书多维表格记录 + 分批执行）均未落地。项目主体（签到 + 通知 + GitHub Actions）已可正常运行。**
> 创建日期：2026-08-27
> 最后同步：2026-08-27（对照 `rainyun.py` v2.6 / `rainyun-sign.yml` / `notify.py` 实际代码）
> 本文档用于记录方案与后续决策，方便回溯。

---

## 〇、现状同步（2026-08-27 · 代码核对）

> 本节为设计定稿后与真实代码的对照，确认哪些做了、哪些还没做。

| # | 设计项 | 现状 | 依据 |
|---|------|------|------|
| 1 | 签到主流程（登录 / 验证码 / 签到 / 读取积分） | ✅ 已实现 | `rainyun.py` 标 `ver = "2.6 (ICR + Cookie)"`，ICR 模块 + Cookie 缓存 + 指纹注入完整 |
| 2 | 通知推送（含飞书机器人 FSKEY） | ✅ 已实现 | `notify.py` 支持 FSKEY / Push+ / SMTP / Bark / 钉钉 / TG / Server酱 等 7+ 渠道 |
| 3 | GitHub Actions 自动运行 | ✅ 已实现 | `.github/workflows/rainyun-sign.yml`，单 cron `0 2 * * *`（UTC）= 北京时间 10:00，含 Cookie 缓存与 keepalive |
| 4 | 飞书多维表格记录 `ledger.py` | ❌ 未实现 | 仓库内无 `ledger.py` 文件，无任何调用 |
| 5 | `rainyun.py` 集成记账 | ❌ 未实现 | `run_checkin()` 返回的 `result` 仅用于通知，未触发表格写入 |
| 6 | 分批执行（`RAINYUN_BATCH` / `RAINYUN_BATCH_SIZE` 切片） | ❌ 未实现 | `parse_accounts()` 仅做用户名/密码解析，无切片逻辑 |
| 7 | 工作流分批定时（多 cron） | ❌ 未实现 | 仍为单 cron，未拆批 |

### 已知不一致（待处理）

1. **版本号错位**：`README.md` 版本历史停在 v2.5（2026-02-23），但 `rainyun.py` 代码已标 v2.6。建议补一版 v2.6 说明（ICR 模块替代 ddddocr、Cookie 缓存等）。
2. **运行时间基准**：设计第四节待选项列的是 12:00 / 14:00 / 16:00 / 18:00，但当前真实运行是**北京时间 10:00 单次**。将来分批时注意以哪个时间为准。
3. **账号清单**：第七节列出的 40 账号划分仅为记录，完整用户名/密码只存于 GitHub Secrets，仓库内不保存（安全约束）。第一批仍缺第 10 个账号，待 Secrets 补全后核对。

### 下一步（解锁阻塞后执行）

- 待第四节三项（每批数量 / 执行时间 / 当日新增列）确认 → 再写 `ledger.py` + 改 `rainyun.py` + 改 `rainyun-sign.yml`（对应设计第五节）。
- 当前无需改动代码即可保持每日签到运行。

---

## 一、背景与问题

1. **卡住风险**：本项目一次运行全部账号时，存在执行过多导致卡住的风险（已实际验证）。因此需要**分批执行**，每批只跑一部分账号（8 或 10 个一组）。
2. **数据无法追溯**：现有机制是每次运行通过 `notify.py` 推送一条通知（Push+ / SMTP / Bark 等），属于"推送即焚"，无法直观查看**每天每个账号新增了多少积分**，历史数据难以统计。

## 二、需求确认

| # | 需求 | 结论 |
|---|------|------|
| 1 | 数据记录方式 | **只用飞书多维表格（Base）**，仓库 CSV 不做 |
| 2 | 积分口径 | 不搞签到前/后差值；**每次签到后把最新积分直接写入表格**即可 |
| 3 | 分批 / 定时 | **暂不改动**，由用户后续统一决定 |
| 4 | 通知推送 | 保持原有 notify 推送不变，作为每日简报；历史详情以飞书表为准 |

## 三、飞书表格设计（初稿）

表名：**雨云签到记录**

| 字段 | 类型 | 说明 |
|------|------|------|
| 记录时间 | 日期时间 | 写入时自动带上 |
| 日期 | 日期 | 签到当天 |
| 账号 | 文本 | 雨云用户名 |
| 批次 | 数字 | 预留字段，分批方案确定后填写 |
| 最新积分 | 数字 | 签到后的当前积分 |
| 状态 | 单选 | 签到成功 / 今日已签到 / 失败 |
| 备注 | 文本 | 失败原因等 |

> 可选增强（待用户决定）：加一列"当日新增"公式 = 今日最新积分 − 昨日最新积分，可在表格里直接看每天新增。

## 四、待决定事项（阻塞实施）

| # | 事项 | 待选项 | 状态 |
|---|------|--------|------|
| 1 | 每批账号数 | 10 个（4 批，正好对应现有第一~四批）/ 8 个（5 批） | 待定 |
| 2 | 每天执行时间与次数 | 例如 12:00 / 14:00 / 16:00 / 18:00 等 | 待定 |
| 3 | 是否加"当日新增"公式列 | 是 / 否 | 待定 |

## 五、实施方案（确认后执行）

### 改动清单

| 位置 | 改动 |
|------|------|
| 飞书侧 | 建表 + 建字段 + 授权（可用 lark-base 能力完成） |
| 新增 `ledger.py` | 调飞书 OpenAPI 往表里追加一行（`requests` 即可，GitHub Actions 中也可运行） |
| `rainyun.py` | 签到成功后调用 ledger 记录（约 10 行改动） |
| `rainyun-sign.yml` | 增加飞书 App 的 Secret 引用 |

### 分批执行设计（预留，未实施）

- 账号列表仍统一放在 GitHub Secrets `RAINYUN_USER` / `RAINYUN_PASS`（多行）。
- `rainyun.py` 的 `parse_accounts()` 增加环境变量切片：
  - `RAINYUN_BATCH`：第几批（从 0 开始）
  - `RAINYUN_BATCH_SIZE`：每批数量（默认 10）
  - `accounts = accounts[batch*size : (batch+1)*size]`
- 工作流改为多个 cron 定时器，每个对应一批；保留 `workflow_dispatch` 手动触发。

### GitHub Secrets 规划

| Secret | 说明 |
|--------|------|
| `RAINYUN_USER` | 全部账号用户名（多行，每行一个） |
| `RAINYUN_PASS` | 全部账号密码（多行，与用户名一一对应） |
| `LARK_APP_ID` | 飞书自建应用 App ID |
| `LARK_APP_SECRET` | 飞书自建应用 App Secret |
| `APP_TOKEN` | 飞书多维表格应用 token |
| `TABLE_ID` | 飞书多维表格数据表 id |

## 六、安全注意事项

- **账号密码一律不写入本仓库 / 本文档**，只存在 GitHub Secrets 中（`RAINYUN_USER` / `RAINYUN_PASS`，多行格式，行数需一一对应）。
- 本仓库为公开仓库（README 指向 github.com/chizw/Rainyun-Qiandao），任何敏感信息（密码、token）严禁提交。
- 飞书 App Secret、表格 token 同理只走 Secrets。

## 七、账号批次说明（仅记录用户名，不含密码）

共 40 个账号，当前按 10 个一批分为 4 批：

- **第一批**：liveou、liyijiang6、hebaiju、wddwwb、wbix、qsb、wblsyx、wangtaotao、pengyuhan（9 个）+ 第 10 个
- **第二批**：sand0tree、dawn8desk、dawn7floor、lake3door、river1clock、breeze1rain、dawn6mist、door8snow、cloud8desk、lamp9dawn（10 个）
- **第三批**：grass8rock、hill4river、pen1mist、sand3cloud、wind6rain、dusk3clock、wave4floor、river7book、dawn4floor、door7mist（10 个）
- **第四批**：river6wind、lake9clock、dawn0lamp、stone3stone、dawn0mist、cup8pen、leaf2dusk、desk3chair、river5dusk、rock0wave（10 个）

> 注意：第一批实际列出的用户名有 9 个（liveou ~ pengyuhan），数量与"每批 10 个"的划分存在出入，且第四批最后 `rock0wave` 的密码在原始记录中显示被截断。最终以 GitHub Secrets 中的完整列表为准。

## 八、决策记录（Decision Log）

| 日期 | 决策 | 备注 |
|------|------|------|
| 2026-08-27 | 数据记录只用飞书多维表格 | 仓库 CSV 不做 |
| 2026-08-27 | 积分口径 = 写最新积分 | 不做签到前后差值 |
| 2026-08-27 | 分批 / 定时暂不改动 | 等用户统一决定后再实施 |
| 2026-08-27 | 暂不动手实施 | 先等分批方案确认 |
| 2026-08-27 | 现状同步：方案改动均未落地 | 代码核对：签到/通知/Actions 已可用；ledger.py、分批、定时切片均缺失 |
| 2026-08-27 | 发现版本号错位（README v2.5 vs 代码 v2.6） | 待补 README v2.6 说明 |
