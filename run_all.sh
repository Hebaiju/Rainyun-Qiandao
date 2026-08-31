#!/bin/sh
# 依次执行 config.ACCOUNTS 里的所有批次；单个批次失败不影响后续批次。
# 只想跑单批：docker compose run --rm qiandao python rainyun.py 0
BATCHES=$(python -c "import config; print(len(config.ACCOUNTS))" 2>/dev/null || echo 1)
echo "run_all: 检测到 $BATCHES 个批次"
i=0
fail=0
while [ "$i" -lt "$BATCHES" ]; do
  echo "run_all: ========== 批次 $i / $((BATCHES - 1)) =========="
  python rainyun.py "$i" || fail=1
  i=$((i + 1))
done
exit $fail
