import { expect, test } from "@playwright/test";
import type { JourneyCard } from "../../src/cards";

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
      const board = page.locator("translink-departures-card");
      await expect(
        board.getByText("Stop timetable", { exact: true }),
      ).toBeVisible();
      await expect(board.getByText("Expected", { exact: true })).toHaveCount(1);
      await expect(
        board.getByText("Extra service", { exact: true }),
      ).toBeVisible();
      await expect(
        board.getByText("Boarding only", { exact: true }),
      ).toBeVisible();
      await expect(board.getByText("Platform change: 5 → 6")).toBeVisible();
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
      const planner = page.getByRole("region", { name: "Journey planner" });
      await expect(planner.getByLabel("Date (Brisbane)")).toBeVisible();
      await expect(planner.getByLabel("Time (Brisbane)")).toBeVisible();
      const plan = planner.getByRole("button", { name: "Plan", exact: true });
      await plan.focus();
      await page.keyboard.press("Enter");
      const options = planner.getByRole("list", {
        name: "Journey alternatives",
      });
      await expect(options.locator(":scope > li")).toHaveCount(3);
      await expect(options.locator(":scope > li").first()).toContainText(
        "56 min",
      );
      await planner.getByLabel("Sort by").selectOption("duration");
      await expect(options.locator(":scope > li").first()).toContainText(
        "41 min",
      );
      const notice = options.getByText("1 service notice", { exact: true });
      await notice.focus();
      await page.keyboard.press("Space");
      await expect(
        options.getByText('<img src="https://example.invalid/notice">'),
      ).toBeVisible();
      expect(
        await planner.evaluate(
          (element) => element.scrollWidth <= element.clientWidth,
        ),
      ).toBe(true);
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

      const journey = page.locator("translink-journey-card");
      const title = `Line closure ${"ReplacementBusTimetable".repeat(8)}`;
      await journey.evaluate((element: JourneyCard, latestTitle) => {
        const hass = element.hass!;
        const itinerary = "sensor.renamed_journey_itinerary";
        const status = "sensor.renamed_journey_status";
        const disruptions = "sensor.renamed_journey_disruptions";
        element.hass = {
          ...hass,
          states: {
            ...hass.states,
            [itinerary]: {
              ...hass.states[itinerary]!,
              attributes: { ...hass.states[itinerary]!.attributes, legs: [] },
            },
            [status]: { ...hass.states[status]!, state: "no_service" },
            [disruptions]: {
              ...hass.states[disruptions]!,
              state: "1",
              attributes: { latest_title: latestTitle },
            },
          },
        };
      }, title);
      await expect(journey.getByRole("status")).toHaveText("No services found");
      const strip = journey.locator(".alert-strip");
      await expect(strip).toBeVisible();
      await expect(strip).toHaveText(`1 service alert · ${title}`);
      expect(
        await strip.evaluate(
          (element) => element.scrollWidth <= element.clientWidth,
        ),
      ).toBe(true);
      expect(external).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}
