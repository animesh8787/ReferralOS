import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

// One throwaway data directory per run (main process creates it; workers inherit it through the environment).
process.env.E2E_DIR ??= fs.mkdtempSync(path.join(os.tmpdir(), "referralos-e2e-"));
const dir = process.env.E2E_DIR;
const API = 8100;
const WEB = 3100;

// Use a Chromium already on this machine (newest installed build) so no browser download is needed; override with PLAYWRIGHT_CHROMIUM_PATH.
function installedChromium(): string | undefined {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH) return process.env.PLAYWRIGHT_CHROMIUM_PATH;
  const root = path.join(process.env.LOCALAPPDATA ?? path.join(os.homedir(), ".cache"), "ms-playwright");
  if (!fs.existsSync(root)) return undefined;
  const dirs = fs.readdirSync(root).filter((d) => /^chromium-\d+$/.test(d)).sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]));
  for (const d of dirs) {
    for (const rel of ["chrome-win64/chrome.exe", "chrome-win/chrome.exe", "chrome-linux/chrome", "chrome-mac/Chromium.app/Contents/MacOS/Chromium"]) {
      const p = path.join(root, d, rel);
      if (fs.existsSync(p)) return p;
    }
  }
  return undefined;
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 240_000,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${WEB}`, trace: "retain-on-failure", screenshot: "only-on-failure", viewport: { width: 1280, height: 900 }, launchOptions: { executablePath: installedChromium() } },
  webServer: [
    {
      // Real API, mock adapters (no network, no real email), tasks run inline, fresh SQLite database.
      command: `uv run alembic upgrade head && uv run uvicorn app.main:app --port ${API}`,
      cwd: "../backend",
      url: `http://localhost:${API}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { DATABASE_URL: `sqlite:///${dir.replaceAll("\\", "/")}/e2e.db`, DATA_DIR: dir, TASKS_INLINE: "1", ADAPTER_MODE: "mock", CORS_ORIGINS: `["http://localhost:${WEB}"]` },
    },
    { command: `npx next dev -p ${WEB}`, url: `http://localhost:${WEB}/login`, timeout: 180_000, reuseExistingServer: false, env: { BACKEND_URL: `http://localhost:${API}` } },
  ],
});
