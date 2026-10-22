import { test, expect } from "@playwright/test";
import fs from "node:fs";
const out = "../docs/validation/vue_interactions_20261021/screenshots";

test("四页导航、双主题与响应式视觉", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/?ata-seed=42");
  await expect(
    page.getByRole("heading", { name: "让文字化作声音" }),
  ).toBeVisible();
  await expect(page.locator("#ata-bg-canvas")).toBeVisible();
  fs.mkdirSync(out, { recursive: true });
  await page.screenshot({
    path: out + "/desktop-light.png",
    fullPage: false,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.screenshot({
    path: out + "/desktop-dark.png",
    fullPage: false,
    animations: "disabled",
  });
  await page.getByRole("link", { name: "资源库", exact: true }).click();
  await page.getByRole("button", { name: "演示书籍", exact: true }).click();
  await expect(page.getByText("第一章.wav", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "运行日志", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "运行日志", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page.getByRole("heading", { name: "管理员登录" })).toBeVisible();
  await page.getByRole("link", { name: "生成有声书", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "让文字化作声音", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".page-view")).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: out + "/mobile-dark.png",
    fullPage: false,
    animations: "disabled",
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await page.screenshot({
    path: out + "/mobile-light.png",
    fullPage: false,
    animations: "disabled",
  });
  expect(errors).toEqual([]);
});

test("离线上传、启动、刷新恢复与停止", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "让文字化作声音" }),
  ).toBeVisible();
  const before = await page.locator("#ata-bg").getAttribute("class");
  expect(before || "").not.toContain("generating");
  await page.getByLabel("上传书籍").setInputFiles({
    name: "离线书籍.docx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("offline"),
  });
  await expect(
    page.locator(".chip").filter({ hasText: "离线书籍.docx" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "高级设置", exact: true }).click();
  await page.getByLabel("仅解析，不生成音频", { exact: true }).check();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole("button", { name: "开始解析书籍", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "停止任务", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "停止任务", exact: true }),
  ).toBeVisible();
  const stop = page.getByRole("button", { name: "停止生成", exact: true });
  await expect(stop).toBeEnabled();
  await stop.scrollIntoViewIfNeeded();
  const folder = "../docs/validation/vue_neon_bloom_20261022";
  fs.mkdirSync(folder, { recursive: true });
  await page.screenshot({
    path: folder + "/stop-generation.png",
    animations: "disabled",
  });
  let stopRequests = 0;
  await page.route("**/api/v1/tasks/*/stop", async (route) => {
    stopRequests++;
    await new Promise((resolve) => setTimeout(resolve, 350));
    await route.continue();
  });
  await stop.click();
  await expect(
    page.getByRole("button", { name: "正在停止…", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("已停止（可再次点击开始）", { exact: true }),
  ).toBeVisible();
  expect(stopRequests).toBe(1);
});

