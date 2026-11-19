# Letterboxd 项目接手规则

## 范围和开始方式

- 本 Project 专门维护 `GavinLegend/Letterboxd_Data_Update`，账号为 `goorison`。网站为 https://gavinlegend.github.io/Letterboxd_Data_Update/ 。
- 先读 `README.md`，再检查 `git status`、相关代码及数据时间。README 的历史基线不是实时状态。
- 本地正式目录为 `/Users/gavin/Downloads/_Organized/11_Websites/02_Letterboxd_Data_Update`。不要回到旧 `Documents` 检出或临时目录维护。
- `gavinlegend.com` 是独立个人主站。不要把它的 Node/Cloudflare 构建、设计规则或部署路径套用到本项目。
- `letterboxd-custom-report` 已归档，其 Pages 已关闭。不要恢复、修改或向其发布，除非用户明确要求。当前文件中的 `custom-report` 名称属于有效代码，不要误删。
- 需要历史细节时，用 README 中的聊天 ID 主动查询。不要让用户重复提供已经可读取的决定。历史助手的完成声明需要与当前代码核对。

## 产品目标和长期决定

- 核心是帮助 Gavin 理解观影偏好、发掘好作品、了解电影和行业。不要重复堆砌 Letterboxd 会员已有总览，也不要为凑功能添加无意义的数据。
- 保留国家/地区 × 类型分析、reviews 文本、lists 偏好、tags 语境、外部推荐和加拿大平台查询。
- 推荐池不能只限 watchlist 或 lists。保留组合筛选、多选类型包含/排除、列头双向排序及清晰的排序状态。
- 全部已看影片都要保留，包括未评分、未在追踪平台发现的影片。不能因 join 或元数据失败丢行。未在追踪平台发现不等于所有平台都不可用。
- 全库 Douban/IMDb 补分优先于表面修饰。不要仅修用户举出的几个例子或仅已看子集。未能可靠补齐时记录完整原因，不编造、不硬配。
- 不恢复 Criterion on Demand 或未可靠合并的 Bilibili 流媒体目录，不展示无用的 Bilibili 评分和 Douban votes。Criterion Channel 继续保留；原始 `bilibili` 观看标签也继续保留。
- Today's Taste Brief 靠前，条数不限八条。电影知识和行业线索应有实质信息、依据和来源，不能用随机填充、关键词或日期变化假装每日更新。

## 数据语义

- 区分 watched、rated、diary events、reviews 和平台目录记录，报告数量时说明口径。
- 区分个人评分、Letterboxd 公共评分、Douban 和 IMDb 评分。缺失不是零分。
- 优先稳定 ID，其次结合标题、年份和别名匹配。同名翻拍、年份偏移、剧集与电影版本必须谨慎核对。
- 不用 null 或低质量新匹配覆盖可靠值。保留评分来源、时间、匹配方式、rating seeds 和缓存版本。
- 历史评分及 parent-series/manual overrides 不能冒充当前单片实时评分。限流或拦截不等于没有词条。
- `with某人`、`withppl`、`watchparty` 是重叠的社交观看信号。`watchparty` 是三人及以上；具体同伴统计不把 `withppl` 当作人。不得重复计为互斥分类。
- `theater`/`thearter` 都是影院，可计入显示方式和地点。用户要求排除未标注项的饼图不加入 Unknown。推断地点需与显式 tags 区分。
- 原始 tags 保留，不擅自翻译或增造中文 tags。UI 翻译与原始数据分开。
- lists 使用可理解的待看计划、偏好声明、主题整理等分类，不重新展示内部 `canon` 术语。

## 界面和文案

- 中英文 UI 完整分离，包括标题、提示、空状态、表头、筛选、图例和 tooltip。电影原名、专名可保留。
- 年份无千位逗号并保持一行；两种语言大数统一 `k/M`，不用“万”；评分使用适当小数位。
- 使用“国家 / 地区”，名称保留 `Hong Kong` 和 `Taiwan`。
- 不拆英文单词、年份或短中文标签。长表优先横向滚动。桌面和手机都要检查重叠、溢出和多余留白。
- 饼图优先图例和 hover，避免切片上堆字。评分对比使用可读数值或点图，不能只有差异难辨的长柱。
- 页面说明用客观、自然的网站语言，不放助手对话、实施细节或机械的功能说明。

