#!/usr/bin/env bash
set -euo pipefail

container_name="job-scraper-jev-e2e-backend"

cleanup() {
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM
cleanup
test_database="${JEV_E2E_TEST_DATABASE:-jobsdb_jev_e2e_test}"
if [[ ! "${test_database}" =~ ^jobsdb_jev_[a-z0-9_]+_test$ ]]; then
  echo "Refusing unsafe Jev E2E database name: ${test_database}" >&2
  exit 1
fi
if ! docker exec postgres-db psql -U admin -d postgres -tA \
  -c "SELECT datname FROM pg_database" | grep -Fxq "${test_database}"; then
  docker exec postgres-db createdb -U admin "${test_database}"
fi
docker compose -f ../docker-compose.yml run \
  --rm \
  --name "${container_name}" \
  --no-deps \
  -e DATABASE_URL="postgresql://admin:dev_password@postgres-db:5432/${test_database}" \
  -e JEV_E2E_DATABASE_URL="postgresql://admin:dev_password@postgres-db:5432/${test_database}" \
  -p 18001:18001 \
  backend-api \
  uvicorn tests.e2e.jev_app:app --host 0.0.0.0 --port 18001
