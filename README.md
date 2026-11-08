# TVbox — TVBox 接口汇总

**Languages:** **简体中文** | [English](README.en.md) | [繁體中文](README.zh-TW.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

> 官网：**[tvbox.org](https://www.tvbox.org/)**  
> 本仓库由 [TVboxorg](https://github.com/TVboxorg) 维护，用于收集、整理并定期探测可用的 TVBox 接口地址。

## 官网

- 网站首页：<https://www.tvbox.org/>
- 接口页：<https://www.tvbox.org/portal.php>
- 盒子软件与下载：<https://www.tvbox.org/>

请优先通过官网获取软件与说明；本仓库专注于**接口清单与可用性探测**。

## 订阅地址（可直接填入 TVBox）

| 用途 | 地址 | 填哪里 |
| --- | --- | --- |
| **单仓聚合（推荐直用）** | `https://raw.githubusercontent.com/TVboxorg/TVbox/main/dist/official.json` | 「配置地址 / 接口」 |
| 多仓列表 | `https://raw.githubusercontent.com/TVboxorg/TVbox/main/dist/tvbox.json` | 「多仓 / 仓库」 |
| 完整列表（含状态） | `https://raw.githubusercontent.com/TVboxorg/TVbox/main/dist/list.json` | 仅查看 |
| 可读状态表 | [`dist/status.md`](./dist/status.md) | 仅查看 |

`official.json` 会自动拉取探测可用的公开线路，跨源拼合 `sites`（标准 CMS 源直接合并；CSP 源尽量带上原线路 `jar`），生成一份可粘贴进 TVBox 的配置。

国内若 raw 较慢，可尝试镜像：

```text
https://cdn.jsdelivr.net/gh/TVboxorg/TVbox@main/dist/official.json
https://cdn.jsdelivr.net/gh/TVboxorg/TVbox@main/dist/tvbox.json
```

## 仓库内容

| 路径 | 说明 |
| --- | --- |
| [`sources.yaml`](./sources.yaml) | 人工维护的接口源（权威数据） |
| [`dist/`](./dist/) | 探测结果与生成的订阅文件（CI 定时更新） |
| [`dist/official.json`](./dist/official.json) | 跨线路聚合的单仓配置 |
| [`dist/history.json`](./dist/history.json) | 每次探测的历史记录与 7 日可用率 |
| [`dist/mirrors.json`](./dist/mirrors.json) | 各镜像通道的实测可达性 |
| [`docs/`](./docs/) | 可视化监控台（GitHub Pages） |
| [`scripts/validate.py`](./scripts/validate.py) | 配置与 jar 校验核心（零依赖，可单独引用） |
| [`scripts/probe.py`](./scripts/probe.py) | 并发探测脚本 |
| [`scripts/history.py`](./scripts/history.py) | 累积历史、计算连续可用次数与状态变更 |
| [`scripts/mirrors.py`](./scripts/mirrors.py) | 实测各镜像通道是否可达 |
| [`scripts/merge.py`](./scripts/merge.py) | 跨线路拼 sites → official.json |
| [`scripts/build.py`](./scripts/build.py) | 生成 list / tvbox / status 与页面数据 |
| [`scripts/notify.py`](./scripts/notify.py) | 状态变更告警 |

## 探测判定口径

判定规则对齐 TVBoxOSC 源码 `ApiConfig.parseJson` / `loadJar`，不做"能打开就算好"的弱判断。

**连通性与 UA**

- 先用 App 真实 UA `okhttp/3.15` 请求，失败再用浏览器 UA 复测一次
- 强制直连（绕过系统代理），与电视盒子的真实网络环境一致
- 中文域名自动转 punycode，中文路径做 percent-encode

**配置结构**

| 检查项 | 规则 |
| --- | --- |
| JSON 可解析 | 允许 `//` `/* */` 注释与尾逗号（Gson 宽容），允许前置说明文字 |
| `sites` 存在 | 取 `video.sites` 或 `sites`，必须是数组 |
| 站点字段完整 | 每项必须含 `key` / `type` / `api`，`type` 必须是数字；缺失在 App 侧会 NPE |
| 站点非空 | `sites` 为空数组合法，但无可用站点，判为不可用 |
| 多仓识别 | 存在 `urls` 键即为多仓，此时没有 `sites` 也算有效 |

**spider jar**

| 检查项 | 规则 |
| --- | --- |
| 可下载 | 直连可取到响应体 |
| 格式合法 | `PK` 头 + 能被 zipfile 解析，最好含 `.dex` |
| MD5 一致 | 若 `spider` 带 `;md5;` 声明，实测 MD5 必须完全一致 |
| 特殊前缀 | 支持 `img+`（Base64 藏在图片/文本里）与 `;md5;` 拆分 |
| 本地路径 | `assets://` `clan://` `file://` 直接判为 local，不做下载 |

**聚合逻辑**

`merge.py` 只合并 jar 探测通过的源的 `type=3` 站点。jar 挂掉的源，其爬虫站点依赖的 jar 必然不可用，直接剔除；这类源只保留不依赖 jar 的 CMS（`type=0/1/4`）站点。

**网盘站过滤**

默认剔除需要网盘会员才能播放的站点（115、夸克、阿里云盘、天翼、百度网盘、Alist、小雅等），这类站普通用户点进去必然失败。

识别依据：

| 位置 | 规则 |
| --- | --- |
| 站点名 | 含 `网盘 / 云盘 / 夸克 / 天翼 / 115 / Alist / 小雅 / 迅雷` |
| api | `csp_` 后含 `Pan / Quark / AList / AliYun / Uc / Baidu / Tianyi / 115 / Xiaoya`，排除 `PanConfig` 这类设置面板 |
| ext | 含 `quark.cn / aliyundrive / cloud.189 / 115.com / pan.baidu` 等网盘域名 |

想保留网盘站，设置环境变量 `KEEP_NETDISK=1` 即可。

## 聚合模式

默认 **纯净模式**（`ONLY_CMS=1`），产出的 `official.json` 只包含可验证的内容：

| 做法 | 说明 |
| --- | --- |
| 只留 `type=0/1/4` | 纯 HTTP 接口站，不依赖加密 jar |
| 逐个实测接口 | 请求 `?ac=videolist&pg=1`，**没有影片列表的直接剔除** |

好处是内容完全可验证——被采纳的每个站都能实际拉出影片列表，且绝不含网盘、Emby、WebDAV 这类需要额外账号的服务。

代价是只剩影视资源站，没有秒播 / 动漫 / 体育 / 听书 / 音乐这些分类。

想恢复混合模式（含 `csp_` 爬虫站），设置 `ONLY_CMS=0`。这类站点的逻辑在加密 jar 内，无法在本地判断内容来源，只能靠站点名与 api 命名做启发式过滤。

## 本地运行

```bash
python3 scripts/probe.py    # 探测 → dist/probe.json
python3 scripts/build.py    # 生成 list / tvbox / status
python3 scripts/merge.py    # 聚合 → dist/official.json
```

可调环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `PROBE_WORKERS` | `8` | 探测并发数 |
| `PROBE_RETRIES` | `1` | 失败重试次数 |

单个地址也能直接分析：

```bash
cd scripts && python3 -c "import validate;print(validate.analyze('https://example.com/tvbox.json'))"
```

## 可视化监控台

页面在 [`docs/index.html`](./docs/index.html)，数据由 `build.py` 输出到 `docs/data/dashboard.json`，纯静态、无外部依赖。

启用 GitHub Pages：

1. 仓库 **Settings → Pages**
2. Source 选 **Deploy from a branch**
3. Branch 选 **main**，目录选 **/docs**
4. 保存后访问 `https://<你的用户名>.github.io/TVbox/`

页面包含：指标卡、可用源趋势曲线、镜像地址（标出当前哪几个能打开，可一键复制）、源列表（按状态筛选、按延迟/可用率/站点数排序、点击展开详情）。

## 状态变更告警

只有在源发生 UP/DOWN 翻转时推送，平时静默。配置任意一个 Secret 即可启用：

| Secret | 说明 |
| --- | --- |
| `ALERT_WEBHOOK` | 通用 webhook，POST JSON `{"text": "..."}` |
| `SERVERCHAN_KEY` | Server 酱 SendKey |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram 机器人 |

可选仓库变量 `ALERT_ON=down`，则只推送掉线、不推送恢复。

## 历史与降级

- `history.json` 记录每个源最近 30 次探测结果，7 日可用率按最近 28 次统计
- `merge.py` 用「来源历史可用率 + 实测延迟」给站点打分，不再按名字里有没有「4K / 高清」这类词排序
- 聚合失败时不覆盖 `official.json`，改写 `dist/degraded.json` 记录原因，监控台顶部会显示黄色横幅


## 说明与免责

- 本仓库**只汇总第三方公开接口 URL**，并做连通性/格式探测，**不托管、不分发**具体影视或直播内容。
- 接口由第三方维护，可用性会变化；探测结果仅供参考。
- 请遵守当地法律法规与平台条款，合理使用。
- 软件下载、教程与社区请访问官网：[https://www.tvbox.org/](https://www.tvbox.org/)

## 贡献

1. 编辑 `sources.yaml` 增删接口（填写 `name` / `url` / `group` / `desc`）
2. 提交 PR，或在本仓库提 Issue
3. Actions 会定时探测并刷新 `dist/`

## License

文档与清单以收集整理为目的公开；第三方接口版权归原作者所有。