test("配音模式开关、双主题按钮与顶栏回到页首", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.route("**/api/v1/books/chapters", (route) =>
    route.fulfill({
      json: {
        fingerprint: "visual-catalog",
        chapters: [{ index: 1, title: "第一章", characters: 50 }],
      },
    }),
  );
  await page.goto("/?ata-seed=42");
  await page.getByRole("button", { name: "高级设置", exact: true }).click();
  await page.getByLabel("仅解析，不生成音频", { exact: true }).uncheck();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByLabel("上传书籍", { exact: true }).setInputFiles({
    name: "示例书籍.docx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("offline"),
  });
  const role = page.getByLabel("启用多角色配音", { exact: true });
  const folder = "../docs/validation/vue_neon_bloom_20261022";
  fs.mkdirSync(folder, { recursive: true });
  await role.check();
  await expect(
    page.getByRole("combobox", { name: "已有角色项目", exact: true }),
  ).toBeVisible();
  await page
    .locator(".role-mode-switch")
    .screenshot({ path: folder + "/role-enabled.png" });
  await role.press("Space");
  await expect(role).not.toBeChecked();
  await page
    .locator(".role-mode-switch")
    .screenshot({ path: folder + "/role-disabled.png" });
  const start = page.getByRole("button", {
    name: "开始生成有声书",
    exact: true,
  });
  await expect(start).toBeEnabled();
  for (const theme of ["light", "dark"]) {
    if (theme === "dark") {
      await page.getByRole("button", { name: "切换深浅色主题" }).click();
      await page.getByRole("button", { name: "切换深浅色主题" }).click();
    }
    for (const [device, width, height] of [
      ["desktop", 1280, 900],
      ["mobile", 390, 844],
    ] as const) {
      await page.setViewportSize({ width, height });
      await page.keyboard.press("End");
      await expect(start).toBeInViewport();
      await page.screenshot({
        path: `${folder}/${device}-${theme}.png`,
        animations: "disabled",
      });
      await role.check();
      await role.scrollIntoViewIfNeeded();
      await page.screenshot({
        path: `${folder}/role-${device}-${theme}.png`,
        animations: "disabled",
      });
      await role.uncheck();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
  }
  // 验证整圈颜色缓慢流动，光环连续且文案稳定；减少动态效果时暂停。
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await start.scrollIntoViewIfNeeded();
  const optics = page.locator(".liquid-glass-edge");
  const core = optics.locator(".glass-edge-core");
  const gradient = optics.locator("linearGradient");
  await expect(optics).not.toHaveClass(/is-paused/);
  await expect
    .poll(() =>
      optics.evaluate((element) =>
        (element as SVGSVGElement).animationsPaused(),
      ),
    )
    .toBe(false);
  const rotation = await gradient.evaluate(
    (element) =>
      (element as SVGLinearGradientElement).gradientTransform.animVal.getItem(0)
        .matrix.b,
  );
  const label = page.locator(".generate-button-label");
  const labelBounds = await label.boundingBox();
  await expect
    .poll(() =>
      gradient.evaluate(
        (element) =>
          (
            element as SVGLinearGradientElement
          ).gradientTransform.animVal.getItem(0).matrix.b,
      ),
    )
    .not.toBe(rotation);
  expect(
    await core.evaluate((element) => getComputedStyle(element).strokeDasharray),
  ).toBe("none");
  expect(
    parseFloat(
      (await gradient.locator("animateTransform").getAttribute("dur"))!,
    ),
  ).toBeGreaterThanOrEqual(30);
  expect(await label.boundingBox()).toEqual(labelBounds);
  await page.screenshot({ path: folder + "/flowing-color.png" });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(optics).toHaveClass(/is-paused/);
  expect(
    await optics.evaluate((element) =>
      (element as SVGSVGElement).animationsPaused(),
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "有声书工坊，回到页面顶部", exact: true })
    .click();
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
  await expect(optics).toHaveClass(/is-paused/);
  await expect(role).not.toBeChecked();
  await page.getByRole("button", { name: "Edge", exact: true }).click();
  await expect(role).toBeDisabled();
  // 顶栏空白区域也支持回顶，主题切换不会触发。
  await page.keyboard.press("End");
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  expect(await page.evaluate(() => scrollY)).toBeGreaterThan(100);
  await page.locator(".app-header").click({ position: { x: 250, y: 12 } });
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
});

test("角色项目载入、编辑后确认失效与重新确认", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("启用多角色配音", { exact: true }).check();
  const select = page.getByRole("combobox", {
    name: "已有角色项目",
    exact: true,
  });
  await expect(select.locator("option")).toHaveCount(2);
  await select.selectOption({ index: 1 });
  await page.getByRole("button", { name: "载入项目", exact: true }).click();
  await expect(page.getByText(/修订 1 · 待复核确认/)).toBeVisible();
  await page.getByRole("button", { name: "复核与确认", exact: true }).click();
  await page
    .getByRole("button", { name: "确认剧本与角色参数", exact: true })
    .click();
  await expect(page.getByText(/已确认，可生成/)).toBeVisible();
  await page.getByRole("button", { name: "人物声音", exact: true }).click();
  await page.getByRole("button", { name: "保存声音参数", exact: true }).click();
  await expect(page.getByText(/待复核确认/)).toBeVisible();
});

test("管理员登录与退出、密钥默认不进入初始化数据", async ({ page }) => {
  const response = await page.request.get("/api/v1/bootstrap");
  expect(JSON.stringify(await response.json())).not.toContain("api_key");
  await page.goto("/settings");
  await page.getByLabel("管理员密码", { exact: true }).fill("admin");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(
    page.getByText("管理员会话已建立", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "管理员登录" })).toBeVisible();
});

