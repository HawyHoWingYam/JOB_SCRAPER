# IT 职位 AI Enrichment 与治理入口优化

## Goal

让本地操作员能够按一个来源选择 IT 相关职位，明确知道哪些职位会进入 AI Enrichment、哪些会被安全排除；当用户点击排除详情时，进入一个针对当前来源和排除原因的可理解、可执行的修复流程，而不是一个无上下文的全局治理后台。

## Background and confirmed facts

- 用户通常一次处理一个来源；目标是为当前来源选择 IT 相关职位并运行 AI Enrichment，不要求一次跨来源。
- 当前 AI Enrichment 预览显示 `8 match · 0 will run · 8 excluded` 时，运行按钮按 `effective_item_count > 0` 禁用（`frontend/src/components/ai/AIEnrichmentPage.jsx:406-410`）。
- 预览把排除原因展示为 `source_catalog_provenance_missing`，并统一链接到 Job Taxonomy Review（`frontend/src/components/ai/AIEnrichmentPage.jsx:999-1017`）。
- Job Intelligence Governance 当前是三个并列治理队列：Job Taxonomy Review、Skill Candidates、Company Industries（`frontend/src/api/jobIntelligence.js:4-19`）。页面默认加载 Job Taxonomy Review 的前 50 条 active review items，并只提供按 Job ID 搜索（`frontend/src/components/jobIntelligence/governanceAreas.js:54-78`、`frontend/src/components/jobIntelligence/GovernanceQueue.jsx:45-75`）；在 17,596 条待处理项目的场景下，左侧 50 条列表会挤压右侧详情，且用户看不出详情与当前 AI 运行之间的关系。
- Job Taxonomy Review 的人工决策是逐条选择既有 Job Subcategory 或标记证据不足（`frontend/src/components/jobIntelligence/governanceAreas.js:54-99`）；对于当前 `source_catalog_provenance_missing` 项目，详情展示了 Job UUID、证据 hash、source path 和两个并不直观的决策按钮，但没有说明用户为什么会到这里、哪个动作能让 AI enrichment 恢复。
- AI enrichment 的 taxonomy preflight 对缺失 source-catalog provenance fail closed（`backend/app/job_intelligence/canonical_taxonomy/preflight.py:44-71`），不能仅凭旧的 source classification 字段绕过。
- 仓库已有历史 Source Catalog provenance 的 report-first、operator-approved repair 设计和脚本，但当前需要先决定是否把它接入用户流程（`backend/scripts/repair_source_catalog_provenance.py:27-38`、`.trellis/spec/backend/source-job-attributes.md:99-106`）。
- 当前截图中的证据仍然有 source classification path 和分类 ID，但 `source_catalog_revision_id` 为 `null`；这属于“路径存在、版本绑定缺失”，理论上可先检查当前发布目录是否覆盖这些分类 ID。它不同于 `source_classification_paths_missing`，后者没有路径证据，不能只补一个版本引用。

## Requirements

- R1. 单来源筛选：支持选择一个当前来源及其 IT 分类；跨来源批处理不是第一版目标。分类层级和后代包含规则必须清晰可见。
- R2. 运行前预览：显示匹配总数、实际可运行数、排除数及每类排除原因；运行按钮的文案必须反映实际可运行数。
- R3. 排除可解释：对 `source_catalog_provenance_missing` 等阻塞原因显示用户能理解的解释、影响范围和下一步动作。
- R4. 正确分流：从 AI Enrichment 进入的链接应带上当前来源/分类/原因/职位范围，治理页面默认只加载相关队列，不能让用户面对无关的巨大全局队列后自行猜测。
- R5. 可理解的详情：详情面板必须先显示“这是什么、为什么阻塞当前运行、你可以做什么、做完后如何回到 AI Enrichment”，再展示 evidence hash、内部 UUID 和 audit timeline 等专家信息。
- R6. 合理的队列布局：限制首屏队列条目数量或改为分页/虚拟列表，保持详情区域稳定可见；队列数量、筛选条件和当前选中项必须持续可见。
- R7. 原因专属动作：对 `source_catalog_provenance_missing` 使用“检查/修复 Source Catalog provenance”的专属解释和动作，不把“Assign existing Job Subcategory”误呈为修复来源 provenance 的办法。
- R8. 安全边界：不得通过旧的 source classification scalar、忽略 provenance 或直接放宽 preflight 来让不具备可信 taxonomy 证据的职位进入 AI/LLM 流程。
- R9. 保留治理审计：任何人工分类、批量修复或标记证据不足的动作都必须沿用现有版本、确认、审计和可回溯机制。
- R10. 前端验证：必须从真实前端入口验证上下文跳转、分页、页码跳转、详情诊断、修复确认、部分成功状态和返回 AI Enrichment 的流程。

