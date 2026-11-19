# Letterboxd 数据分析网站

为 `goorison` 持续维护的个人观影分析和电影发现工具，可公开分享给朋友。目标是补足 Letterboxd 会员统计没有提供的分析，理解观影偏好、观看语境和影评，并发现好作品和有价值的电影知识。

- 网站：https://gavinlegend.github.io/Letterboxd_Data_Update/
- 仓库：https://github.com/GavinLegend/Letterboxd_Data_Update
- Letterboxd 账号：https://letterboxd.com/goorison/
- Codex Project：`Letterboxd Data Website Maintenance`
- 本地维护目录：`/Users/gavin/Downloads/_Organized/11_Websites/02_Letterboxd_Data_Update`
- 接手规则：[AGENTS.md](AGENTS.md)

本文于 **2026-11-19** 根据历史聊天、Git 提交和当前代码整理。下文统计是本地检出的快照，不代表实时线上核验。

## 项目边界

本项目独立维护 Letterboxd 分析站。个人主站 `gavinlegend.com` 属于另一个仓库 `GavinLegend/gavinlegend-site`，其 Node 构建、Cloudflare Pages、域名和导航规则不适用于这里。

旧仓库 `GavinLegend/letterboxd-custom-report` 已于 2026-11-19 归档，旧 GitHub Pages 已关闭。不要再向旧站发布。当前代码仍保留 `custom-report` 文件名及 `Custom Research Desk` 页面标题，这是本项目的历史命名，不表示正在使用已归档仓库。

旧仓库和旧检出保存在相邻的 `../99_Archive/` 中。历史聊天中的 `Documents/...`、`outputs/.../share-site` 和 `/tmp/gavin-letterboxd-refresh` 是旧工作位置，后续以本目录为准。

## 网站结构和代码入口

这是 Python 生成的静态单页网站，没有 Node 应用构建、数据库或登录后台。主要 HTML、CSS、交互 JavaScript 和分析数据由生成器写入页面，图表使用 Plotly。近期动态单独加载 JSON。

| 文件或目录 | 用途 |
| --- | --- |
| `scripts/build_custom_letterboxd_report.py` | 核心生成器：数据合并、评分补充、推荐、tags、影评、片单分析，以及 `build_html()` 中的布局、翻译、图表和交互 |
| `scripts/analyze_letterboxd.py` | CSV、电影键、Letterboxd 元数据缓存及基础分析工具 |
| `scripts/sync_letterboxd_public.py` | 公开页面及 RSS 同步，生成兼容导出的 CSV 输入 |
| `scripts/refresh_recent_activity.py` | 单独拉取近期公开 RSS，生成 `recent-activity.json` |
| `scripts/prepare_account_export.py` | 筛选账号 ZIP 中当前使用的 CSV，精简 profile |
| `scripts/seed_metadata_cache_from_report.py` | 从上一版报告复用电影元数据 |
| `scripts/validate_report_data.py` | 检查数据覆盖、个人评分、年份和部分语言问题，输出完整缺失清单 |
| `scripts/check_report_coverage.py` | 防止较少记录的公开同步覆盖较完整快照 |
| `data/rating-seeds/` | 版本控制中的 Douban/IMDb 评分种子，避免临时缓存丢失后评分退化 |
| `.github/workflows/sync-letterboxd-public.yml` | 自动同步、校验、覆盖保护、提交和推送 |
| `index.html`、`custom-report-data.json` | 根目录已发布产物，必须保持一致 |
| `recent-activity.js`、`recent-activity.css`、`recent-activity.json` | 独立近期动态面板，标出完整分析日期 |
| `missing_data_report.md` | 当前完整快照的覆盖统计和逐条缺失原因 |
| `.nojekyll` | GitHub Pages 静态发布标记 |
| `.vendor/`、`data/public-sync/`、`outputs/` | 被 Git 忽略的依赖、输入和缓存、构建输出 |
| `tests/` | 公开同步和 RSS 相关回归测试 |

页面依次包含近期公开动态、Today's Taste Brief 和电影线索、已看影片豆瓣覆盖、Canada Streaming Availability、Recommendations Beyond Watchlist、Genre × Country / Region、Viewing Context Tags、Review Language Patterns、List Signals。

主要 JSON 分区为 `profile`、`metrics`、`genre_country`、`tags`、`reviews`、`lists`、`watched_douban`、`streaming`、`recommendations`、`daily_signal`、`custom_insights`。修改页面应改生成器，再重建产物，避免只改 `index.html` 后被下次同步覆盖。近期动态的独立 JS/CSS 直接维护根目录文件。

## 数据更新流程

### 1. 定时公开同步

工作流默认账号是 `goorison`，Python 版本为 3.11。

