import { expect, test } from "@playwright/test";
import fs from "node:fs";

test("研究审阅启用、合并预览、撤销和双主题窄屏", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const corpus = JSON.parse(
    fs.readFileSync("../examples/research_review/input.json", "utf8"),
  );
  const uploaded = await page.request.post("/api/v1/uploads", {
    multipart: {
      file: {
        name: "research-role.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(corpus.cases[0].state.script)),
      },
    },
  });
  expect(uploaded.ok()).toBeTruthy();
  const file = await uploaded.json();
  const imported = await page.request.post("/api/v1/projects/import", {
    data: { file_id: file.id },
  });
  expect(imported.ok()).toBeTruthy();
  const project = await imported.json();
  await page.goto("/?ata-seed=42");
  await page.getByLabel("启用多角色配音", { exact: true }).check();
  await page.getByText("导入剧本或载入已有项目", { exact: true }).click();
  await page
    .getByLabel("已有角色项目", { exact: true })
    .selectOption(project.id);
  await page.getByRole("button", { name: "载入项目", exact: true }).click();
  await page.getByRole("button", { name: "段落归属", exact: true }).click();
  await page.getByRole("button", { name: "优先审阅", exact: true }).click();
  const panel = page.getByRole("region", { name: "研究优先审阅" });
  await panel
    .getByRole("button", { name: "启用研究审阅", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "分析人物依据", exact: true }),
  ).toBeEnabled();
  await panel.getByText("人物关系与撤销", { exact: true }).click();
  await panel
    .getByRole("combobox", { name: "来源人物", exact: true })
    .selectOption("person_b");
  await panel
    .getByRole("combobox", { name: "合并到人物", exact: true })
    .selectOption("person_a");
  await panel
    .getByRole("button", { name: "预览全书身份合并", exact: true })
    .click();
  await expect(panel.getByText(/这次操作会改变 12 段/)).toBeVisible();
  const before = await (
    await page.request.get(`/api/v1/projects/${project.id}`)
  ).json();
  expect(before.script.chapters[0].segments[1].role_id).toBe("person_b");
  await panel
    .getByRole("button", { name: "确认应用本次修改", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "预览撤销", exact: true }),
  ).toBeEnabled();
  await panel.getByRole("button", { name: "预览撤销", exact: true }).click();
  await panel
    .getByRole("button", { name: "确认应用本次修改", exact: true })
    .click();
  await expect(panel.getByText(/过期 12 段/)).toBeVisible();
  await panel
    .getByRole("button", { name: "开始 10 分钟审阅", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "暂停计时", exact: true }),
  ).toBeEnabled();
  await panel.getByRole("button", { name: "暂停计时", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "继续计时", exact: true }),
  ).toBeEnabled();
  await panel
    .getByRole("button", { name: "暂时无法判断，稍后处理", exact: true })
    .click();
  const choice = panel.getByRole("combobox", { name: "说话人", exact: true });
  await choice.selectOption("person_a");
  await page.route(
    `**/api/v1/projects/${project.id}/research/preview`,
    (route) =>
      route.fulfill({
        status: 409,
        json: {
          error: {
            code: "revision_conflict",
            message: "项目已变化，请刷新后重新检查本次选择。",
          },
        },
      }),
  );
  await panel
    .getByRole("button", { name: "预览归属修改", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("请刷新");
  await expect(choice).toHaveValue("person_a");
  await page.unroute(`**/api/v1/projects/${project.id}/research/preview`);
  await choice.focus();
  await page.keyboard.press("Tab");
  await expect(
    panel.getByRole("button", { name: "预览归属修改", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    panel.getByRole("button", { name: "确认应用本次修改", exact: true }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "保留原状", exact: true }).click();
  // 分析服务返回草稿的 UI 契约替身；真实 spawn 提交由服务测试覆盖。
  const rawView = await (
    await page.request.get(`/api/v1/projects/${project.id}/research`)
  ).json();
  let completed = false;
  const sid = rawView.state.script.chapters[0].segments[1].segment_id;
  const proposal = {
    id: "browser-proposal",
    base_revision: rawView.state.revision,
    input_digest: "offline-test",
    analyzer_version: "offline-browser",
    status: "ready",
    applied_segments: [],
    mentions: [],
    claims: [],
    conflicts: [],
    changes: [
      {
        segment_id: sid,
        decision: {
          ...rawView.state.decisions[sid],
          entity_id: "person_a",
          status: "proposed",
        },
        dependencies: [],
      },
    ],
  };
  await page.route(`**/api/v1/projects/${project.id}/research`, (route) =>
    route.fulfill({
      json: completed
        ? {
            ...rawView,
            state: { ...rawView.state, proposals: { [proposal.id]: proposal } },
          }
        : rawView,
    }),
  );
  const fakeTask = {
    id: "browser-analysis",
    request_id: "browser-analysis-request",
    kind: "research_analyze",
    status: "running",
    created_at: 1,
    project_id: project.id,
    revision: rawView.state.revision,
    result: {},
    error: "",
    output_dirs: [],
    progress: { mode: "running", status: "离线分析", active: true },
  };
  await page.route("**/api/v1/tasks", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({ json: fakeTask })
      : route.continue(),
  );
  await page.route("**/api/v1/tasks/browser-analysis", (route) => {
    completed = true;
    return route.fulfill({
      json: {
        ...fakeTask,
        status: "succeeded",
        finished_at: 2,
        result: { proposal_id: proposal.id },
        progress: { mode: "finished", active: false },
      },
    });
  });
  await panel
    .getByRole("button", { name: "分析人物依据", exact: true })
    .click();
  await expect(panel.getByRole("region", { name: "重新分析差异" })).toBeVisible(
    { timeout: 10000 },
  );
  await expect(
    panel.getByRole("button", { name: "应用选中的 1 个建议", exact: true }),
  ).toBeEnabled();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await panel.evaluate((el) =>
    window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - 130),
  );
  fs.mkdirSync("test-results/research-review", { recursive: true });
  await page.screenshot({
    path: "test-results/research-review/desktop-light.png",
  });
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.evaluate((el) =>
    window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - 130),
  );
  await page.screenshot({
    path: "test-results/research-review/mobile-dark.png",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});
