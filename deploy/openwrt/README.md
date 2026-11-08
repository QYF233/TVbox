# OpenWrt 独立部署

在路由器上跑，用**国内 IP** 做播放验证，结果比 GitHub Actions（海外）准确。
产出的配置放在 `/www/tvbox/`，局域网 TVBox 直接填地址即可。

## 原理

```
每小时/6小时 cron
   ↓
fetch_pool.py      经 gh-proxy 拉取仓库里的 cms_pool.json
   ↓
verify_play.py     国内网络实测每个站能不能真出流（列表→详情→m3u8）
   ↓
build_pool_config.py  按评分排序，编译成 official.json
   ↓
/www/tvbox/official.json   局域网 HTTP 可访问
```

## 部署

```sh
# 1) 建目录
mkdir -p /mnt/sda4/tvbox/scripts /mnt/sda4/tvbox/dist /www/tvbox

# 2) 上传脚本（在 PC 侧用 pscp/scp）
#    scripts/validate.py
#    scripts/verify_play.py
#    scripts/fetch_pool.py
#    scripts/build_pool_config.py
#    scripts/blocklist.txt
#    cms_pool.json
#    deploy/openwrt/run.sh  →  /mnt/sda4/tvbox/run.sh

# 3) 加定时任务（每 6 小时）
chmod +x /mnt/sda4/tvbox/run.sh
(crontab -l 2>/dev/null; echo '0 */6 * * * /bin/sh /mnt/sda4/tvbox/run.sh >/dev/null 2>&1') | crontab -
/etc/init.d/cron reload
```

## 使用

局域网地址：

```
http://10.0.0.1/tvbox/official.json
```

填进 TVBox 的「配置地址」。

## 排障

```sh
tail -30 /mnt/sda4/tvbox/run.log     # 最近一次运行日志
ls -la /www/tvbox/                   # 产物
sh /mnt/sda4/tvbox/run.sh            # 手动跑一次
```

## 注意

- 宿主是 busybox ash，`set -e`、`$(date)` 可用，但**没有 `timeout`、没有 `pkill`**
- 脚本用 Python 3 标准库，无需 pip 安装
- `fetch_pool.py` 走 gh-proxy 镜像，因为 `raw.githubusercontent.com` 在国内不可达
- 拉取失败会沿用本地缓存的池子，不会中断
