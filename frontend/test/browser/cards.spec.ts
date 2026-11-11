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
      const tracker = page.locator("translink-journey-card .active-vehicle");
      await expect(tracker.getByRole("status")).toHaveText(/Live position ·/);
      await expect(tracker).toContainText("Train 103");
      expect(
        await tracker.evaluate(
          (element) => element.scrollWidth <= element.clientWidth,
        ),
      ).toBe(true);
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
      const boardViews = board.getByRole("group", { name: "Board view" });
      const arrivals = boardViews.getByRole("button", { name: "Arrivals" });
      const departures = boardViews.getByRole("button", { name: "Departures" });
      await expect(departures).toHaveAttribute("aria-pressed", "true");
      await arrivals.focus();
      await page.keyboard.press("Enter");
      await expect(arrivals).toHaveAttribute("aria-pressed", "true");
      await expect(departures).toHaveAttribute("aria-pressed", "false");
      await expect(board.getByText("Expected stop time")).toBeVisible();
      await expect(board.getByText("Drop-off terminal")).toBeVisible();
      expect(
        await arrivals.evaluate(
          (element) => getComputedStyle(element).outlineStyle,
        ),
      ).toBe("solid");

      const direction = board.getByRole("combobox", {
        name: "Direction",
        exact: true,
      });
      await direction.focus();
      await page.keyboard.press("o");
      await expect(direction).toHaveValue("Outbound");
      await expect(board.getByText("Return terminal")).toBeVisible();
      await expect(board.getByText("Drop-off terminal")).toHaveCount(0);
      await expect(board.getByText("Expected stop time")).toHaveCount(0);
      expect(
        await direction.evaluate(
          (element) => getComputedStyle(element).outlineStyle,
        ),
      ).toBe("solid");
      for (const controls of [board.locator(".board-filters"), boardViews]) {
        expect(
          await controls.evaluate(
            (element) => element.scrollWidth <= element.clientWidth,
          ),
        ).toBe(true);
      }
      await departures.focus();
      await page.keyboard.press("Space");
      await expect(departures).toHaveAttribute("aria-pressed", "true");
      await expect(arrivals).toHaveAttribute("aria-pressed", "false");
      await expect(board.getByText("Return terminal")).toHaveCount(0);
      const toggle = page.getByRole("button", { name: /Journey details/ });
      await toggle.focus();
      await page.keyboard.press("Enter");
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(page.locator(".leg[aria-current=step]")).toContainText(
        "Active leg",
      );
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
      const share = page.getByRole("button", { name: "Share or export" });
      await share.focus();
      await page.keyboard.press("Enter");
      const preview = page.getByRole("region", {
        name: "Preview journey sharing",
      });
      const heading = preview.getByRole("heading");
      await expect(heading).toBeFocused();
      expect(
        await heading.evaluate(
          (element) => getComputedStyle(element).outlineStyle,
        ),
      ).toBe("solid");
      await expect(preview.locator(".share-text")).toContainText(
        "Trip timetable",
      );
      await expect(preview).not.toContainText("14 Private Street");
      expect(
        await preview.evaluate(
          (element) => element.scrollWidth <= element.clientWidth,
        ),
      ).toBe(true);
      await page.keyboard.press("Escape");
      await expect(preview).toBeHidden();
      await expect(share).toBeFocused();
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
      await expect(journey.locator(".state")).toHaveText("No services found");
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

test("downloads a calendar file by keyboard when share and clipboard APIs are absent", async ({
  page,
}) => {
  // Serve the local harness under a plain HTTP origin that Chromium does not
  // treat as a secure context. Requests are fulfilled from the local harness.
  await page.route("http://ha.test/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    await route.fulfill({ response: await page.request.get(pathname) });
  });
  await page.goto("http://ha.test/frontend/test/browser/index.html");
  expect(
    await page.evaluate(() => ({
      secure: window.isSecureContext,
      share: typeof navigator.share,
      clipboard: typeof navigator.clipboard,
      randomUUID: typeof crypto.randomUUID,
    })),
  ).toEqual({
    secure: false,
    share: "undefined",
    clipboard: "undefined",
    randomUUID: "undefined",
  });
  const share = page.getByRole("button", { name: "Share or export" });
  await share.focus();
  await page.keyboard.press("Enter");
  const preview = page.getByRole("region", { name: "Preview journey sharing" });
  await expect(
    preview.getByRole("button", { name: "Share", exact: true }),
  ).toHaveCount(0);
  await expect(preview.getByRole("button", { name: "Copy text" })).toHaveCount(
    0,
  );
  const download = page.waitForEvent("download");
  const button = preview.getByRole("button", {
    name: "Download calendar file",
  });
  await button.focus();
  await page.keyboard.press("Space");
  expect((await download).suggestedFilename()).toBe("translink-journey.ics");
  await page.keyboard.press("Escape");
  await expect(share).toBeFocused();
});
