import { test, expect } from "@playwright/test";

test("引擎音色名称、自定义模型和多卡设备可以配置", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "MiniMax", exact: true }).click();
  await expect(
    page.locator('datalist option[value="male-qn-qingse"]'),
  ).toHaveAttribute("label", "青涩青年音色");
  await page.getByLabel("模型", { exact: true }).fill("custom-minimax-model");
  await page.getByLabel("音色", { exact: true }).fill("my-cloned-voice");
  await expect(page.getByLabel("音色", { exact: true })).toHaveValue(
    "my-cloned-voice",
  );

  await page.getByRole("button", { name: "VoxCPM", exact: true }).click();
  await page.getByLabel("模型", { exact: true }).fill("/models/local-voxcpm");
  await page.getByLabel("设备", { exact: true }).fill("cuda:1");
  await page.getByLabel("预设音色", { exact: true }).fill("file:固定人声.wav");
  await expect(page.getByLabel("设备", { exact: true })).toHaveValue("cuda:1");

  await page.getByRole("button", { name: "Chatterbox", exact: true }).click();
  await page
    .getByLabel("模型", { exact: true })
    .selectOption("chatterbox-v0.5");
  await expect(page.getByLabel("模型", { exact: true })).toHaveValue(
    "chatterbox-v0.5",
  );

  await page.getByRole("button", { name: "Edge", exact: true }).click();
  await expect(
    page.getByLabel("音色", { exact: true }).locator("option").first(),
  ).toContainText("zh-CN-");
});

test("音色说明支持完整文档格式、自动识别、错误及导入警告", async ({ page }) => {
  await page.goto("/settings");
  const input = page.locator('input[type="file"][accept*=".pdf"]');
  for (const suffix of [".pdf", ".md", ".html", ".tsv"]) {
    expect(await input.getAttribute("accept")).toContain(suffix);
  }
  await expect(page.getByLabel("提供商", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("默认语言", { exact: true })).toHaveValue("");
  await expect(
    page.getByLabel("默认语言", { exact: true }).locator('option[value="yue"]'),
  ).toHaveText("粤语");
  let requests = 0;
  await page.route("**/api/v1/voices/import", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.provider).toBeNull();
    expect(body.language).toBe("");
    requests++;
    if (requests === 1) {
      await route.fulfill({
        status: 422,
        json: {
          error: { code: "voice_import", message: "没有可解析的文档内容。" },
        },
      });
    } else {
      await route.fulfill({
        json: {
          count: 1,
          source_name: "粘贴内容",
          entries: [
            {
              provider: "minimax",
              voice_id: "my-voice",
              display_name: "我的声音",
              language: "yue",
            },
          ],
          warnings: ["请试听后确认音色。"],
        },
      });
    }
  });
  await page
    .getByRole("button", { name: "解析并保存音色", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("没有可解析的文档内容。");
  await expect(page.getByText("本次导入", { exact: false })).toHaveCount(0);
  await page.getByLabel("粘贴音色说明", { exact: true }).fill("有效音色说明");
  await page
    .getByRole("button", { name: "解析并保存音色", exact: true })
    .click();
  await expect(
    page.getByText("请试听后确认音色。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("我的声音 · my-voice · MiniMax · yue", { exact: true }),
  ).toBeVisible();
});
