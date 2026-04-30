# Skills

Generated on: 2026-04-29

Source: current Codex session skill registry plus installed local `SKILL.md`
files under `$CODEX_HOME`, `$HOME/.agents`, `.cc-switch`, and Superpowers
plugin cache directories.

## Notes

- The repository itself does not currently contain a `skills/` directory.
- Superpowers workflow skills appear in multiple local locations. This document
  lists the canonical local workflow copy first and notes the plugin alias set
  separately.
- Paths are local to this machine.

## System Skills

| Skill | Purpose | Path |
| --- | --- | --- |
| `imagegen` | Generate or edit raster images such as photos, illustrations, textures, sprites, mockups, or transparent cutouts. | `/Users/hawyho/.codex/skills/.system/imagegen/SKILL.md` |
| `openai-docs` | Use current official OpenAI documentation for OpenAI API and product questions. | `/Users/hawyho/.codex/skills/.system/openai-docs/SKILL.md` |
| `plugin-creator` | Create and scaffold Codex plugin directories and plugin metadata. | `/Users/hawyho/.codex/skills/.system/plugin-creator/SKILL.md` |
| `skill-creator` | Guide creation or updates of Codex skills. | `/Users/hawyho/.codex/skills/.system/skill-creator/SKILL.md` |
| `skill-installer` | Install Codex skills from curated lists or GitHub repositories. | `/Users/hawyho/.codex/skills/.system/skill-installer/SKILL.md` |

## User Skills

| Skill | Purpose | Path |
| --- | --- | --- |
| `api-design-principles` | REST and GraphQL API design principles for maintainable developer-facing APIs. | `/Users/hawyho/.agents/skills/api-design-principles/SKILL.md` |
| `api-security-best-practices` | Secure API patterns for auth, authorization, validation, rate limiting, and common API risks. | `/Users/hawyho/.agents/skills/api-security-best-practices/SKILL.md` |
| `claude-api` | Build, debug, optimize, and migrate Anthropic Claude API or SDK apps. | `/Users/hawyho/.agents/skills/claude-api/SKILL.md` |
| `docker-compose` | Define and run multi-container Docker Compose development environments. | `/Users/hawyho/.agents/skills/docker-compose/SKILL.md` |
| `e2e-testing-patterns` | Build reliable Playwright and Cypress end-to-end test suites. | `/Users/hawyho/.agents/skills/e2e-testing-patterns/SKILL.md` |
| `fastapi-templates` | Create production-ready FastAPI apps with async patterns and dependency injection. | `/Users/hawyho/.agents/skills/fastapi-templates/SKILL.md` |
| `find-skills` | Discover and install agent skills for requested capabilities. | `/Users/hawyho/.agents/skills/find-skills/SKILL.md` |
| `frontend-design` | Create polished production-grade frontend interfaces, pages, apps, and components. | `/Users/hawyho/.agents/skills/frontend-design/SKILL.md` |
| `gemini` | Use Gemini CLI for one-shot Q&A, summaries, and generation. | `/Users/hawyho/.agents/skills/gemini/SKILL.md` |
| `gpt-researcher` | Work with GPT Researcher architecture, integrations, retrievers, MCP data sources, and pipelines. | `/Users/hawyho/.agents/skills/gpt-researcher/SKILL.md` |
| `postgres` | Connect to Postgres, run SQL diagnostics, inspect schemas, review migrations, and use PostGIS or pgvector patterns. | `/Users/hawyho/.agents/skills/postgres/SKILL.md` |
| `python-testing-patterns` | Implement pytest-based Python testing strategies, fixtures, mocks, and test-driven workflows. | `/Users/hawyho/.agents/skills/python-testing-patterns/SKILL.md` |
| `smithery-ai-cli` | Find, connect, and use MCP tools and skills through Smithery CLI. | `/Users/hawyho/.agents/skills/smithery-ai-cli/SKILL.md` |
| `sqlalchemy-alembic-expert-best-practices-code-review` | Review and implement SQLAlchemy ORM and Alembic migration best practices. | `/Users/hawyho/.agents/skills/sqlalchemy-alembic-expert-best-practices-code-review/SKILL.md` |
| `vercel-react-best-practices` | React and Next.js performance patterns based on Vercel Engineering guidance. | `/Users/hawyho/.agents/skills/vercel-react-best-practices/SKILL.md` |
| `web-scraping` | Web scraping and data extraction with Python tooling. | `/Users/hawyho/.agents/skills/web-scraping/SKILL.md` |
| `webapp-testing` | Interact with and test local web apps through Playwright, screenshots, and browser logs. | `/Users/hawyho/.agents/skills/webapp-testing/SKILL.md` |