test("自动目录随解析选项更新，批量上传不沿用旧目录", async ({ page }) => {
  let reads = 0;
  await page.route("**/api/v1/books/chapters", async (route) => {
    const data = route.request().postDataJSON();
    reads++;
    await route.fulfill({
      json: {
        fingerprint: `catalog-${reads}`,
        chapters: [
          {
            index: 1,
            title: `${data.provider}-${data.parser.newline_mode}-第一章`,
            characters: 20,
          },
          { index: 2, title: "自动读取的第二章", characters: 30 },
        ],
      },
    });
  });
  await page.goto("/");
  await page.getByLabel("上传书籍").setInputFiles({
    name: "自动目录.epub",
    mimeType: "application/epub+zip",
    buffer: Buffer.from("offline"),
  });
  await expect(
    page.getByText("已自动读取 2 章", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("起始章节", { exact: true })).toHaveValue("1");
  expect(reads).toBe(1);
  await page
    .getByRole("group", { name: "语音引擎" })
    .getByRole("button", { name: "Edge", exact: true })
    .click();
  await expect(
    page.getByLabel("起始章节", { exact: true }).locator("option").first(),
  ).toHaveText("1 · edge-double-第一章");
  await page.getByRole("button", { name: "高级设置", exact: true }).click();
  await page.getByLabel("段落识别", { exact: true }).selectOption("single");
  await expect(
    page.getByLabel("起始章节", { exact: true }).locator("option").first(),
  ).toHaveText("1 · edge-single-第一章");
  expect(reads).toBe(3);
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByLabel("上传书籍").setInputFiles({
    name: "第二本.epub",
    mimeType: "application/epub+zip",
    buffer: Buffer.from("offline"),
  });
  await expect(
    page.getByText("批量转换使用共用数字范围", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("起始章节", { exact: true })).toHaveAttribute(
    "type",
    "number",
  );
  expect(reads).toBe(3);
});

test("目录失败可重试，原生选择文件按钮已隐藏", async ({ page }) => {
  let failed = true;
  await page.route("**/api/v1/books/chapters", (route) =>
    failed
      ? route.fulfill({
          status: 422,
          json: {
            error: { code: "test_parse", message: "测试：暂时无法读取章节。" },
          },
        })
      : route.fulfill({
          json: {
            fingerprint: "retry",
            chapters: [{ index: 1, title: "重试成功", characters: 10 }],
          },
        }),
  );
  await page.goto("/");
  const input = page.getByLabel("上传书籍");
  const bounds = await input.boundingBox();
  expect(bounds?.width).toBeLessThanOrEqual(1);
  await input.setInputFiles({
    name: "重试.epub",
    mimeType: "application/epub+zip",
    buffer: Buffer.from("offline"),
  });
  await expect(page.getByText("测试：暂时无法读取章节。")).toBeVisible();
  failed = false;
  await page.getByRole("button", { name: "重试读取", exact: true }).click();
  await expect(
    page.getByText("已自动读取 1 章", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "读取章节目录", exact: true }),
  ).toHaveCount(0);
});

test("滑动导航保持生成草稿，快速切换与减少动态效果正常", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("上传书籍").setInputFiles({
    name: "保留草稿.epub",
    mimeType: "application/epub+zip",
    buffer: Buffer.from("offline"),
  });
  const nav = page.getByRole("navigation", { name: "主导航" });
  await nav.getByRole("link", { name: "资源库", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "你的声音资源库", exact: true }),
  ).toBeVisible();
  await nav.getByRole("link", { name: "运行日志", exact: true }).click();
  await nav.getByRole("link", { name: "设置", exact: true }).click();
  await nav.getByRole("link", { name: "生成有声书", exact: true }).click();
  await expect(
    page.locator(".chip").filter({ hasText: "保留草稿.epub" }),
  ).toBeVisible();
  await expect(nav.locator(".is-selected")).toHaveText("生成有声书");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await nav.getByRole("link", { name: "资源库", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "你的声音资源库", exact: true }),
  ).toBeVisible();
  expect(
    await nav
      .locator(".segment-indicator")
      .evaluate((el) => getComputedStyle(el).transitionDuration),
  ).toBe("0s");
  expect(errors).toEqual([]);
});

