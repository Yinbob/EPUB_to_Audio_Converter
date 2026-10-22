import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
const python =
  process.env.STUDIO_TEST_PYTHON ||
  (existsSync("../venv_audio_quality/bin/python")
    ? "../venv_audio_quality/bin/python"
    : "python3");
const chrome =
  process.env.CHROME_PATH ||
  (process.platform === "darwin"
    ? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    : undefined);
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:7864",
    headless: true,
    launchOptions: {
      executablePath: chrome,
    },
  },
  webServer: {
    command: `${python} -m uvicorn tests.services.browser_server:app_factory --factory --app-dir .. --host 127.0.0.1 --port 7864`,
    url: "http://127.0.0.1:7864/api/v1/bootstrap",
    reuseExistingServer: false,
  },
});