## Workflow Skills

| Skill | Purpose | Path |
| --- | --- | --- |
| `brainstorming` | Explore intent, requirements, and design before creative or behavior-changing work. | `/Users/hawyho/.cc-switch/skills/brainstorming/SKILL.md` |
| `executing-plans` | Execute a written implementation plan with review checkpoints. | `/Users/hawyho/.cc-switch/skills/executing-plans/SKILL.md` |
| `subagent-driven-development` | Execute implementation plans with independent tasks in the current session. | `/Users/hawyho/.cc-switch/skills/subagent-driven-development/SKILL.md` |
| `systematic-debugging` | Investigate bugs, test failures, or unexpected behavior before proposing fixes. | `/Users/hawyho/.cc-switch/skills/systematic-debugging/SKILL.md` |
| `test-driven-development` | Use TDD when implementing features or bug fixes. | `/Users/hawyho/.cc-switch/skills/test-driven-development/SKILL.md` |
| `using-git-worktrees` | Create isolated git worktrees for feature work or implementation plans. | `/Users/hawyho/.cc-switch/skills/using-git-worktrees/SKILL.md` |
| `using-superpowers` | Establish the rule for discovering and invoking relevant skills. | `/Users/hawyho/.cc-switch/skills/using-superpowers/SKILL.md` |
| `writing-plans` | Write multi-step implementation plans before touching code. | `/Users/hawyho/.cc-switch/skills/writing-plans/SKILL.md` |

## Superpowers Plugin Skills

The Superpowers plugin exposes the workflow skills with the `superpowers:`
prefix. The same skill set is also present in the plugin cache.

| Skill | Canonical Superpowers Path | Plugin Cache Path |
| --- | --- | --- |
| `superpowers:brainstorming` | `/Users/hawyho/.codex/superpowers/skills/brainstorming/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/brainstorming/SKILL.md` |
| `superpowers:dispatching-parallel-agents` | `/Users/hawyho/.codex/superpowers/skills/dispatching-parallel-agents/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/dispatching-parallel-agents/SKILL.md` |
| `superpowers:executing-plans` | `/Users/hawyho/.codex/superpowers/skills/executing-plans/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/executing-plans/SKILL.md` |
| `superpowers:finishing-a-development-branch` | `/Users/hawyho/.codex/superpowers/skills/finishing-a-development-branch/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/finishing-a-development-branch/SKILL.md` |
| `superpowers:receiving-code-review` | `/Users/hawyho/.codex/superpowers/skills/receiving-code-review/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/receiving-code-review/SKILL.md` |
| `superpowers:requesting-code-review` | `/Users/hawyho/.codex/superpowers/skills/requesting-code-review/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/requesting-code-review/SKILL.md` |
| `superpowers:subagent-driven-development` | `/Users/hawyho/.codex/superpowers/skills/subagent-driven-development/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/subagent-driven-development/SKILL.md` |
| `superpowers:systematic-debugging` | `/Users/hawyho/.codex/superpowers/skills/systematic-debugging/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/systematic-debugging/SKILL.md` |
| `superpowers:test-driven-development` | `/Users/hawyho/.codex/superpowers/skills/test-driven-development/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/test-driven-development/SKILL.md` |
| `superpowers:using-git-worktrees` | `/Users/hawyho/.codex/superpowers/skills/using-git-worktrees/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/using-git-worktrees/SKILL.md` |
| `superpowers:using-superpowers` | `/Users/hawyho/.codex/superpowers/skills/using-superpowers/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/using-superpowers/SKILL.md` |
| `superpowers:verification-before-completion` | `/Users/hawyho/.codex/superpowers/skills/verification-before-completion/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/verification-before-completion/SKILL.md` |
| `superpowers:writing-plans` | `/Users/hawyho/.codex/superpowers/skills/writing-plans/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/writing-plans/SKILL.md` |
| `superpowers:writing-skills` | `/Users/hawyho/.codex/superpowers/skills/writing-skills/SKILL.md` | `/Users/hawyho/.codex/plugins/cache/openai-curated/superpowers/6807e4de/skills/writing-skills/SKILL.md` |
