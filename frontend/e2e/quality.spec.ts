import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { newUser, seed } from "./helpers";

const PAGES = ["/dashboard", "/profile", "/imports", "/contacts", "/prospects", "/companies", "/jobs", "/opportunities", "/resumes", "/outreach", "/outreach/settings", "/tracking",
  "/suppression", "/settings", "/diagnostics", "/privacy", "/guide", "/onboarding"];

test.describe.configure({ mode: "serial" });

test("every page works at phone width: no horizontal page scroll, no console errors", async ({ page }) => {
  await newUser(page, "mobile");
  await seed(page);
  await page.setViewportSize({ width: 375, height: 812 });
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  const wide: string[] = [];
  for (const url of [...PAGES, "/login", "/signup"]) {
    if (url === "/login" || url === "/signup") await page.context().clearCookies();
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (over > 1) wide.push(`${url} (+${over}px)`);
  }
  expect(wide, "pages that scroll sideways at 375px").toEqual([]);
  expect(errors).toEqual([]);
});

test("automated accessibility audit finds no serious or critical issues", async ({ page }) => {
  await newUser(page, "axe");
  await seed(page);
  const report: string[] = [];
  for (const url of PAGES) {
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    const res = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    for (const v of res.violations.filter((x) => x.impact === "serious" || x.impact === "critical")) report.push(`${url}: ${v.id} (${v.impact}) x${v.nodes.length} e.g. ${v.nodes[0].target.join(" ")}`);
  }
  expect(report).toEqual([]);
});