## Acceptance Criteria

- [ ] 用户可以选择一个来源的 IT 分类，并能看懂选择的是精确分类还是包含后代分类。
- [ ] 预览准确区分 `match`、`will run` 和 `excluded`；只有 `will run > 0` 时 Run 按钮可用。
- [ ] 用户从预览中的排除详情进入治理流程后，默认只看到当前来源、当前分类范围和当前排除原因相关的项目，而不是 17,596 条无筛选的全局队列。
- [ ] 队列首屏不会用 50 个长条目挤压详情；用户可以快速翻页/加载下一批，并始终看见当前项目详情。
- [ ] 对缺失 provenance 的职位，界面明确说明不能直接运行的原因，并提供安全的 report/review/repair 下一步；不会暗示“Assign existing Job Subcategory”能修复 source provenance。
- [ ] 详情面板中的每个动作都有面向操作员的说明；内部证据字段收纳到“查看技术证据/审计”区域。
- [ ] 修复流程在右侧详情面板内完成：先只读检查，再明确确认；完成后可回到 AI Enrichment 并重新预览当前批次。
- [ ] 一个批次部分修复成功时，页面显示原批次、已修复可运行、仍被排除三个数量，并允许运行可运行子集。
- [ ] 现有 Job Taxonomy、Skill Candidates、Company Industries 的治理能力和审计行为不被破坏。
- [ ] 覆盖相关前端和后端测试，包括单来源筛选、排除预览、带上下文的治理深链、队列布局、页码跳转和 provenance fail-closed 行为。
- [ ] 实际启动前端并验证完整用户路径；通过浏览器测试或等价的前端交互测试确认关键控件可用，并保留验证结果。

## Out of scope for the first slice

- 不改变 AI enrichment 的模型、prompt、worker、重试或并发策略。
- 不把所有 25,355 个治理项目改成一次性批量人工决策。
- 不在没有覆盖验证、版本指纹确认和操作员确认的情况下批量写入历史 provenance。

## Resolved product decisions

- Provenance 修复默认只作用于当前 AI Enrichment 预览批次：当前来源、分类、日期范围和 Pending Limit 共同确定的职位集合；不默认扩展到整个来源的所有 pending 职位。
- Job Taxonomy Review 队列默认显示 10 条紧凑项目，使用上一页/下一页和页码输入跳转；右侧固定显示当前选中项详情，技术证据和审计信息收纳在可展开区域。
- 一个当前批次中只有部分职位完成 provenance 修复时，已修复且重新通过 preflight 的子集可以直接运行；未修复职位继续单独显示原因，不阻塞可运行子集。
- `source_classification_paths_missing` 不在第一版触发重新采集；详情只说明缺少来源分类路径以及需要后续重新采集/补充来源数据。
- 选择某来源的 IT 父分类默认包含全部后代分类，并显示包含的子分类数量；需要精确范围时可改选具体子分类。
- `source_catalog_provenance_missing` 的检查、确认修复和结果反馈直接放在右侧详情面板；不再把用户送到另一个无上下文页面。

## Open product decisions

- None currently blocking the first design draft.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