1. 恢复 `.vendor`、公开同步缓存和报告输出缓存。
2. 读取公开页面，更新 ratings、diary、reviews、tags、watchlist、profile 和 lists 等 CSV。
3. 遇到识别出的 Cloudflare challenge，脚本退出码为 `75`。工作流发出 warning，保留完整报告，继续尝试 RSS 更新。其他错误仍应失败，不能一概吞掉。
4. RSS 更新独立的 `recent-activity.json`。
5. 完整同步可用时，生成并校验候选报告。
6. 比较已看影片、观影事件、有标签事件、片单和影评数量。任一减少就保留旧快照。
7. 有变化才提交到 `main`。工作流带并发控制、缓存、rebase 和推送重试。

触发安排均为 **UTC**：

- `17 */6 * * *`：每天 00:17、06:17、12:17、18:17 增量同步，刷新最近 60 条详情页。
- `43 9 * * 0`：周日 09:43 强制刷新全部 diary/review 详情页。
- `workflow_dispatch`：可手动运行，默认仍为增量模式。
- 对工作流、`scripts/**`、README 或 `.gitignore` 的 push 也会触发。因此发布文档修改可能同时启动同步。

“周日全量”指公开条目详情，不等于完整账号导出，也不表示所有第三方评分和流媒体目录都已刷新。

**成功运行不等于数据全部最新。** 需分别检查 `custom-report-data.json.generated_at`、`recent-activity.json.latest_activity_at`、工作流 warning 和覆盖保护结果。RSS 只提供有限近期记录，不会自动合并进完整统计，也不能补齐大量历史补录。

### 2. 完整账号导出校准

公开页面长期受阻、历史缺口较大或用户有意删除记录时，用新的账号导出重建。ZIP、准备后的 CSV 和临时产物放在公开仓库之外。使用新的空输入目录，避免旧 `lists/*.csv` 残留。

`prepare_account_export.py` 复制 `watched.csv`、`ratings.csv`、`diary.csv`、`reviews.csv`、`watchlist.csv` 和 `lists/*.csv`，将 `profile.csv` 缩减到 Username。它不会自动判断每个片单或影评的公开权限，仍需检查可公开内容。

从仓库根目录执行，替换 `/private/path/...` 为本次指定路径：

```bash
python3 -m pip install --target .vendor pandas numpy lxml curl_cffi openpyxl
export PYTHONPATH="$PWD/.vendor${PYTHONPATH:+:$PYTHONPATH}"

python3 scripts/prepare_account_export.py \
  /private/path/letterboxd-export.zip /private/path/report-input
python3 scripts/seed_metadata_cache_from_report.py \
  --report custom-report-data.json \
  --input-dir /private/path/report-input \
  --output /private/path/report-output/film_metadata_cache.json
python3 scripts/build_custom_letterboxd_report.py \
  --input-dir /private/path/report-input \
  --output-dir /private/path/report-output \
  --streaming-lookups 0 --douban-lookups 0 \
  --watched-douban-lookups 0 --ptgen-detail-lookups 0 \
  --streaming-catalog-timeout 0
python3 scripts/validate_report_data.py \
  --input-dir /private/path/report-input \
  --report-json /private/path/report-output/share-site/custom-report-data.json \
  --index-html /private/path/report-output/share-site/index.html \
  --output /private/path/report-output/share-site/missing_data_report.md
python3 scripts/check_report_coverage.py \
  --existing custom-report-data.json \
  --candidate /private/path/report-output/share-site/custom-report-data.json
```

最后一条输出 `true` 表示候选数量减少，应先查明原因。真实删除需要以新导出确认，不能为了通过检查而保留应删除记录。

这组参数限制额外查询，但**不是完全离线构建**。缺失电影元数据、IMDb 或电影资讯等路径仍可能联网。`--streaming-catalog-timeout 0` 禁用新目录抓取，并复用输出目录或当前工作目录中的报告，所以应从仓库根目录运行。它不代表“无超时限制”。缓存目录越新，不代表流媒体可用性越新，必须检查来源和 fallback 信息。

校验后，只将 `share-site/index.html`、`share-site/custom-report-data.json`、`share-site/missing_data_report.md` 复制到仓库根目录，按需保留 `.nojekyll`。保留根目录 `recent-activity.*` 文件。不要用生成的 `share-site/README.md` 覆盖本维护文档，也不要整目录复制私人输入。

### 3. 本地公开同步与预览

`./scripts/run_public_sync.sh` 是早期一键脚本，需要 zsh。它安装依赖、同步、构建、校验，然后直接覆盖根目录报告。它目前**没有 CI 的覆盖数量保护、RSS 刷新或 challenge 后继续 RSS 的分支**。维护已有完整快照时，优先分步生成候选并运行上述覆盖检查，不要把它当作安全预览命令。

仅预览现有静态页面：

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

