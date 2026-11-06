# Profile 维护

README 展示个人介绍、带头像的终端卡片、技术能力与 [helloc.net](https://helloc.net) 入口，详细案例留在个人网站。

## 头像卡片

卡片参考 [itgoyo/itgoyo](https://github.com/itgoyo/itgoyo)，支持深浅主题，显示 GitHub 头像、个人定位、关注方向、技术栈、部署方式、所在地、GitHub 注册年份与个人网站。头像嵌入 SVG，无需浏览器另外请求头像图片。

头像和注册年份来自 GitHub API，其余内容根据个人网站配置。展示名称统一为 `HelloC`，所在地按个人资料整理为 `Hangzhou, China · Remote`；网址仅显示在卡片底部。可在仓库变量 `PROFILE_OS` 中填写实际操作系统，未配置时不显示 OS 一行。终端卡片不再展示 Stars、关注人数或仓库排名，汇总统计由下方 Snapshot 展示。

## 本地生成

使用 Python 3.11 或更新版本：

```sh
python3 -m venv .venv
.venv/bin/pip install -r cache/requirements.txt
cp .env.example .env
.venv/bin/python src/updateGithubStats.py
```

`.env` 的 `ACCESS_TOKEN` 可留空，匿名请求有较低的速率限制。生成文件为 `img/github_stats_light.svg` 和 `img/github_stats_dark.svg`。

## 自动更新

工作流每天北京时间 16:20 更新卡片，也可手动运行 **Update profile cards**。修改脚本、依赖或工作流并推送到 `main` / `master` 时同样触发。使用默认 `GITHUB_TOKEN`，仓库策略和分支保护需允许工作流写入。

自动化只更新卡片，不修改 README 的介绍内容。

## GitHub Snapshot

使用与 itgoyo/itgoyo 相同的 [github-stats-transparent](https://github.com/itgoyo/github-stats-transparent) 透明背景模板，授权保存在 `templates/snapshot/LICENSE`。两张卡片在本仓库生成，不依赖第三方实时图片接口。

运行 `.venv/bin/python src/updateSnapshot.py` 生成概览和语言卡片；每日工作流会自动运行。

### 纳入 private

在此仓库的 **Settings → Secrets and variables → Actions → Repository secrets** 中设置 `STATS_TOKEN`。工作流检测到此 Secret 后，使用 PAT 调用 `/user/repos` 分页读取它可访问的私有仓库，合并本人公开仓库，排除 fork，并按仓库 ID 去重。私有仓库可以属于本人、协作项目或组织，实际范围由 PAT 的仓库授权决定。

Fine-grained PAT 需覆盖目标仓库，并具有 Metadata: Read-only（仓库列表、语言和贡献者统计）以及 Administration: Read-only（仓库访问量）。组织仓库还可能需要组织批准。若日志中的 private 数量为 0，请检查仓库选择、令牌是否过期及组织授权。

推送这些配置后，进入 **Actions → Update profile cards → Run workflow**。日志只输出公开/私有仓库的汇总数量，卡片只发布数量和语言分布，不输出私有仓库名称或代码。头像卡片继续使用默认 `GITHUB_TOKEN` 读取头像和个人资料，不读取私有仓库。

未配置 `STATS_TOKEN` 时回退到公开仓库统计。仓库列表或语言请求失败会中止本次生成，保留已提交的图片。代码变更量和访问量属于独立指标，读取失败时按下文标注覆盖范围。

Stars、Forks 和语言评分覆盖上述仓库范围；贡献仓库数量单独按下文的 GraphQL 并集计算。贡献总数通过 GraphQL 按年份汇总，受 PAT 权限及 GitHub 的贡献可见性规则影响，与所选仓库的语言统计范围不完全一致；查询失败时显示 `—`。代码变更行数和访问量已接入，取数口径与权限见下文。

本地运行时在 `.env` 中设置 `ACCESS_TOKEN`，并使用 `INCLUDE_PRIVATE=true .venv/bin/python src/updateSnapshot.py`；不要提交令牌。

Snapshot 按仓库等权统计语言：先将每个非空仓库的语言字节数归一化为总权重 1，再跨仓库累计语言评分；仅展示评分前 10 名，百分比按这 10 种语言的评分总和归一化为 100%，不合并为 Other。同分时按语言名称排序。空仓库或无语言数据的仓库不参与评分。两张卡片宽度均为 360，高度至少 250，语言列表每行两项，最多 10 种占 5 行，两张卡片保持等高且不裁切。README 保持左右并排，小屏幕可点击卡片查看原图。

## 字号层级

README 使用 GitHub 原生二级标题作为页标题、三级标题作为分区标题，正文保留平台默认字号。终端卡片标题 18px、正文 14px、状态栏 12px；Snapshot 标题 14px、正文 11px，图标 13px。SVG 字号会随图片显示宽度等比缩放；两张 Snapshot 继续保持同一行，可点击查看原图。

## 代码变更量与访问量

- **Lines of code changed**：调用 `/repos/{owner}/{repo}/stats/contributors`，汇总当前账号本人（按 GitHub login 匹配）的新增行数与删除行数。采用 GitHub 默认分支贡献者统计口径，排除 merge 和空提交，不是仓库现有代码行数，也不是全体贡献者的变更量。
- **Views (last 14 days)**：调用 `/repos/{owner}/{repo}/traffic/views`，汇总返回的 `count`，即最近 14 天访问次数，不是独立访客数，也不是产品网站访问量。
- Fine-grained PAT 的访问量权限为 **Administration: Read-only**，同时需覆盖目标仓库；新增权限后若组织要求审批，需等待批准。`STATS_TOKEN` 的名称保持不变。
- GitHub 返回 202 表示统计正在生成；脚本最多请求 4 次，间隔 2、4、8 秒。仍未就绪会留待下次工作流重试。
- 部分仓库成功时显示小计并加 `*`，卡片底部标注 `Partial total`；全部不可读显示 `—`。成功返回的真实零值仍显示 `0`。日志按指标输出可读仓库数和失败原因汇总，不打印仓库名称或响应正文。
- `access_denied`：检查令牌是否过期、选定仓库和权限、组织批准；`pending`：稍后重跑；`rate_limited`：等待 API 配额恢复；`no_data`：GitHub 未返回可用统计。
- GitHub 对 10,000 次及以上提交的仓库可能把贡献者新增/删除量返回为 0。脚本检测提交量上限，并把有提交但行数全零的可疑结果标记为不可用；纯二进制提交也可能因此暂不计入，避免展示误导性的零值。

相关文档：[仓库统计](https://docs.github.com/en/rest/metrics/statistics#get-all-contributor-commit-activity)、[访问量](https://docs.github.com/en/rest/metrics/traffic#get-page-views)。

### Repositories with contributions

按照参考仓库 `itgoyo/github-stats-transparent` 的 `all_repos` 口径，取以下两个 GraphQL 连接返回的仓库 ID 并集：

1. `user.repositories(isFork: false)`：GitHub 为该账号返回的非 fork 仓库。
2. `user.repositoriesContributedTo(includeUserRepositories: false, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW])`：通过提交、PR、创建仓库或 PR Review 参与的其他仓库。此分支与原仓库一致，不额外排除 fork。

两个连接独立分页，每页 100 项，按 ID 去重，不把“能访问私有仓库”直接等同于“对其有贡献”。启用 `STATS_TOKEN` 后纳入 PAT 可见的私有条目；未启用私有统计则过滤私有条目。查询使用 `USER_NAME` 指定的账号，避免令牌持有人不同导致统计错人。

范围遵循 GitHub 对上述连接的贡献类型、历史范围和可见性定义，不宣称覆盖账号全部历史。自有非 fork 仓库会按原实现直接纳入，即使没有本人代码提交。它与语言统计的仓库范围不必相同。

此指标需要 GraphQL 认证。没有令牌、权限不足、查询失败或分页异常时显示 `—`，不再使用可访问仓库数量或不完整分页结果代替；日志只包含汇总数量，不输出私有名称。

## 语言占比的统计口径

`语言评分 = Σ（该语言在仓库内的字节数 / 该仓库所有语言字节数）`。

例如 1 个大型纯 Java 仓库加 4 个小型纯 TypeScript 仓库，评分是 Java 1、TypeScript 4，显示 20% / 80%，而不是按总代码体积计算。仓库内部的混合语言比例仍保留。

这表示“按项目平衡后的语言构成”，不是总代码字节占比、本人贡献量或开发时间。每个非空仓库权重相同，小型实验项目也会计入；超过 10 种语言时，百分比仅表示所展示前 10 种之间的份额。卡片已注明 `Top 10 share · Equal weight per repository`，不对 Java 做特殊降权。

README 的终端卡片固定使用 `img/github_stats_dark.svg`，不再根据浏览器配色偏好切换；浅色 SVG 仍保留并随脚本生成，便于以后切换。Snapshot 的透明背景不受影响。