## 构建和更新纪律

- 核心源文件是 `scripts/build_custom_letterboxd_report.py`，`build_html()` 包含大部分前端。常规修改应改源再生成，不能只补根目录 HTML。
- 保持根目录 HTML 和 JSON 一致，保留独立 `recent-activity.js/css/json`。不要用生成器的 share-site README 覆盖人工维护的 README。
- 从仓库根目录运行构建。依赖为 Python/pandas/numpy/lxml/curl_cffi/openpyxl，CI 使用 Python 3.11；命令见 README。
- 先生成候选，再校验、比较覆盖并复制公开产物。本地 `run_public_sync.sh` 会直接覆盖报告，缺少 CI 覆盖保护和 RSS 步骤，不作为安全默认入口。
- 保留 challenge 退出码 75、最后完整快照和 RSS 回退逻辑。只对已识别的上游 challenge 温和退出，真正错误不能静默吞掉。
- 区分 RSS 最新条目、完整报告生成日期和流媒体目录日期。RSS 不会重算完整分析，工作流 success 不能证明完整更新。
- `--streaming-catalog-timeout 0` 表示禁用目录刷新并复用缓存，不是无限等待。不能把缓存可用性描述成实时验证。
- 账号导出用新的空输入目录，避免旧片单残留。减少的记录先检查：不完整抓取应保留旧快照，真实删除应以新导出校准。
- 保留工作流的并发控制、缓存、评分种子和推送重试。修改同步时同时考虑 CI 与本地流程差异。

## 隐私、验证和交付

- 原始 ZIP、准备后的 CSV、私人 source-materials 和敏感文件放在公开仓库之外。当前 `.gitignore` 并未自动保护所有这些文件。
- 导出准备脚本只筛选文件和精简 profile，不自动判断私密片单/评论。发布前检查产物内容和准确的待提交清单。
- 账号导出中的“知道链接的人可见”片单不默认纳入公开网站。先核对可见性，按用户确认的范围筛选，并将排除清单保存在仓库外的本次构建目录，后续重建继续遵守。
- 不做与任务无关的全盘私人文件搜索。需要导出时优先使用本次用户提供或已明确指定的路径。
- 不运行会 `git add .`、重设分支/remote 并推送的旧 `publish_to_github.sh` 作为日常流程。只暂存本次明确需要的文件。
- 根据用户当前任务及仍适用的授权决定是否提交、推送和部署。历史某次“更新网站”不是把所有文档整理都自动上线的理由，也不需要对已授权的发布重复确认。
- 文档修改检查路径、命令和 `git diff --check`。代码修改运行相关现有测试及语法检查；数据重建运行 validator 和 coverage 检查，并阅读输出，不只看退出码。
- UI 修改检查手机/桌面、中英文、筛选、排序、图表、RSS 和控制台。缺失报告的静态语言扫描不能代替浏览器验收。
- 用户要求发布时，完成部署并核对线上 JSON 时间与统计，不只报告 push 成功。说明实际更新了哪些数据及仍未更新的部分。
- 新决定、数据流程或结构变化及时更新 README；稳定接手规则变化同步更新本文件。未实现的要求明确标为待办或限制。

## Gavin 的通用写作偏好

- 使用自然、日常语言和短句，只保留必要术语。报告和普通文档避免第一人称，除非明确要求；求职信可用第一人称。
- 不用 em dash 或 en dash 连接分句，尽量不用分号。连字符只用于必要复合词或技术记号。
- 编辑用户提供的 Word 文档时保留已有字体、符号、样式和布局，除非用户要求改变。
- 求职信不使用 “appeals to me”、“appeal to me”、“appealing to me”，也不用 “appear to me” 或 “appearance to me” 代替动机表达。
- 交通条件写 “I have access to a reliable vehicle.”，不写 “I own a car”。
- 避免 “I value the chance”、“I would value the chance” 和例行的 “I would welcome the opportunity”。直接说明兴趣、贡献或学习目标，不机械添加向他人学习的句子。
- 交付前复查这些措辞，保留内容和自信，去除套话。