test("高级设置弹窗、背景模糊、焦点返回与设置保留", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/?ata-seed=42");
  const trigger = page.getByRole("button", { name: "高级设置", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "高级设置", exact: true });
  await expect(dialog).toBeVisible();
  await expect(
    page.getByRole("button", { name: "关闭高级设置", exact: true }),
  ).toBeFocused();
  expect(
    await dialog.evaluate(
      (el) => getComputedStyle(el, "::backdrop").backdropFilter,
    ),
  ).toContain("blur(12px)");
  await page.getByLabel("章节并行数", { exact: true }).fill("3");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(page.getByLabel("章节并行数", { exact: true })).toHaveValue("3");
  const folder = "../docs/validation/vue_advanced_modal_20261021";
  fs.mkdirSync(folder, { recursive: true });
  await page.screenshot({
    path: folder + "/desktop-light.png",
    animations: "disabled",
  });
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await page.getByRole("button", { name: "切换深浅色主题" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await trigger.click();
  await expect(dialog).toBeVisible();
  await page.screenshot({
    path: folder + "/mobile-dark.png",
    animations: "disabled",
  });
  const bounds = await dialog.boundingBox();
  expect(bounds!.width).toBeLessThanOrEqual(390);
  expect(bounds!.height).toBeLessThanOrEqual(844);
  await page.mouse.click(2, 2);
  await expect(dialog).not.toBeVisible();
});

test("封面上传、批量占位、移除与旧版响应式宽度", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/?ata-seed=42");
  const folder = "../docs/validation/vue_book_covers_20261022";
  fs.mkdirSync(folder, { recursive: true });
  await page.screenshot({ path: folder + "/empty-desktop.png" });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page
    .getByLabel("上传书籍", { exact: true })
    .setInputFiles("tests/fixtures/covered-book.epub");
  const card = page.locator(".uploaded-book");
  const cover = card.locator("img");
  await expect(cover).toBeVisible();
  await expect(card.locator(".book-cover")).toHaveClass(/has-image/);
  expect(
    await cover.evaluate((el) => (el as HTMLImageElement).naturalWidth),
  ).toBeGreaterThan(0);
  await expect(page.getByText(/已自动读取 \d+ 章/)).toBeVisible();
  await expect(page.getByText(/· 已读取书籍封面$/)).toBeVisible();
  const nav = page.getByRole("navigation", { name: "主导航" });
  await nav.getByRole("link", { name: "资源库", exact: true }).click();
  await nav.getByRole("link", { name: "生成有声书", exact: true }).click();
  await expect(cover).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const theme of ["light", "dark"]) {
    if (theme === "dark") {
      await page.getByRole("button", { name: "切换深浅色主题" }).click();
      await page.getByRole("button", { name: "切换深浅色主题" }).click();
    }
    for (const [device, width, height, shellWidth] of [
      ["desktop", 1600, 1000, 1320],
      ["laptop", 1280, 900, 1280],
      ["narrow", 1100, 900, 1100],
      ["mobile", 390, 844, 390],
    ] as const) {
      await page.setViewportSize({ width, height });
      await page.evaluate(() => scrollTo(0, 0));
      expect((await page.locator(".studio-shell").boundingBox())!.width).toBe(
        shellWidth,
      );
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `${folder}/${device}-${theme}.png`,
        animations: "disabled",
      });
    }
  }
  await page.getByLabel("上传书籍", { exact: true }).setInputFiles({
    name: "没有封面的很长书籍名称用来验证换行与布局.docx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("offline"),
  });
  await expect(page.locator(".uploaded-book")).toHaveCount(2);
  await expect(page.getByText(/· 暂无内嵌封面$/)).toBeVisible();
  const fallback = page.locator(".uploaded-book").last();
  expect(await fallback.evaluate((el) => getComputedStyle(el).transform)).toBe(
    "none",
  );
  await fallback.scrollIntoViewIfNeeded();
  await page.screenshot({
    path: folder + "/batch-mobile-dark.png",
    animations: "disabled",
  });
  await page
    .locator(".uploaded-book")
    .first()
    .getByRole("button", { name: "移除文件" })
    .click();
  await expect(page.locator(".uploaded-book")).toHaveCount(1);
  await page.getByRole("button", { name: "移除文件", exact: true }).click();
  await expect(page.locator(".uploaded-book")).toHaveCount(0);
  await expect(
    page.getByText("拖放书籍到此处，或点击选择", { exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
