import fs from "node:fs";
import path from "node:path";
import { expect, Page, test } from "@playwright/test";

const SAMPLES = path.resolve(__dirname, "../../samples");
const OUTBOX = path.join(process.env.E2E_DIR!, "outbox");
const EMAIL = `e2e.${Date.now()}@example.com`;
const PASSWORD = "correct-horse-9";

function latestToken(to: string): string {
  const files = fs.readdirSync(OUTBOX).sort();
  for (const f of files.reverse()) {
    const m = JSON.parse(fs.readFileSync(path.join(OUTBOX, f), "utf-8"));
    if (m.to === to) return m.body.split(": ").pop() as string;
  }
  throw new Error("no mail for " + to);
}

async function status(page: Page, text: RegExp | string, timeout = 60_000) {
  await expect(page.getByRole("status").filter({ hasText: text }).first()).toBeVisible({ timeout });
}

test("sign up, verify, onboard, import, discover, match, tailor, approve, send (mock), track, export, delete", async ({ page }) => {
  // ---------------------------------------------------------------- account
  await page.goto("/signup");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign up" }).click();
  await status(page, /Account created/);

  await page.goto("/verify");
  await page.getByLabel("Token from your email").fill(latestToken(EMAIL));
  await page.getByRole("button", { name: "Verify" }).click();
  await status(page, /Email verified/);

  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Upload your resume or enter your details")).toBeVisible();

  // keyboard users get a skip link as the first stop
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  const skip = page.getByRole("link", { name: "Skip to content" });
  expect(await page.evaluate(() => document.querySelector("a[href], button, input, select, textarea, [tabindex]")?.textContent)).toBe("Skip to content"); // first stop in tab order
  await skip.focus();
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport(); // visible while focused
  await expect(page.locator("#main")).toHaveCount(1); // and it points at a real target

  // ---------------------------------------------------------------- onboarding: resume, GitHub (mock), preferences
  await page.goto("/onboarding");
  await page.getByLabel("Resume file").setInputFiles(path.join(SAMPLES, "resumes/alex_experienced.pdf"));
  await status(page, /Resume read/);
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByLabel("Fetch my public GitHub data").check();
  await page.getByLabel("GitHub username or URL").fill("demo-user");
  await page.getByRole("button", { name: "Fetch" }).first().click();
  await status(page, /GitHub checked/);
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByText(/Profile completeness:/)).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByLabel(/Roles you want/).fill("Backend Engineer");
  await page.getByLabel(/Preferred locations/).fill("Remote");
  await page.getByRole("button", { name: "Save" }).click();
  await status(page, "Saved.");
  await page.getByRole("button", { name: "Continue" }).click();

  // ---------------------------------------------------------------- imports (LinkedIn + HR with provenance)
  await page.getByRole("link", { name: /Import your LinkedIn connections CSV/ }).click();
  await expect(page).toHaveURL(/\/imports/);
  await page.getByLabel("CSV file (up to 25 MB)").setInputFiles(path.join(SAMPLES, "contacts/linkedin_connections_sample.csv"));
  await expect(page.getByText(/Detected: utf-8/)).toBeVisible();
  await expect(page.getByText("Unused columns:")).toHaveCount(0); // every column of the export was recognised
  await page.getByRole("button", { name: "Start import" }).click();
  await expect(page.getByText(/Read 60 · valid 60/)).toBeVisible({ timeout: 60_000 });

  await page.getByLabel("HR / recruiter contacts").check();
  await page.getByLabel("CSV file (up to 25 MB)").setInputFiles(path.join(SAMPLES, "contacts/hr_contacts_sample.csv"));
  await expect(page.getByRole("button", { name: "Start import" })).toBeDisabled(); // provenance is required
  await page.getByLabel(/Where did this list come from/).selectOption("self_collected");
  await page.getByRole("button", { name: "Start import" }).click();
  await expect(page.getByText(/duplicates 1/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Inspect rows" }).first().click();
  await expect(page.getByRole("heading", { name: "Rows" })).toBeVisible();
  await expect(page.getByText("Blank line")).toBeVisible(); // rejected rows come with their reason
  await page.getByLabel("Show").selectOption("valid");
  await expect(page.getByText(/Invalid email 'not-an-email'/)).toBeVisible(); // a bad address is flagged but the person is not silently dropped

  // ---------------------------------------------------------------- jobs: add a board, discover, verify
  await page.goto("/onboarding");
  await page.getByRole("button", { name: "Continue" }).click(); // sources -> discovery
  await page.getByLabel("Company name").fill("Acme Test Co");
  await page.getByLabel("Job board URL").fill("https://boards.greenhouse.io/acme-test");
  await page.getByRole("button", { name: "Add and search" }).click();
  await status(page, /Board added and searched/);
  await page.getByRole("button", { name: "Finish setup" }).click();
  await expect(page).toHaveURL(/\/dashboard/);

  await page.goto("/jobs");
  await expect(page.getByRole("link", { name: "Backend Engineer" })).toBeVisible();
  await expect(page.getByText(/boards reachable/)).toBeVisible();
  await page.getByRole("link", { name: "Backend Engineer" }).click();
  await expect(page.getByText("Verified open").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verification evidence" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "api listed" }).first()).toBeVisible();

  // ---------------------------------------------------------------- opportunities
  await page.goto("/opportunities");
  await page.getByRole("button", { name: "Re-analyse my jobs" }).click();
  const card = page.locator("article", { hasText: "Backend Engineer" }).first();
  await expect(card.getByText("Verified and eligible")).toBeVisible({ timeout: 60_000 });
  await expect(card.getByText("Who to contact first")).toBeVisible();
  await expect(card.getByText(/inferred from connection data, not verified/)).toBeVisible();

  // ---------------------------------------------------------------- tailor + approve a resume
  await page.goto("/jobs");
  await page.getByRole("link", { name: "Backend Engineer" }).click();
  await page.getByRole("button", { name: "Tailor my resume" }).click();
  await expect(page.getByRole("heading", { name: /Resume workspace/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/statements are supported by your profile/)).toBeVisible();
  await expect(page.getByText(/not an ATS score/)).toBeVisible();
  await page.getByRole("button", { name: "Approve this version" }).click();
  await status(page, /Approved\. This version is now locked/);
  const pdf = await page.request.get(page.url().replace(/\/resumes\//, "/api/tailoring/") + "/files/resume.pdf");
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");

  // ---------------------------------------------------------------- outreach settings, simulated Gmail, batch, approve, send
  await page.goto("/outreach/settings");
  await page.getByLabel("Your name").fill("Alex Example");
  await page.getByLabel("Your email address").fill("alex.example@example.com");
  await page.getByLabel(/Send through my Gmail/).check();
  await page.getByLabel(/at least \(seconds\)/).fill("0"); // no real waiting in the test; the default is a random 30-120 s between emails
  await page.getByLabel(/at most \(seconds\)/).fill("0");
  await page.getByRole("button", { name: "Save settings" }).click();
  await status(page, "Saved.");
  await page.getByRole("button", { name: "I understand and agree" }).click();
  await expect(page.getByText(/Acknowledged on/)).toBeVisible();
  await page.getByLabel("Connect my Gmail account").check();
  await page.getByLabel("Simulated Gmail address").fill("alex.example@example.com");
  await page.getByRole("button", { name: /Connect \(simulated, offline\)/ }).click();
  await expect(page.getByText(/Connected as/)).toBeVisible();

  await page.goto("/outreach");
  await page.getByRole("button", { name: "Prepare a new batch" }).click();
  await expect(page.getByRole("heading", { name: /I prepared 5 messages for you to review/ })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Nothing is sent until you approve/)).toBeVisible();
  await page.getByRole("button", { name: /Approve all ready \(5\)/ }).click();
  await page.getByRole("spinbutton", { name: "Messages" }).fill("5");
  await page.getByRole("spinbutton", { name: "Daily limit" }).fill("20");
  await page.getByRole("button", { name: "Confirm and approve" }).click();
  await status(page, /Approved 5 message/);

  await page.getByRole("tab", { name: "Sending" }).click();
  await page.getByRole("button", { name: "Send approved emails now" }).click();
  await status(page, /Sent 2/);

  await page.getByRole("tab", { name: "Manual-send queue" }).click();
  await expect(page.getByRole("link", { name: "Open LinkedIn profile" })).toHaveCount(3);
  await page.getByRole("button", { name: "I sent this" }).first().click();
  await status(page, /Marked as sent/);

  // ---------------------------------------------------------------- tracking, replies, dashboard
  await page.goto("/tracking");
  await expect(page.getByRole("button", { name: /^sent \(3\)/ })).toBeVisible();
  await page.getByRole("button", { name: /^sent \(3\)/ }).click();
  const emailRow = page.getByRole("row", { name: /email/ }).first();
  await expect(emailRow).toBeVisible();

  await page.goto("/outreach");
  await page.getByRole("tab", { name: "Sending" }).click();
  await page.getByRole("link", { name: "Open message" }).count();
  const sentList = await page.request.get("/api/outreach/messages?send_state=sent&page_size=5");
  const first = (await sentList.json()).items[0];
  await page.goto(`/outreach/${first.id}`);
  await page.getByLabel("Reply text").fill("Happy to refer you, send your resume.");
  await page.getByRole("button", { name: "Record reply" }).click();
  await status(page, /Recorded as: referral offered/);

  await page.goto("/dashboard");
  await expect(page.locator("dt", { hasText: "Messages sent" }).locator("xpath=following-sibling::dd")).toHaveText("3");
  await expect(page.locator("dt", { hasText: "Referrals offered" }).locator("xpath=following-sibling::dd")).toHaveText("1");
  await expect(page.getByRole("img", { name: /3 outreach/ }).first()).toBeVisible();

  // ---------------------------------------------------------------- exports, diagnostics, guide
  const csv = await page.request.get("/api/exports/prospects.csv");
  expect(csv.status()).toBe(200);
  expect(await csv.text()).toContain("Rank,Tier,Score,Confidence");
  const xlsx = await page.request.get("/api/exports/prospects.xlsx");
  expect(xlsx.status()).toBe(200);
  await page.goto("/diagnostics");
  await expect(page.getByText(/mock HTTP only/).first()).toBeVisible();
  await expect(page.getByText(/disabled by design/)).toBeVisible();
  await page.goto("/guide");
  await expect(page.getByRole("heading", { name: "How ReferralOS works" })).toBeVisible();

  // ---------------------------------------------------------------- delete the account and everything in it
  await page.goto("/settings");
  page.once("dialog", (d) => d.accept());
  await page.getByLabel("Your password").fill(PASSWORD);
  await page.getByRole("button", { name: "Delete everything" }).click();
  await expect(page).toHaveURL(/\/signup/, { timeout: 30_000 });
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("#form-error")).toHaveText("Invalid email or password", { timeout: 20_000 }); // the account really is gone
});
