# MCP Servers

Generated on: 2026-04-29

Source: local Codex MCP configuration in `/Users/hawyho/.codex/config.toml`
and MCP tools discoverable in the current session.

## Notes

- Environment values are intentionally omitted.
- The repository itself does not currently contain an MCP configuration file.
- "Configured" means the server is present in local Codex config. "Exposed in
  session" means tools from that server are visible to this Codex run.

## Configured MCP Servers

| Server | Command | Args | Exposed in session | Purpose |
| --- | --- | --- | --- | --- |
| `sequential-thinking` | `npx` | `-y @modelcontextprotocol/server-sequential-thinking` | Yes | Structured reasoning workflow helper. |
| `context7` | `npx` | `-y @upstash/context7-mcp` | Yes | Up-to-date library documentation lookup and code examples. |
| `playwright` | `npx` | `-y @playwright/mcp@latest --headless` | Yes | Browser automation for local web app interaction and testing. |
| `postgres-local` | `uvx` | `postgres-mcp --access-mode=restricted` | Not exposed in this session | Restricted local Postgres inspection and queries. |
| `chrome-devtools` | `npx` | `-y chrome-devtools-mcp@latest` | Yes | Chrome DevTools page control, inspection, screenshots, network, and performance tools. |
| `redis-local` | `uvx` | `--from redis-mcp-server@latest redis-mcp-server --url redis://localhost:6379/0` | Yes | Local Redis key/value, hash, set, stream, vector, and documentation helpers. |
| `semgrep` | `uvx` | `semgrep-mcp` | Not exposed in this session | Semgrep-backed code scanning and static analysis. |
| `serena` | `serena` | `start-mcp-server --context=codex --project-from-cwd` | Not exposed in this session | Codebase semantic navigation and editing assistance. |

## Exposed MCP Tool Namespaces

| Namespace | Representative tools | Purpose |
| --- | --- | --- |
| `mcp__context7__` | `resolve_library_id`, `query_docs` | Resolve libraries and query current documentation. |
| `mcp__sequential_thinking__` | `sequentialthinking` | Break down complex tasks with explicit reasoning steps. |
| `mcp__chrome_devtools__` | `list_pages`, `select_page`, `click`, `fill_form`, `take_screenshot`, `get_network_request`, `performance_stop_trace` | Inspect and control Chrome pages. |
| `mcp__playwright__` | `browser_tabs`, `browser_resize`, `browser_run_code` | Run browser automation snippets and manage browser tabs. |
| `mcp__redis_local__` | `get`, `hget`, `hset`, `scan_keys`, `dbsize`, `vector_search_hash`, `hybrid_search`, `search_redis_documents` | Inspect local Redis data and use Redis vector/search helpers. |

## Config Snippet

Sensitive values under env sections are omitted.

```toml
[mcp_servers.sequential-thinking]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-sequential-thinking"]

[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]

[mcp_servers.playwright]
command = "npx"
args = ["-y", "@playwright/mcp@latest", "--headless"]

[mcp_servers.postgres-local]
command = "uvx"
args = ["postgres-mcp", "--access-mode=restricted"]

[mcp_servers.chrome-devtools]
command = "npx"
args = ["-y", "chrome-devtools-mcp@latest"]

[mcp_servers.redis-local]
command = "uvx"
args = ["--from", "redis-mcp-server@latest", "redis-mcp-server", "--url", "redis://localhost:6379/0"]

[mcp_servers.semgrep]
command = "uvx"
args = ["semgrep-mcp"]

[mcp_servers.serena]
command = "serena"
args = ["start-mcp-server", "--context=codex", "--project-from-cwd"]
```
