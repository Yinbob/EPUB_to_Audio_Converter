import { expect, test } from "@playwright/test";

for (const viewport of [
  { width: 1440, height: 1000 },
  { width: 390, height: 844 },
]) {
  test(`长页面导航与模块保留 ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const navigation = page.getByRole("navigation", { name: "生成流程" });
    const sections = page.locator(".workflow-section");
    await expect(sections).toHaveCount(5);
    for (const section of await sections.all())
      await expect(section).toBeVisible();
    await expect(navigation).toHaveCSS("position", "static");
    await expect(page.locator("#workflow-hint")).toHaveCount(0);

    await page
      .locator("#book-setup")
      .getByLabel("起始章节", { exact: true })
      .fill("2");
    await page
      .locator("#voice-setup")
      .getByLabel("语速", { exact: true })
      .fill("1.25");
    await page.getByLabel("启用多角色配音", { exact: true }).check();

    for (const link of await navigation.getByRole("link").all()) {
      const href = await link.getAttribute("href");
      await link.press("Enter");
      const target = page.locator(href!);
      await expect(target).toBeFocused();
      await expect
        .poll(() =>
          target.evaluate((element) => {
            const header = document.querySelector(".app-header")!;
            return (
              element.getBoundingClientRect().top >=
              header.getBoundingClientRect().bottom + 14
            );
          }),
        )
        .toBe(true);
      if (href !== "#quality-setup") {
        await expect(link).toHaveAttribute("aria-current", "location");
      }
    }
    await expect
      .poll(() =>
        navigation.evaluate(
          (element) => element.getBoundingClientRect().bottom,
        ),
      )
      .toBeLessThan(0);
    await expect(page.locator(".app-header")).toBeInViewport();
    await expect(
      page.locator("#book-setup").getByLabel("起始章节", { exact: true }),
    ).toHaveValue("2");
    await expect(
      page.locator("#voice-setup").getByLabel("语速", { exact: true }),
    ).toHaveValue("1.25");
    await expect(
      page.getByLabel("启用多角色配音", { exact: true }),
    ).toBeChecked();
    await expect(page.locator(".role-workflow")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
}
