import { test, expect } from "@playwright/test";

test("声音卡保存绑定本次试听，包含明确确认和固定版本导出", async ({ page }) => {
  let saved: any = null;
  const card = {
    id: "narrator",
    label: "旁白",
    language: "zh",
    version: "a".repeat(64),
    bindings: [
      {
        provider: "mimo",
        model: "mimo-v2.5-tts",
        endpoint: "https://example.invalid/v1",
      },
    ],
  };
  await page.route("**/api/v1/voice-profiles", async (route) => {
    if (route.request().method() === "POST") {
      saved = route.request().postDataJSON();
      await route.fulfill({ json: card });
    } else await route.fulfill({ json: saved ? [card] : [] });
  });
  await page.route("**/api/v1/tasks", async (route) => {
    const body = route.request().postDataJSON();
    expect(body.kind).toBe("preview");
    expect(body.generation.file_ids).toEqual([]);
    await route.fulfill({
      json: {
        id: "card-preview",
        kind: "preview",
        status: "succeeded",
        created_at: 0,
        result: { audio: { id: "preview", category: "wav" } },
        error: "",
        progress: {},
      },
    });
  });
  await page.goto("/settings");
  const save = page.getByRole("button", { name: "保存本次绑定", exact: true });
  await expect(save).toBeDisabled();
  await page
    .getByRole("button", { name: "生成声音卡试听", exact: true })
    .click();
  await expect(
    page.getByRole("link", { name: "下载本次试听", exact: true }),
  ).toBeVisible();
  await expect(save).toBeDisabled();
  await page
    .getByLabel("已听完本次试听，确认作为此引擎的声音绑定", { exact: true })
    .check();
  await save.click();
  await expect.poll(() => saved?.task_id).toBe("card-preview");
  expect(saved.confirmed).toBe(true);
  await page.getByLabel("逻辑声音", { exact: true }).selectOption("narrator");
  await expect(
    page.getByRole("link", { name: "导出声音卡 ZIP", exact: true }),
  ).toHaveAttribute(
    "href",
    `/api/v1/voice-profiles/narrator/${card.version}/export`,
  );
});

test("资源库原文段落可跳到音频且播放时反向标记，保留原书下载", async ({
  page,
  request,
}) => {
  const files = await (
    await request.get(
      "/api/v1/library/files?folder=" + encodeURIComponent("演示书籍"),
    )
  ).json();
  const audio = files.find((f: any) => f.category === "wav");
  await page.route("**/api/v1/library/source?*", async (route) =>
    route.fulfill({
      json: {
        available: true,
        manifest: {},
        source_file: { id: "original-book" },
        chapters: [{ index: 1, title: "第一章" }],
        paragraphs: [
          {
            id: "ch1:p1",
            chapter_index: 1,
            text: "原文第一段。",
            locator: {
              kind: "epub",
              href: "Text/one.xhtml",
              node_path: "/html[1]/body[1]/p[1]",
            },
          },
          {
            id: "ch1:p2",
            chapter_index: 1,
            text: "原文第二段。",
            locator: {
              kind: "epub",
              href: "Text/one.xhtml",
              node_path: "/html[1]/body[1]/p[2]",
            },
          },
        ],
        timeline: {
          chapters: [
            {
              chapter_index: 1,
              audio_file: audio,
              spans: [
                {
                  start_seconds: 0,
                  end_seconds: 0.5,
                  paragraph_ids: ["ch1:p1"],
                  precision: "chunk",
                },
                {
                  start_seconds: 0.5,
                  end_seconds: 1,
                  paragraph_ids: ["ch1:p2"],
                  precision: "chunk",
                },
              ],
            },
          ],
        },
      },
    }),
  );
  await page.goto("/library");
  await page.getByRole("button", { name: "演示书籍", exact: true }).click();
  await page.getByText("原文与音频溯源", { exact: true }).click();
  await expect(
    page.getByRole("link", { name: "下载保留的原始书籍", exact: true }),
  ).toHaveAttribute("href", "/api/v1/files/original-book?download=true");
  const paragraph = page
    .locator(".source-paragraph")
    .filter({ hasText: "原文第二段。" });
  await expect(page.locator("details audio")).toBeVisible();
  await paragraph.click();
  await expect(paragraph).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(() =>
      page
        .locator("details audio")
        .evaluate((node: HTMLAudioElement) => node.currentTime),
    )
    .toBeGreaterThanOrEqual(0.5);
});
