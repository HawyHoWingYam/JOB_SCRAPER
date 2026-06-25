# JOB_SCRAPER — ECC Project Context

> Python FastAPI job scraping application with AI enrichment for JobsDB Hong Kong and CTGoodJobs.

## Tech Stack

- **Backend**: Python 3.11, FastAPI 0.135, SQLAlchemy 2.0, PostgreSQL 15, Redis 7
- **Frontend**: React 19, Vite 5, Recharts, Lucide React
- **Infra**: Docker Compose, Playwright (browser automation)
- **AI**: Multi-provider LLM (Gemini, Anthropic, Zhipu, custom)

## Key Files

- Backend API: `backend/app/main.py`
- Frontend: `frontend/src/main.jsx`
- Config: `.env` (project root)

## ECC Integration

ECC v2.0.0 is installed at `~/.claude/` with the **full profile** (23 modules, 826 files).

### Available Agents (67)

Key agents for this project:
- `fastapi-reviewer` — FastAPI code review
- `python-reviewer` — Python code review
- `code-reviewer` — General code review
- `security-reviewer` — Security vulnerability detection
- `database-reviewer` — PostgreSQL/Supabase schema & query
- `react-reviewer` — React code review
- `planner` — Implementation planning
- `tdd-guide` — Test-driven development
- `e2e-runner` — End-to-end Playwright testing
- `docs-lookup` — API documentation lookup

### Available Commands (92)

Key commands:
- `/plan` — Create implementation plan
- `/code-review` — Review code changes
- `/build-fix` — Fix build errors
- `/tdd` — TDD workflow
- `/harness-audit` — Audit harness reliability
- `/quality-gate` — Run quality gate checks
- `/compact` — Compact context at logical breakpoints
- `/cost` — Monitor token spending
- `/model` — Switch model (sonnet/opus)

### Hooks Active

- **GateGuard**: Blocks destructive shell commands
- **Pre-commit quality**: Lint + console.log + secret detection
- **Config protection**: Blocks linter config weakening
- **MCP health check**: Validates MCP servers before use
- **Session persistence**: Auto-saves/loads session context
- **Continuous learning**: Extracts patterns from sessions
- **Cost tracking**: Per-session token/cost telemetry
- **Desktop notifications**: macOS/WSL task summaries

## ECC Skills — 自動使用 (Auto-Use)

當任務匹配以下任一技能時，**無需等待用戶要求**，直接 `run_skill()` 或 `read_skill()` 載入對應的 playbook：

### Backend / API
- `fastapi-patterns` — FastAPI 最佳實踐：Pydantic v2、DI、async handlers、auth、測試
- `python-patterns` — Python 習慣用法、PEP 8、type hints
- `api-design` — REST API 設計：資源命名、分頁、錯誤處理、版本化
- `backend-patterns` — 後端架構設計模式
- `database-migrations` — 資料庫遷移：Alembic、rollback、零停機部署
- `postgres-patterns` — PostgreSQL 優化、索引、查詢
- `docker-patterns` — Docker Compose、多服務、網路、安全
- `deployment-patterns` — CI/CD、部署策略

### Frontend (React 19)
- `react-patterns` — React 18/19 hooks、Suspense、data fetching、state
- `react-testing` — Vitest + Testing Library
- `react-performance` — React 效能優化
- `frontend-design-direction` — 設計系統、UI 模式

### Scraping / Data
- `data-scraper-agent` — 自動化爬蟲 (Playwright、調度、LLM 增強)
- `e2e-testing` — Playwright E2E 測試

### Testing / Quality
- `test-driven-development` — RED-GREEN-REFACTOR TDD
- `systematic-debugging` — 系統性除錯
- `code-review` — 程式碼審查
- `verification-loop` — 基於 checkpoints 的驗證

### Security
- `security-review` — 安全審查
- `security-scan` — 安全配置掃描

### AI / LLM (多供應商)
- `cost-aware-llm-pipeline` — 按複雜度路由模型
- `ai-first-engineering` — Eval-first 開發模式

### Workflow
- `architecture-decision-records` — ADR 記錄
- `strategic-compact` — 何時 /compact
- `error-handling` — 錯誤處理模式

### Rules (21 language ecosystems)

Key rules for this project: Python, React, TypeScript, Web, Common (all sourced from `~/.claude/rules/ecc/`)

## Token Optimization

Recommended settings (already in `~/.claude/settings.json`):
- Model: `sonnet` (default), switch with `/model opus` for deep reasoning
- `MAX_THINKING_TOKENS`: 10000
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`: 50
- `CLAUDE_CODE_SUBAGENT_MODEL`: haiku

## Quick Reference

```bash
# Compact at logical breakpoints
/compact

# Switch to deep reasoning
/model opus

# Check costs
/cost

# Run harness audit
/harness-audit

# Security scan
/security-scan
```

## Related

- ECC source: `.reasonix/ecc-src/` (v2.0.0)
- ECC skills: `.reasonix/ecc-group-a/` (130 skills)
- ECC docs: `docs/HERMES-SETUP.md`, `the-shortform-guide.md`, `the-longform-guide.md`
