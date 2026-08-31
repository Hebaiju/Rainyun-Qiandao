# 部署指南（通用版）

把雨云自动签到跑在任意一台装了 Docker 的机器上。**不需要 AI，不需要克隆完整仓库，不需要本地构建**——官方镜像已自动发布到 GHCR，改代码推送到 main 分支后会自动重新构建。

唯一需要编辑的文件是 `config.py`：账号密码、飞书、PushPlus 全在里面，**不进镜像、不进 git**。

## 方式 A：拉取官方镜像（推荐，3 分钟）

```bash
# 1. 建目录，取部署所需的两个文件
mkdir -p ~/rainyun-qiandao/cookies && cd ~/rainyun-qiandao
curl -fsSLO https://raw.githubusercontent.com/Hebaiju/Rainyun-Qiandao/main/docker-compose.yml
curl -fsSLo config.py https://raw.githubusercontent.com/Hebaiju/Rainyun-Qiandao/main/config.example.py

# 2. 编辑 config.py：ACCOUNTS 填账号密码（分批）、LARK_* 飞书记账、PUSH_PLUS_TOKEN 推送
vi config.py

# 3. 跑一次验证（默认依次执行所有批次）
docker compose run --rm qiandao
```

首次运行后 `cookies/` 里会出现各账号的 cookie JSON，之后签到免登录。

## 每日定时（宿主机 crontab）

```bash
crontab -e
# 北京时间每天 12:00（若服务器是 UTC 时区则写 0 4；服务器是北京时间则写 0 12）
0 4 * * * cd /home/you/rainyun-qiandao && /usr/bin/docker compose run --rm qiandao >> cron.log 2>&1
```

## 方式 B：源码构建（想改代码时）

```bash
git clone https://github.com/Hebaiju/Rainyun-Qiandao.git
cd Rainyun-Qiandao
cp config.example.py config.py && vi config.py
# 取消 docker-compose.yml 里 "build: ." 的注释
docker compose build && docker compose run --rm qiandao
```

推送到 main 分支后，GitHub Actions 会自动构建并发布新的官方镜像。

## 日常操作

```bash
docker compose run --rm qiandao                      # 跑所有批次
docker compose run --rm qiandao python rainyun.py 0  # 只跑第 0 批
docker compose pull                                  # 升级到最新镜像
tail -f cron.log                                     # 看定时任务日志
```

## config.py 怎么写

参考 `config.example.py`，核心是 ACCOUNTS（二维列表，每个子列表为一批）：

```python
ACCOUNTS = [
    [("user1", "pass1"), ("user2", "pass2")],   # 第 0 批
    [("user3", "pass3")],                        # 第 1 批
]
PUSH_PLUS_TOKEN = "xxxx"       # 微信推送（可选）
LARK_APP_ID = "..."            # 飞书记账（可选，四项齐全才启用）
LARK_APP_SECRET = "..."
LARK_APP_TOKEN = "..."
LARK_TABLE_ID = "..."
```

只有一批就只写一个子列表。小内存服务器保持一批不超过 10~15 个账号、`MAX_WORKERS=1`。

## 环境变量（docker-compose.yml 的 environment 里调）

| 变量 | 默认 | 说明 |
|---|---|---|
| `MAX_WORKERS` | `1`（镜像内置） | 同批并发 Chrome 数。小内存保持 1 |
| `CHECKIN_MAX_RETRIES` | `2` | 失败重试次数 |
| `MAX_DELAY` | `15` | 相邻账号启动间隔上限（秒），随机 5~该值 |
| `DEBUG` | `false` | 调试日志 |
| `NOTIFY_ONLY_FAILURE` | `false` | 全部成功时不推送 |

## 内存与迁移

- `MAX_WORKERS=1` 时峰值约 400~600MB（单个 headless Chrome + OCR 模型）；1GB 空闲内存的服务器可稳定运行，更小内存请加 swap。
- **迁移**：cookie 文件名是账号名的哈希，与机器无关，把旧机器 `cookies/*.json` 拷到新机器即可继续免登录；或只带一个 `config.py` 去新机器重新登录。

## 服务器上的部署位置（本次已部署）

- 目录：`/opt/rainyun-qiandao`（compose + config.py + cookies/）
- 定时：`crontab -l` 查看，日志 `/opt/rainyun-qiandao/cron.log`