访问 `http://127.0.0.1:8000/`，用 HTTP 而不是 `file://`，确保近期动态 JSON 可加载。

## 重要产品和数据决定

- 分析应超出官方会员总览：国家/地区与类型交叉、reviews 文本、lists 标题表达的偏好、tags 语境，以及外部电影发现。
- 推荐不能只限 watchlist 或自建片单。允许用户按 watchlist、lists、平台、可看状态及类型包含/排除组合筛选。类型支持多选。
- 加拿大平台范围包括 Netflix、Crave、Amazon Prime、Criterion Channel、Apple TV+、Disney+、Crunchyroll。Criterion Channel 与已撤回的 Criterion on Demand 是不同服务。
- Criterion on Demand 因没有可用片库被撤回。Bilibili 流媒体目录因无法可靠合并电影条目被撤回，不恢复无效目录或 Bilibili 评分。用户原有 `bilibili` 观看标签仍是有效历史数据。
- 全部已看影片都应进入已看和流媒体总表，即使不在追踪平台上。显示“未在追踪平台发现”，不能推断全球都不可看。已看不等于已评分。
- 评分补全针对全库，而非只修几个例子或仅已看影片。优先稳定 IMDb/TMDb/Letterboxd/Douban 标识，标题匹配需结合年份和别名。不得用空值覆盖可靠数据，也不能为追求覆盖率硬配。
- Letterboxd 公共评分与个人评分分开。公共评分读取可靠聚合字段，不能用不准确的直方图估算替代。缺失评分显示为空值标记，不显示 `0.0`。
- 记录 Douban/IMDb 的来源、匹配方式和缓存时间。历史存档评分、parent-series 匹配和人工 override 不应冒充最新的电影独立评分。未匹配项写入完整 `missing_data_report.md`。
- `with某人`、`withppl`、`watchparty` 都属于社交观看。`watchparty` 指三人及以上，具体同伴图只统计人名，不能把 `withppl` 当作人，也不能把这几个重叠标签当作互斥类别相加。
- `theater` 和原始拼写 `thearter` 都代表影院，可同时属于显示方式和地点。未标注项目不混入要求排除未知项的饼图。现有代码对 home/personal setup 有推断，应与明确标签区分。
- lists 用“待看计划 / 偏好声明 / 主题整理”等可理解分类，不把内部 `canon` 当作统一用户标签。
- Today's Taste Brief 靠前，条数不限制为八条。电影知识和行业线索应有实际内容和来源，不堆关键词或机械新闻摘要。日期轮换不能伪装成新事实。
- 中英文 UI 完整分离，电影原名和专有名称可保留。不要新增用户没有写过的中文原始 tags。年份一行、无千位逗号；大数两种语言都用 `k/M`；评分避免多余小数。
- 用“国家 / 地区”，名称保留 `Hong Kong`、`Taiwan`。不改成 `Hong Kong SAR` 或 `Taiwan region`。
- 流媒体和推荐表支持列头双向排序及可见排序状态。长表横向滚动优先，不拆英文单词、年份和短标签。评分比较用可读数值或点图。饼图用图例和 hover，避免切片文字重叠。桌面和手机都需核对。

## 开发历史与依据

| 时间 | 演进和决定 | 可追溯依据 |
| --- | --- | --- |
| 2026-04-22 | 从官方导出开始，先做可重复生成的工作簿。用户明确拒绝重复会员统计，转为语境、文本、片单、交叉分析和个性化发现；做成可分享静态站 | 「Letterboxd 数据分析网站」；`ac6e837` |
| 2026-04-22 至 04-26 | 增加加拿大平台、组合筛选、外部推荐池，修复公共评分来源和片单分类；从旧报告站过渡到当前仓库 | 同一聊天；`ec8c78c`、`4f158a0` |
| 2026-04-26 | 用户选择无需登录的公开页面 + RSS 方案，采用每六小时和周日任务；修复 JustWatch 429，保留缓存 | `01aa580` 及工作流 |
| 2026-04-28 | 调整摘要、流媒体区顺序、双语和排版，撤回 Criterion on Demand/Bilibili 目录，修复豆瓣限流误判和 tags 逻辑 | `44f7d69`、`29d0ea5`、`9d4ccd9`、`d66ddd3` |
| 2026-04-29 至 04-30 | 全部已看纳入总表，修复标题/年份匹配及评分回填，扩大 IMDb/Douban 全库补分，生成完整缺失清单 | `88a0a92`、`59fc316`、`0e6e970`、`7881588` |
| 2026-05-04 | 自动任务并发、缓存、推送稳定性；持久化评分种子；双语、k/M、表格排序和每日内容继续改进 | `d4de06b`、`b717cc1` |
| 2026-08-08 | 旅行前处理重复失败邮件，针对 Cloudflare challenge 保留旧报告并重试，真正错误继续告警 | 「修复 Gmail 报错邮件问题」；`8197f8a` |
| 2026-10-21 | 发现完整分析停在 10 月 13 日；增加独立 RSS 面板并标出快照日期；随后用新导出补齐历史并增加覆盖保护 | 「Scaffold GavinLegend site」；`dee055f`、`84f1b96` |
| 2026-11-19 | 网站目录统一编号，旧报告站全平台归档；当前项目独立接手 Letterboxd 维护 | 「Scaffold GavinLegend site」及本项目接手聊天 |

