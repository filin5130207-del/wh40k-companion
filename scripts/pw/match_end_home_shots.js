const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.ODOO_URL || "http://127.0.0.1:8069";
const DB = process.env.ODOO_DB || "wh40k";
const MEDIA =
  process.env.MEDIA_DIR ||
  "C:/Users/Павел/AppData/Local/Cursor/AgentStores/cursor_agent_stores/bc-b0114265-b6e6-437b-bd9a-f9def7ac969a/files/media/match-end-home";
const ROSTER_JSON = path.resolve(__dirname, "../../testdata/aufychi.json");

fs.mkdirSync(MEDIA, { recursive: true });

const stamp = Date.now();
const host = {
  email: `meh${stamp}@example.com`,
  password: "Password123!",
  nickname: `MeHost${stamp}`,
};
const guest = {
  email: `meg${stamp}@example.com`,
  password: "Password123!",
  nickname: `MeGuest${stamp}`,
};

function shot(page, name) {
  const out = path.join(MEDIA, name);
  return page.screenshot({ path: out, fullPage: true }).then(() => {
    const size = fs.statSync(out).size;
    console.log(`SHOT ${name} ${size}b`);
    if (size < 1000) throw new Error(`Screenshot too small: ${name}`);
    return out;
  });
}

async function signup(page, user) {
  await page.goto(`${BASE}/wh40k/signup`, { waitUntil: "domcontentloaded" });
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);
  await page.fill('input[name="nickname"]', user.nickname);
  await Promise.all([
    page.waitForURL(/\/(wh40k|odoo|web)/, { timeout: 30000 }),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForTimeout(800);
}

async function openCompanion(page) {
  await page.goto(`${BASE}/wh40k/app`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".wh40k-app", { timeout: 45000 });
  await page.waitForSelector("nav.wh40k-bottom-nav", { timeout: 20000 });
  await page.waitForTimeout(800);
}

async function importRoster(page) {
  await page.locator("nav.wh40k-bottom-nav button", { hasText: "Ростеры" }).click();
  await page.waitForSelector("text=Мои ростеры", { timeout: 10000 });
  const [fc] = await Promise.all([
    page.waitForEvent("filechooser"),
    page.click("input.wh40k-file"),
  ]);
  await fc.setFiles(ROSTER_JSON);
  await page.waitForSelector("text=Превью ростера", { timeout: 20000 });
  await page.click("text=Подтвердить импорт");
  await page.waitForTimeout(2500);
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const hostCtx = await browser.newContext({ viewport: { width: 420, height: 860 } });
  const guestCtx = await browser.newContext({ viewport: { width: 420, height: 860 } });
  const hostPage = await hostCtx.newPage();
  const guestPage = await guestCtx.newPage();
  const pageErrors = [];
  for (const p of [hostPage, guestPage]) {
    p.on("pageerror", (err) => pageErrors.push(String(err)));
    p.on("console", (msg) => {
      if (msg.type() === "error") pageErrors.push(`console:${msg.text()}`);
    });
  }

  try {
    await signup(hostPage, host);
    await openCompanion(hostPage);
    await importRoster(hostPage);

    await signup(guestPage, guest);
    await openCompanion(guestPage);
    await importRoster(guestPage);

    // Host create match
    await hostPage.locator("nav.wh40k-bottom-nav button", { hasText: "Матч" }).click();
    await hostPage.waitForSelector("text=Создать матч", { timeout: 15000 });
    const purge = hostPage.locator("button.wh40k-list-item", { hasText: "Purge the Foe" });
    if (await purge.count()) await purge.first().click();
    await hostPage.locator("section.wh40k-panel button.wh40k-list-item").filter({ hasText: /pts/ }).first().click();
    await hostPage.locator("button.wh40k-btn-primary", { hasText: "Создать" }).click();
    await hostPage.waitForSelector("text=Ожидание противника", { timeout: 30000 });
    const joinUrl = (await hostPage.textContent("code")).trim();
    console.log("JOIN", joinUrl);

    // Guest deep-link join (same path as QR → /wh40k/join/<token> → #wh40k_join=)
    await guestPage.goto(joinUrl, { waitUntil: "domcontentloaded" });
    await guestPage.waitForSelector(".wh40k-app", { timeout: 45000 });
    // TourInteractive crash would show Oops! dialog
    const oops = await guestPage.locator("text=Oops!").count();
    const tourErr = await guestPage.locator("text=TourInteractive").count();
    console.log("OOPS", oops, "TOUR_ERR_UI", tourErr);
    if (oops > 0 || tourErr > 0) {
      await shot(guestPage, "zz-tour-crash.png");
      throw new Error("TourInteractive crash dialog visible after QR join deep link");
    }
    await guestPage.waitForSelector("text=приглашает вас в матч", { timeout: 30000 });
    await shot(guestPage, "01-deeplink-invite-no-tour-crash.png");
    await guestPage.click("text=Принять");
    await guestPage.waitForSelector("text=Подтвердить", { timeout: 20000 });
    await guestPage.locator("button.wh40k-list-item").filter({ hasText: /pts/ }).first().click();
    await guestPage.click("text=Подтвердить");
    await guestPage.waitForSelector("text=Закончить матч", { timeout: 30000 });
    await hostPage.waitForSelector("text=Закончить матч", { timeout: 45000 });
    await shot(hostPage, "02-host-game.png");
    await shot(guestPage, "03-guest-game.png");

    // Guest surrenders → both should land on home dashboard with nav
    await guestPage.click("text=Закончить матч");
    await guestPage.waitForSelector("text=Вы уверены, что хотите сдаться?", { timeout: 10000 });
    await guestPage.click("text=Да, сдаться");
    await guestPage.waitForSelector("text=Личный кабинет", { timeout: 20000 });
    await guestPage.waitForSelector("nav.wh40k-bottom-nav", { timeout: 10000 });
    await guestPage.waitForSelector(".wh40k-result-banner", { timeout: 10000 });
    await shot(guestPage, "04-guest-home-after-surrender.png");

    // Host is notified via poll → home
    await hostPage.waitForSelector("text=Личный кабинет", { timeout: 45000 });
    await hostPage.waitForSelector("nav.wh40k-bottom-nav", { timeout: 10000 });
    await hostPage.waitForSelector(".wh40k-result-banner", { timeout: 15000 });
    await shot(hostPage, "05-host-home-after-opponent-surrender.png");

    // Neither stuck on result-only screen without nav
    const guestResultOnly = await guestPage.locator(".wh40k-app >> text=На главный экран").count();
    const hostResultOnly = await hostPage.locator(".wh40k-app >> text=На главный экран").count();
    if (guestResultOnly || hostResultOnly) {
      throw new Error("Player still on dedicated result screen");
    }
    if (!(await guestPage.locator("nav.wh40k-bottom-nav").count())) {
      throw new Error("Guest missing bottom nav on home");
    }
    if (!(await hostPage.locator("nav.wh40k-bottom-nav").count())) {
      throw new Error("Host missing bottom nav on home");
    }

    const tourCrashes = pageErrors.filter((e) => /TourInteractive|resumeTour/i.test(e));
    console.log("PAGE_ERRORS", pageErrors.slice(0, 20));
    if (tourCrashes.length) {
      throw new Error(`Tour crash in page errors: ${tourCrashes.join(" | ")}`);
    }
    console.log("MATCH_END_HOME_PASS");
  } catch (e) {
    console.error("MATCH_END_HOME_FAIL", e);
    try {
      await shot(hostPage, "zz-host-error.png");
      await shot(guestPage, "zz-guest-error.png");
    } catch (_) {}
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main();
