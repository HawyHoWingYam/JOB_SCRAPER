# Suggested Commands
- Start stack: `docker-compose up -d`
- Frontend dev server: `npm --prefix frontend run dev`
- Frontend build: `npm --prefix frontend run build`
- Frontend lint: `npm --prefix frontend run lint`
- Frontend format: `npm --prefix frontend run format`
- Backend tests: `pytest backend/tests -v`
- Single backend test file: `pytest backend/tests/<path>.py -v`
- Repo status: `git status --short`
- Fast file search: `rg --files`, `rg -n "pattern" <paths>`
