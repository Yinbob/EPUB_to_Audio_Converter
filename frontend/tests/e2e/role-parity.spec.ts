import { expect, test, type Page } from "@playwright/test";

async function roleProject(page: Page) {
  let project: any = {
    id: "role-parity-project",
    revision: 1,
    confirmed: false,
    file: { id: "script" },
    script: {
      schema_version: 2,
      provider: "openai",
      roles: {
        narrator: {
          display_name: "旁白",
          provider_params: { voice: "冰糖", speed: 1 },
        },
        first: {
          display_name: "甲人物",
          provider_params: { voice: "茉莉", speed: 1 },
        },
        second: {
          display_name: "乙人物",
          provider_params: { voice: "茉莉", speed: 1.2 },
        },
      },
      chapters: [
        {
          chapter_index: 1,
          title: "第一章",
          segments: [
            {
              segment_id: "a",
              role_id: "narrator",
              text: "他走进了房间。",
              text_kind: "narration",
              speaker: { status: "confirmed", evidence: [] },
            },
            {
              segment_id: "b",
              role_id: "first",
              text: "你好，我在这里等你。",
              text_kind: "dialogue",
              speaker: {
                status: "proposed",
                evidence: [{ kind: "explicit_speech_tag", quote: "甲人物说" }],
              },
            },
            {
              segment_id: "c",
              role_id: "second",
              text: "谢谢，我已经来了。",
              text_kind: "dialogue",
              speaker: { status: "proposed", evidence: [] },
            },
          ],
        },
      ],
    },
  };
  await page.route("**/api/v1/projects", (route) =>
    route.fulfill({ json: [{ id: project.id, revision: project.revision }] }),
  );
  await page.route("**/api/v1/projects/role-parity-project", async (route) => {
    if (route.request().method() === "PATCH") {
      const edit = route.request().postDataJSON();
      project = structuredClone(project);
      if (edit.operation === "segment") {
        const segment = project.script.chapters[0].segments.find(
          (s: any) => s.segment_id === edit.data.segment_id,
        );
        segment.role_id = edit.data.entity_id;
        segment.speaker.status = "confirmed";
      }
      project.revision++;
      project.confirmed = false;
    }
    await route.fulfill({ json: project });
  });
  await page.goto("/");
  await page.getByLabel("启用多角色配音", { exact: true }).check();
  await page.getByText("导入剧本或载入已有项目", { exact: true }).click();
  await page
    .getByLabel("已有角色项目", { exact: true })
    .selectOption(project.id);
  await page.getByRole("button", { name: "载入项目", exact: true }).click();
  await expect(
    page.getByText("修订 1 · 待复核确认", { exact: true }),
  ).toBeVisible();
}

test("角色复核保留对白筛选、判断依据、音色分组和保存后下一段", async ({
  page,
}) => {
  await roleProject(page);
  await page.getByRole("button", { name: "段落归属", exact: true }).click();
  const voices = page.getByLabel("按配置音色检索", { exact: true });
  await expect(voices.locator("option")).toHaveCount(3);
  await expect(voices.locator("option").last()).toContainText(
    "甲人物 / 乙人物 · 2 段",
  );
  await page.getByLabel("复核范围", { exact: true }).selectOption("dialogue");
  await expect(
    page.getByRole("button", { name: "他走进了房间。", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("复核范围", { exact: true }).selectOption("pending");
  await page
    .getByRole("button", { name: "你好，我在这里等你。", exact: true })
    .click();
  await expect(
    page.getByText("explicit_speech_tag：甲人物说", { exact: false }),
  ).toBeVisible();
  await expect(page.getByLabel("本段朗读人物", { exact: true })).toHaveValue(
    "first",
  );
  await page
    .getByRole("button", { name: "保存本段归属，继续下一段", exact: true })
    .click();
  await expect(page.locator(".segment-text")).toHaveText("谢谢，我已经来了。");
  await expect(page.getByLabel("本段朗读人物", { exact: true })).toHaveValue(
    "second",
  );
});

test("切换人物或保存新修订后不能固定上一个人物的试听", async ({ page }) => {
  await roleProject(page);
  await page.route("**/api/v1/tasks", async (route) => {
    const body = route.request().postDataJSON();
    await route.fulfill({
      json: {
        id: "bound-preview",
        kind: "preview",
        status: "succeeded",
        created_at: 0,
        project_id: body.project_id,
        revision: body.revision,
        role_id: body.role_id,
        result: { audio: { id: "preview-audio" } },
        progress: {},
        error: "",
      },
    });
  });
  await page.getByRole("button", { name: "试听此人物", exact: true }).click();
  const freeze = page.getByRole("button", {
    name: "将本次试听固定为此人物声音",
    exact: true,
  });
  await expect(freeze).toBeVisible();
  await page
    .locator(".role-list")
    .getByRole("button", { name: "甲人物", exact: true })
    .click();
  await expect(freeze).toHaveCount(0);
  await page
    .locator(".role-list")
    .getByRole("button", { name: "旁白", exact: true })
    .click();
  await expect(freeze).toBeVisible();
  await page.getByRole("button", { name: "保存声音参数", exact: true }).click();
  await expect(
    page.getByText("修订 2 · 待复核确认", { exact: true }),
  ).toBeVisible();
  await expect(freeze).toHaveCount(0);
});
