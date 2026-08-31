# 雨云自动签到（Selenium + Chromium 无头浏览器）
# 基底必须是 Debian 系（ddddocr 依赖 onnxruntime，无 musl/Alpine wheel）
FROM python:3.11-slim-bookworm

# pip 源参数化：默认清华源（国内机器快）；海外 CI 可构建时传
# --build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# chromium / chromium-driver 来自同一 Debian 仓库，版本天然匹配，
# 且 chromium-driver 安装在 /usr/bin/chromedriver，正好命中 rainyun.py 的 Linux 分支。
# 中文字体用 wqy-microhei（约 2MB）而非 noto-cjk（约 200MB），渲染够用且镜像更小。
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium chromium-driver \
        fonts-liberation fonts-wqy-microhei \
        procps psmisc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --retries 5 -i "$PIP_INDEX_URL" -r requirements.txt

# 只复制运行必需的代码，绝不打入 config.py（含账号密码，运行时挂载）
COPY rainyun.py ICR.py ledger.py notify.py stealth.min.js config.example.py run_all.sh ./
RUN chmod +x run_all.sh && mkdir -p temp/cookies

# MAX_WORKERS=1 串行签到，适配小内存服务器（可被 compose environment 覆盖）
ENV LINUX_MODE=true \
    MAX_WORKERS=1 \
    PYTHONUNBUFFERED=1

CMD ["./run_all.sh"]
