import { execFileSync } from "node:child_process";

export default function globalTeardown() {
  const database = process.env.JEV_E2E_TEST_DATABASE || "jobsdb_jev_e2e_test";
  if (!/^jobsdb_jev_[a-z0-9_]+_test$/.test(database)) {
    throw new Error(`Refusing unsafe Jev E2E database cleanup: ${database}`);
  }
  try {
    execFileSync(
      "docker",
      ["rm", "-f", "job-scraper-jev-e2e-backend"],
      { stdio: "ignore" },
    );
  } catch {
    // The web server may already have exited and removed itself.
  }
  execFileSync(
    "docker",
    [
      "exec",
      "postgres-db",
      "psql",
      "-U",
      "admin",
      "-d",
      "postgres",
      "-v",
      "ON_ERROR_STOP=1",
      "-c",
      `DROP DATABASE IF EXISTS ${database} WITH (FORCE)`,
    ],
    { stdio: "ignore" },
  );
}
