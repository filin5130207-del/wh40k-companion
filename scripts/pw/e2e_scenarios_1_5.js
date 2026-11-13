const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.ODOO_URL || "http://127.0.0.1:8069";
const DB = process.env.ODOO_DB || "wh40k";
const MEDIA =
  process.env.MEDIA_DIR ||
  "C:/Users/Павел/AppData/Local/Cursor/AgentStores/cursor_agent_stores/bc-b0114265-b6e6-437b-bd9a-f9def7ac969a/files/media/scenarios-1-5";
const ROSTER_JSON = path.resolve(__dirname, "../../testdata/aufychi.json");

fs.mkdirSync(MEDIA, { recursive: true });

const stamp = Date.now();
const host = {
  email: `host${stamp}@example.com`,
  password: "Password123!",
  nickname: `Host${stamp}`,
};
const guest = {
  email: `guest${stamp}@example.com`,
  password: "Password123!",
  nickname: `Guest${stamp}`,
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
    page.waitForURL(/\/wh40k(\?|$)/, { timeout: 20000 }),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForTimeout(1000);
  if (await page.locator(".wh40k-error").count()) {
    throw new Error("Signup error: " + (await page.locator(".wh40k-error").innerText()));
  }
}

async function login(page, user) {
  await page.goto(`${BASE}/web/login?db=${DB}`, { waitUntil: "domcontentloaded" });
  await page.fill("input[name=login]", user.email);
  await page.fill("input[name=password]", user.password);
  await Promise.all([
    page.waitForURL(/\/(web|odoo)(?!\/login)/, { timeout: 30000 }),
    page.click("button[type=submit]"),
  ]);
  await page.waitForTimeout(2000);
}

async function openCompanion(page) {
  // Resolve client action id
  const actionId = await page.evaluate(async () => {
    const res = await fetch("/web/dataset/call_kw/ir.model.data/check_object_reference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: {
          args: ["wh40k_companion", "action_wh40k_companion_client"],
          kwargs: {},
        },
        id: 1,
      }),
    });
    const j = await res.json();
    // returns [model, id]
    return j.result && j.result[1];
  });
  if (!actionId) {
    await page.goto(`${BASE}/wh40k/app`, { waitUntil: "domcontentloaded" });
  } else {
    // Odoo 20 prefers /odoo/action-<id>
    await page.goto(`${BASE}/odoo/action-${actionId}`, { waitUntil: "domcontentloaded" });
  }
  await page.waitForSelector(".wh40k-app", { timeout: 45000 });
  await page.waitForTimeout(1500);
}

async function jsonRpc(page, route, params) {
  return page.evaluate(
    async ({ route, params }) => {
      const res = await fetch(route, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", method: "call", params, id: Date.now() }),
      });
      const j = await res.json();
      if (j.error) throw new Error(JSON.stringify(j.error));
      return j.result;
    },
    { route, params }
  );
}

