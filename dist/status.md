# 接口探测状态

- 官网：https://www.tvbox.org/
- 仓库：https://github.com/TVboxorg/TVbox
- 生成时间（UTC）：`2026-11-08T05:07:14Z`
- 可用：**23** / 38
- spider 可用：**15**，MD5 不符：0，多仓：0
- 可用站点合计：**1484**

判定口径：先用 App 真实 UA `okhttp/3.15` 拉取；配置须能解析为 JSON 且 `sites` 内每项含 `key/type/api`；`spider` 非空时须可下载、是合法 zip、MD5 与 `;md5;` 声明一致。`urls` 存在按多仓处理。

| 状态 | 分组 | 名称 | 站点 | jar | 多仓 | 耗时 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| UP | pref | 王二小 | 100 | ok | - | 691ms | 混合线路，以网盘(4K)为主，适合网盘VIP用户 |
| UP | pref | 菜妮丝 | 37 | ok | - | 1489ms | 常规线路，推荐瓜子、金牌等线路 |
| UP | pref | 俊哥 | 24 | fail | - | 506ms | 常规线路 |
| UP | pref | 小盒子 | 54 | ok | - | 5954ms | 常规线路 |
| UP | back | 小盒子4K | - | none | - | 1098ms | 4K高清线路 |
| UP | back | 二月红接口 | 28 | ok | - | 688ms | 综合影视源 |
| UP | back | 王二小接口 | 63 | ok | - | 683ms | 王二小备用线路 |
| UP | back | 王二小放牛娃 | 63 | ok | - | 840ms | 王二小网盘备用源 |
| UP | back | 牛二 | 100 | ok | - | 355ms | 网盘4K混合线路 |
| UP | back | uuccc | 28 | ok | - | 1615ms | 通用影视线路 |
| UP | back | 新接口 | 63 | ok | - | 239ms | 全新综合聚合源 |
| UP | back | ok线路1 | 234 | fail | - | 531ms | 稳定通用影视源 |
| UP | back | 荐片 | 28 | fail | - | 3207ms | 荐片高清专用线路 |
| UP | back | my interface | 2 | ok | - | 75ms | 自建本地接口源 |
| UP | back | 1号VIP源 | 28 | ok | - | 812ms | VIP付费影视线路 |
| UP | back | 软件内置源 | 90 | ok | - | 74ms | 本地端口服务接口 |
| UP | back | ok线路2 | 1 | ok | - | 339ms | Gist托管备用源 |
| UP | back | 摸鱼儿 | 104 | ok | - | 194ms | 鱼影视专用线路 |
| UP | back | 牛儿 | 63 | ok | - | 214ms | 牛二同站备用wex源 |
| UP | back | 拾光 | - | none | - | 2185ms | SVIP高清影视托管源 |
| UP | back | 神秘大佬 | 157 | fail | - | 1333ms | Github加速聚合综合源 |
| UP | back | 潇洒Github备用 | 111 | fail | - | 2463ms | 潇洒线路镜像加速地址 |
| UP | back | 金鹰 | 106 | fail | - | 1172ms | 金鹰影视专用聚合线路 |
| DOWN | pref | 饭太硬 | - | none | - | 461ms | 混合线路，推荐荐片等线路 |
| DOWN | pref | 肥猫 | - | none | - | 3120ms | 混合线路，推荐肥猫、瓜子、金牌等线路 |
| DOWN | pref | 少儿频道 | - | none | - | 118ms | 常规线路，启蒙、少儿、小/初/高 |
| DOWN | pref | 4k云盘接口 | - | none | - | 44ms | 混合线路，可用性较差 |
| DOWN | pref | 无意云 | - | none | - | 34ms | 混合线路，若不用网盘的话可以选排序靠后的线路，画质较高 |
| DOWN | pref | 欧歌接口 | - | none | - | 120ms | 常规影视线路 |
| DOWN | back | 欧歌免费 | - | none | - | 79ms | 欧歌免费公用线路 |
| DOWN | back | 饭太硬 | - | none | - | 355ms | 混合线路，推荐荐片等线路 |
| DOWN | back | 潇洒 | - | none | - | 1266ms | 综合高清线路 |
| DOWN | back | fmys | - | none | - | 191ms | 综合聚合线路 |
| DOWN | back | 饭太硬备用 | - | none | - | 1370ms | 饭太硬备用访问地址 |
| DOWN | back | 11号托管源 | - | none | - | 259ms | Github静态加速源 |
| DOWN | back | sss公用源 | - | none | - | 479ms | 长期稳定通用线路 |
| DOWN | back | 小苹果线路 | - | none | - | 1377ms | Bitbucket托管苹果影视源 |
| DOWN | back | 66号GitCode源 | - | none | - | 289ms | 国内Gitee类静态影视接口 |
