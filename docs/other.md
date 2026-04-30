# 外部工具与库研究

## 已评估的 GitHub 仓库

| 仓库 | 相关性 | 结论 |
|------|--------|------|
| scrapy/scrapy | 中高 | 成熟 crawler 框架，可借鉴 middleware、pipeline、调度模型；当前项目已有 FastAPI 调度、进度、DB 保存和去重，暂不建议整体迁移 |
| D4Vinci/Scrapling | 高 | 最适合作为 CTgoodjobs 或未来新站点的 research probe；可验证自适应选择器、stealth fetcher、Playwright 抓取能力，不建议直接替换现有生产解析器 |
| rmax/scrapy-redis | 中 | 仅在未来需要多 worker 分布式抓取时考虑；当前 Redis 更适合继续服务进度、调度和任务状态 |
| ScrapeGraphAI/Scrapegraph-ai | 中 | 适合探索未知页面结构或失败页面兜底；生产保存链路仍应优先使用确定性 parser |
| santifer/career-ops | 低到中 | 可借鉴职位评估、匹配、tracker 等产品流程；对当前爬虫基础设施帮助有限 |
| lorien/awesome-web-scraping | 高 | 工具索引价值高，适合从中挑轻量 Python parser/extraction 组件补强现有架构 |
| mishushakov/llm-scraper | 中低 | TypeScript/Playwright + LLM extraction 思路可参考；后端是 Python，暂不适合作为主链路依赖 |
| volcengine/OpenViking | 低 | 偏 Agent context database；只有在需要长期研究记忆、站点变化记忆或 agent 任务记忆时才值得再看 |

---

## awesome-web-scraping 详细筛选

当前项目已经有 FastAPI、`httpx`、BeautifulSoup、Playwright、Redis、APScheduler、数据库持久化、去重和 AI enrichment。最有价值的方向不是引入完整 crawler runtime，而是用低侵入 Python 组件提升 CTgoodjobs HTML 解析、新站点研究和字段标准化能力。

### 高优先级

**extruct**
- 自动提取 JSON-LD、Microdata、OpenGraph、RDFa 等页面结构化元数据。
- 适合替代或补强 CTgoodjobs list/detail parser 中手写的 JSON-LD 提取逻辑。
- 建议先只做 research probe，对比当前 `backend/app/scraper/ctgoodjobs/list_scraper.py` 的输出一致性。

**selectolax**
- 快速 HTML parser，支持 CSS selector。
- 适合替换当前 CTgoodjobs parser 中用正则抽取 `title`、`meta`、`href`、`script[type="application/ld+json"]` 的部分。
- 优先目标是提高解析稳定性和可读性，不是追求性能优化。

**parsel**
- Scrapy 抽出的 selector 库，支持 CSS、XPath、JMESPath 和 regex。
- 适合把详情页字段定位写成更清晰的 selector 表达式。
- 如果团队更熟 XPath/CSS selector，可优先试 `parsel`；如果更看重速度和轻量，可优先试 `selectolax`。

### 中优先级

**chompjs**
- 用于解析 HTML 里嵌入的 JavaScript object，适合处理不是严格 JSON 的页面状态数据。
- 对未来新招聘站点 research probe 有价值；当前 JobsDB API 和 CTgoodjobs JSON-LD 路径暂不急需。

**dateparser**
- 解析自然语言、多语言、相对时间日期，例如 `2 days ago`、中文日期或混合时区日期。
- 只有当产品需要统一标准化 `listing_date`、`posted_at` 等字段时再引入。

**price-parser**
- 从薪资字符串中解析金额和币种，例如 `HK$25k - 35k / month`。
- 适合未来做薪资筛选、薪资统计或薪资区间标准化；当前可先保留原始 `salary_label`。

**curl_cffi**
- 可模拟浏览器 TLS/HTTP2 指纹，比只改 User-Agent 更接近真实浏览器请求。
- 不建议现在替换 `httpx`；只有在 JobsDB/CTgoodjobs 明确出现 TLS 指纹拦截、403/429 明显增加时，才作为可选 fetch backend 做 A/B probe。

### 研究用途

**Crawl4AI**
- 适合把网页转成 LLM-friendly Markdown 或做 LLM 抽取实验。
- 可用于新站点结构探索，不建议放进生产保存链路。

**ScrapeGraphAI / llm-scraper**
- 适合用 prompt + schema 快速探索未知页面字段。
- 可作为开发期辅助工具，帮助生成初版字段映射；生产链路仍应使用确定性 parser 和测试样本固化结果。

### 暂缓引入

- **Scrapy / Crawlee Python**：完整 crawler runtime，与现有 FastAPI 服务、调度、进度和 DB pipeline 重叠；新增很多站点或需要独立爬虫集群时再评估。
- **scrapy-redis**：只有在采用 Scrapy 并需要分布式 frontier/queue 时才有意义。
- **proxy/captcha marketplace 类资源**：当前还没有明确证据显示需要代理池或验证码处理，暂不进入依赖清单。
- **aiohttp**：`httpx` 已满足当前异步 HTTP 需求，没有迁移收益。
- **playwright-stealth / camoufox / Botasaurus**：作为 Playwright 被明显识别后的备用方案，不作为当前默认改造方向。

---

## 建议行动顺序

1. 用 `extruct` 对 CTgoodjobs 分类页和详情页做一次只读 probe，比较 JSON-LD 提取结果与现有 parser 是否一致。
2. 在 CTgoodjobs list/detail parser 上分别试 `selectolax` 或 `parsel`，目标是减少正则解析 HTML 的脆弱点。
3. 仅当产品需要日期或薪资结构化时，再引入 `dateparser` 和 `price-parser`。
4. 保留 `curl_cffi` 为网络层备选方案；只有在观测到 `httpx` 请求被目标站稳定阻挡时再实验。
5. 继续把 LLM 抽取工具限制在 research/probe 阶段，生产保存链路保持确定性解析、去重、DB 保存和 AI enrichment 的现有边界。