(async () => {
  const results = {};
  const browser = await chromium.launch({ headless: true });
  const hostCtx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const guestCtx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const hostPage = await hostCtx.newPage();
  const guestPage = await guestCtx.newPage();

  try {
    // --- Scenario 1: registration + profile ---
    await hostPage.goto(`${BASE}/wh40k`, { waitUntil: "domcontentloaded" });
    await shot(hostPage, "01-landing.png");
    await signup(hostPage, host);
    await shot(hostPage, "01b-after-signup.png");
    await login(hostPage, host);
    await openCompanion(hostPage);
    // nickname already set during signup; dashboard should show rosters
    const dashText = await hostPage.textContent(".wh40k-app");
    if (!dashText.includes(host.nickname) && !dashText.includes("Командир") && !dashText.includes("Мои ростеры")) {
      throw new Error("Dashboard did not load after signup/login");
    }
    await shot(hostPage, "01-dashboard-after-register.png");
    results.s1 = "pass";

    // Guest signup (for later)
    await signup(guestPage, guest);
    await login(guestPage, guest);
    await openCompanion(guestPage);
    await shot(guestPage, "01c-guest-dashboard.png");

    // --- Scenario 2: import with preview ---
    const rosterRaw = fs.readFileSync(ROSTER_JSON, "utf8");
    // Use file chooser for host
    const [fileChooser] = await Promise.all([
      hostPage.waitForEvent("filechooser"),
      hostPage.click('input.wh40k-file'),
    ]);
    await fileChooser.setFiles(ROSTER_JSON);
    await hostPage.waitForSelector("text=Превью ростера", { timeout: 20000 });
    await shot(hostPage, "02-import-preview.png");
    const previewText = await hostPage.textContent(".wh40k-app");
    if (!/Ауфычи|aufychi/i.test(previewText)) {
      console.warn("Preview name may differ:", previewText.slice(0, 300));
    }
    await hostPage.click("text=Подтвердить импорт");
    await hostPage.waitForTimeout(3000);
    await shot(hostPage, "02-roster-list.png");
    results.s2 = "pass";

    // Import same roster for guest
    const [gChooser] = await Promise.all([
      guestPage.waitForEvent("filechooser"),
      guestPage.click('input.wh40k-file'),
    ]);
    await gChooser.setFiles(ROSTER_JSON);
    await guestPage.waitForSelector("text=Превью ростера", { timeout: 20000 });
    await guestPage.click("text=Подтвердить импорт");
    await guestPage.waitForTimeout(3000);

    // --- Scenario 3: host create match + QR + countdown ---
    await hostPage.locator("nav.wh40k-nav button", { hasText: "Создать матч" }).click();
    await hostPage.waitForTimeout(1000);
    await shot(hostPage, "03-create-form.png");
    // select 2000 (default), Purge the Foe, first roster
    const purge = hostPage.locator("button.wh40k-list-item", { hasText: "Purge the Foe" });
    if (await purge.count()) await purge.first().click();
    const rosterBtn = hostPage.locator("section.wh40k-panel button.wh40k-list-item").filter({ hasText: /pts/ }).first();
    await rosterBtn.click();
    await hostPage.locator("button.wh40k-btn-primary", { hasText: "Создать" }).click();
    await hostPage.waitForSelector("text=Ожидание противника", { timeout: 30000 });
    await hostPage.waitForSelector(".wh40k-countdown", { timeout: 10000 });
    await shot(hostPage, "03-waiting-qr-countdown.png");
    const countdown = await hostPage.textContent(".wh40k-countdown");
    console.log("countdown", countdown);
    if (!/^\d{2}:\d{2}$/.test((countdown || "").trim())) {
      throw new Error(`Bad countdown: ${countdown}`);
    }
    const joinUrl = await hostPage.textContent("code");
    console.log("joinUrl", joinUrl);
    results.s3 = "pass";
    results.joinUrl = joinUrl;

    // --- Scenario 4: guest QR join ---
    await guestPage.locator("nav.wh40k-nav button", { hasText: "Сканировать QR" }).click();
    await guestPage.waitForTimeout(500);
    await guestPage.fill("input.wh40k-input", joinUrl.trim());
    await guestPage.locator("button.wh40k-btn-primary", { hasText: "Проверить" }).click();
    await guestPage.waitForSelector("text=приглашает вас в матч", { timeout: 20000 });
    await shot(guestPage, "04-invite-card.png");
    await guestPage.click("text=Принять");
    await guestPage.waitForSelector("text=Подтвердить", { timeout: 20000 });
    await shot(guestPage, "04-select-roster.png");
    const guestRoster = guestPage.locator("button.wh40k-list-item").filter({ hasText: /pts/ }).first();
    await guestRoster.click();
    await guestPage.click("text=Подтвердить");
    await guestPage.waitForSelector("text=Закончить матч", { timeout: 30000 });
    await shot(guestPage, "04-guest-game.png");
    // host should enter game via poll
    await hostPage.waitForSelector("text=Закончить матч", { timeout: 45000 });
    await shot(hostPage, "04-host-game.png");
    results.s4 = "pass";

    // --- Scenario 5: surrender ---
    await guestPage.click("text=Закончить матч");
    await guestPage.waitForSelector("text=Вы уверены, что хотите сдаться?", { timeout: 10000 });
    await shot(guestPage, "05-surrender-modal.png");
    await guestPage.click("text=Да, сдаться");
    await guestPage.waitForSelector("text=Поражение", { timeout: 20000 });
    await shot(guestPage, "05-guest-result.png");
    await guestPage.click("text=На главный экран");
    await guestPage.waitForTimeout(2000);
    await shot(guestPage, "05-guest-home-stats.png");

    // host: poll may not auto-switch; refresh via surrender state by opening match or dashboard
    // Host still on game until they notice — trigger via state poll by clicking refresh if present,
    // or navigate dashboard and check wins. Force check via RPC.
    const hostDash = await jsonRpc(hostPage, "/wh40k/player/dashboard", {});
    console.log("host stats", hostDash.player);
    if (!(hostDash.player.wins >= 1)) {
      // try opening result by reloading match state if still in game
      console.warn("Host wins not yet 1; checking match finished via UI reload");
    }
    // Guest losses
    const guestDash = await jsonRpc(guestPage, "/wh40k/player/dashboard", {});
    console.log("guest stats", guestDash.player);
    if (!(guestDash.player.losses >= 1)) {
      throw new Error("Guest losses not updated");
    }
    if (!(hostDash.player.wins >= 1)) {
      throw new Error("Host wins not updated");
    }
    results.s5 = "pass";
    results.hostWins = hostDash.player.wins;
    results.guestLosses = guestDash.player.losses;
    results.hostWinRate = hostDash.player.win_rate;
    results.guestWinRate = guestDash.player.win_rate;

    fs.writeFileSync(path.join(MEDIA, "e2e-results.json"), JSON.stringify(results, null, 2));
    console.log("ALL_PASS", JSON.stringify(results));
    console.log(
      "FILES",
      fs.readdirSync(MEDIA).map((f) => `${f}:${fs.statSync(path.join(MEDIA, f)).size}`)
    );
  } catch (e) {
    console.error("E2E_FAIL", e);
    try {
      await shot(hostPage, "zz-host-error.png");
      await shot(guestPage, "zz-guest-error.png");
    } catch (_) {}
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
