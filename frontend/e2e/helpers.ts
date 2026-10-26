import fs from "node:fs";
import path from "node:path";
import { expect, Page } from "@playwright/test";

export const SAMPLES = path.resolve(__dirname, "../../samples");
export const PASSWORD = "correct-horse-9";

export function latestToken(to: string): string {
  const dir = path.join(process.env.E2E_DIR!, "outbox");
  for (const f of fs.readdirSync(dir).sort().reverse()) {
    const m = JSON.parse(fs.readFileSync(path.join(dir, f), "utf-8"));
    if (m.to === to) return m.body.split(": ").pop() as string;
  }
  throw new Error("no mail for " + to);
}

/** Creates a verified user through the real API and signs in through the real login form. */
export async function newUser(page: Page, tag: string): Promise<string> {
  const email = `${tag}.${Date.now()}@example.com`;
  expect((await page.request.post("/api/auth/signup", { data: { email, password: PASSWORD } })).status()).toBe(201);
  expect((await page.request.post("/api/auth/verify", { data: { token: latestToken(email) } })).status()).toBe(200);
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  return email;
}

export const csrf = async (page: Page) => (await page.context().cookies()).find((c) => c.name === "csrf")?.value ?? "";

/** Fills an account with a resume, contacts, a job board and matches so list pages have real content. */
export async function seed(page: Page) {
  const h = { "X-CSRF-Token": await csrf(page) };
  await page.request.post("/api/profile/items", { headers: h, data: { section: "personal", data: { name: "Alex Example", email: "alex.example@example.com", links: [] } } });
  await page.request.post("/api/imports", { headers: h, multipart: { kind: "linkedin", file: { name: "c.csv", mimeType: "text/csv", buffer: fs.readFileSync(path.join(SAMPLES, "contacts/linkedin_connections_sample.csv")) } } })
    .then(async (r) => { const j = await r.json(); await page.request.post(`/api/imports/${j.import_id}/start`, { headers: h, data: {} }); });
  await page.request.post("/api/boards", { headers: h, data: { company: "Acme Test Co", ats: "greenhouse", token: "acme-test" } });
  await page.request.post("/api/jobs/discover", { headers: h, data: {} });
}
