#!/bin/sh
BASE=/mnt/sda4/tvbox
LOG=$BASE/run.log
cd "$BASE" || exit 1
echo "[$(date '+%F %T')] ===== start =====" >> "$LOG"

# 1) 拉最新站点池（失败则用本地缓存）
if python3 scripts/fetch_pool.py >> "$LOG" 2>&1; then
    echo "  pool fetched" >> "$LOG"
else
    echo "  pool fetch failed, using cached" >> "$LOG"
fi

# 2) 国内网络实测每个站点能否出流
python3 scripts/verify_play.py --pool cms_pool.json --workers 8 >> "$LOG" 2>&1

# 3) 编译成 TVBox 配置
python3 scripts/build_pool_config.py >> "$LOG" 2>&1

# 4) 发布到 web 目录
mkdir -p /www/tvbox
if [ -f dist/official.json ]; then
    cp dist/official.json /www/tvbox/official.json
    echo "  published -> /www/tvbox/official.json" >> "$LOG"
fi
echo "[$(date '+%F %T')] ===== done =====" >> "$LOG"
