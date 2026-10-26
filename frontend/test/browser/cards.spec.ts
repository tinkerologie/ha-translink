import { expect, test } from "@playwright/test";
for (const width of [320, 768, 1440]) {
  for (const dark of [false, true]) {
    test(`cards fit at ${width}px in ${dark ? "dark" : "light"} mode`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      const external: string[] = [];
      page.on("request", (request) => {
        if (!request.url().startsWith("http://127.0.0.1:4178"))
          external.push(request.url());
      });
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto("/frontend/test/browser/index.html");
      if (dark)
        await page
          .locator("body")
          .evaluate((body) => body.classList.add("dark"));
      await expect(
        page.getByRole("heading", { name: "Your journey" }),
      ).toBeVisible();
      await expect(
        page.getByRole("heading", { name: "Departures", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("heading", { name: "Service alerts" }),
      ).toBeVisible();
      const toggle = page.getByRole("button", { name: /Journey details/ });
      await toggle.focus();
      await page.keyboard.press("Enter");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await page
        .locator("translink-journey-card .stop-details summary")
        .click();
      await expect(page.locator("translink-journey-card .call")).toHaveCount(
        20,
      );
      await expect(
        page.getByText("Rothwell station", { exact: true }),
      ).toBeVisible();
      await toggle.focus();
      await page.keyboard.press("Space");
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      expect(
        await toggle.evaluate(
          (element) => getComputedStyle(element).outlineStyle,
        ),
      ).toBe("solid");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      const overflows = await page
        .locator(
          "translink-journey-card,translink-departures-card,translink-alerts-card",
        )
        .evaluateAll((cards) =>
          cards.some((card) => card.scrollWidth > card.clientWidth),
        );
      expect(overflows).toBe(false);
      expect(external).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}