本次回顾分页读到了早期开发聊天和主站聊天的开头，并检查了故障修复聊天和归档的「Locate Letterboxd stats link」。归档聊天曾给出旧站地址，该信息已被 11 月的归档决定取代。没有把历史助手对“完成”的陈述当作当前代码全部满足需求的证明。

历史聊天 ID，供需要细节时检索：

- `019db605-4eac-72e0-92ac-1262e818a963`：Letterboxd 数据分析网站。
- `019e0e11-d852-7e93-b35b-f0da39d1d2d9`：Scaffold GavinLegend site。
- `019fe180-7af8-7aa0-92fc-0888e64bfced`：修复 Gmail 报错邮件问题。
- `019e321a-7e35-7e33-8f58-c84f599b53e9`：Locate Letterboxd stats link，已归档。

## 后续维护记录

- 2026-11-19：Genre × Country / Region 增加默认的 All genres / 全部类型选项。汇总按独立影片计算，合拍片的国家占比均分，避免多类型重复计数；饼图尾部国家合并为其他，表格保留全部国家。切换语言保留筛选。此次复用原快照生成页面，未刷新数据日期。

- 2026-11-19：使用当日 17:30 UTC 官方导出重建并校验报告。公开报告包含 610 部影片、875 条观影事件、184 篇影评及 21 个公开片单。按用户要求排除一张仅链接可见的片单，排除记录保存在仓库外的本次构建目录。

## 当前基线和未解决限制

2026-11-19 完整报告 `generated_at` 为 `2026-11-19T17:37:35.918248+00:00`，来源是当天 17:30 UTC 的官方账号导出。含 610 部已看、610 部已评分、875 条观影事件、502 条有标签事件、184 篇影评、21 个公开片单。原始 ZIP 与排除片单均保存在公开仓库外。

本次 RSS 请求最新条目时间仍为 `2026-11-14T11:08:11+00:00`，这是条目发布时间，不是抓取时间。完整分析与 RSS 面板的日期独立。

现有缺失报告记录：流媒体总表 8,818 条，Douban 缺 3,322 条，IMDb 缺 24 条，年份缺 1 条；已看覆盖和个人评分遗漏为 0。与前一快照相比，已有 Douban/IMDb 分数没有变成空值。完整缺失原因见 `missing_data_report.md`。

仍需明确的限制：

- 当前 CI 使用 `--streaming-catalog-timeout 0`，保留旧流媒体目录。不能称为每日实时可用性验证。
- RSS 新条目不会让历史分析和推荐同步重算。长期受阻仍需新导出或另行实现可靠的数据接入。
- `build_custom_insights()` 仍有固定分析模板；没有新输入时可重复出现相同结论。每日栏目存在日期相关逻辑，不代表所有内容每天有实质变化。
- 覆盖保护只比较五项数量，不能识别所有字段损坏、同数量错误或全部评分退化。仍需数据校验和抽样。
- 元数据种子脚本枚举 ratings、watchlist、lists，不覆盖所有仅存在于 watched 的未评分影片。生成器会合并 watched，但新增未评分条目可能仍需联网补元数据。
- `.gitignore` 没有覆盖所有 ZIP/CSV 或 `source-materials/`。不能以“在本地生成”为理由把这些文件放进公开仓库。

## 验证和发布

文档修改检查链接、路径、命令和 `git diff --check` 即可。数据或代码修改按影响运行：

```bash
PYTHONPATH=.vendor python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py
```

重建后运行 `validate_report_data.py` 和覆盖检查，阅读缺失清单，不只看进程退出码。修改 UI 时，还要在浏览器查看桌面/手机、中英文、筛选、排序、tags 图例、RSS 日期和控制台错误。静态扫描通过不等于视觉验收通过。

部署使用 GitHub Pages 的 `main` 分支根目录。发布前检查当前 diff、私密文件和待提交清单，按本次任务的发布授权执行。不要直接运行早期 `publish_to_github.sh`：它会 `git add .`、重设 main 和 remote，并推送，不适合日常维护。发布后分别核验同步任务、Pages 部署、线上 JSON 时间和关键统计，不能只报 commit 成功。

首次接手整理只修改了文档。后续功能发布和数据重建记录见上文，不能将首次整理的状态当作当前状态。
