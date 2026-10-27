/* Browser smoke test against an isolated AgentOS server and database.
   npm-installed Playwright or PLAYWRIGHT_MODULE_PATH is needed.
   Chromium is the default; set AGENTOS_BROWSER_CHANNEL=msedge for installed Edge.
   AGENTOS_TEST_URL defaults to http://127.0.0.1:8000.
   AGENTOS_TEST_TOKEN must match the isolated server's AGENTOS_API_TOKEN. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { withBrowser } = require('./browser-support.cjs');
const out = path.resolve(__dirname, '../.verification/dashboard');
const snapshotOut = path.resolve(__dirname, '../.verification/expressive-final');
const snapshotManifest = [];
let snapshotAssetsReady = false;
fs.mkdirSync(out, { recursive: true });

async function connect(page, url, token) {
  await page.goto(url);
  await page.locator('#access-token').fill(token);
  await page.locator('#connect-button').click();
  await page.locator('#workspace').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.getElementById('task-list').getAttribute('aria-busy') === 'false');
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  await page.waitForFunction(() => document.getElementById('planner').getAttribute('aria-busy') === 'false');
  await page.evaluate(() => document.fonts.ready);
}

async function create(page, goal, preview = false, approval = false) {
  await page.locator('#goal').fill(goal);
  await page.locator('#require-approval').setChecked(approval);
  const responsePromise = page.waitForResponse((response) => response.url().endsWith('/api/tasks') && response.request().method() === 'POST');
  await page.locator(preview ? '#preview-button' : '#run-button').click();
  const response = await responsePromise;
  assert.equal(response.status(), 201);
  const task = await response.json();
  await page.waitForFunction(() => !document.getElementById('run-button').disabled);
  await page.locator('#task-detail .detail-title').waitFor({ state: 'visible' });
  assert.equal(await page.locator('#task-detail .detail-title').textContent(), goal);
  return task;
}

async function action(page, label, taskId, endpoint) {
  const responsePromise = page.waitForResponse((response) => response.url().endsWith(`/api/tasks/${taskId}/${endpoint}`) && response.request().method() === 'POST');
  await page.getByRole('button', { name: label, exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 200);
  const task = await response.json();
  await page.waitForFunction(() => [...document.querySelectorAll('.detail-actions button')].every((button) => !button.disabled));
  return task;
}

async function assertApprovalCall(page, task) {
  const next = task.steps[task.current_step];
  assert.equal(await page.locator('.approval-tool').textContent(), next.tool_name);
  assert.deepEqual(JSON.parse(await page.locator('.approval-args').textContent()), next.tool_args, 'The approval panel must show the exact next call, including unresolved references');
  assert.equal(await page.locator('.approval-call').isVisible(), true);
}

async function capture(page, width, name) {
  await page.setViewportSize({ width, height: width > 1100 ? 900 : width > 600 ? 1024 : 844 });
  await page.evaluate(() => { window.scrollTo(0, 0); });
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true, animations: 'disabled' });
  const measured = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, fonts: document.fonts.check('14px "IBM Plex Sans"') }));
  assert.ok(measured.scrollWidth <= measured.width + 1, `${name} page overflows horizontally: ${JSON.stringify(measured)}`);
  assert.ok(measured.fonts, 'IBM Plex Sans must load');
  if (name.startsWith('theme-')) {
    if (!snapshotAssetsReady) {
      const assets = path.join(snapshotOut, 'assets');
      const web = path.resolve(__dirname, '../agent_engine/web');
      fs.mkdirSync(path.join(assets, 'fonts'), { recursive: true });
      fs.writeFileSync(path.join(assets, 'styles.css'), fs.readFileSync(path.join(web, 'styles.css'), 'utf8').replaceAll('/static/fonts/', './fonts/'));
      for (const font of ['ibm-plex-sans.ttf', 'ibm-plex-mono.ttf']) fs.copyFileSync(path.join(web, 'fonts', font), path.join(assets, 'fonts', font));
      fs.copyFileSync(path.join(web, 'favicon.svg'), path.join(assets, 'favicon.svg'));
      snapshotAssetsReady = true;
    }
    const html = await page.evaluate(() => {
      const documentCopy = document.documentElement.cloneNode(true);
      documentCopy.querySelectorAll('script, [hidden], link[rel="preload"]').forEach((node) => node.remove());
      documentCopy.querySelectorAll('link[rel="stylesheet"]').forEach((node) => node.setAttribute('href', 'assets/styles.css'));
      documentCopy.querySelectorAll('link[rel="icon"]').forEach((node) => node.setAttribute('href', 'assets/favicon.svg'));
      return '<!doctype html>\n' + documentCopy.outerHTML;
    });
    fs.copyFileSync(path.join(out, `${name}.png`), path.join(snapshotOut, `${name}.png`));
    fs.writeFileSync(path.join(snapshotOut, `${name}.html`), html);
    snapshotManifest.push({ name, width, theme: await page.locator('html').getAttribute('data-theme') });
    fs.writeFileSync(path.join(snapshotOut, 'manifest.json'), JSON.stringify({ capturedAt: new Date().toISOString(), states: snapshotManifest }, null, 2) + '\n');
  }
}

async function setTheme(page, theme) {
  if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme-toggle').click();
  await page.waitForFunction((value) => document.documentElement.dataset.theme === value, theme);
  assert.equal(await page.locator('#theme-toggle').getAttribute('aria-label'), 'Dark mode');
  assert.equal(await page.locator('#theme-toggle').getAttribute('aria-pressed'), String(theme === 'dark'));
  assert.equal((await page.locator('#theme-label').textContent()).trim(), 'Dark mode');
}

async function assertReadable(page) {
  const failures = await page.evaluate(() => {
    const rgb = (value) => {
      const channels = value.match(/[\d.]+/g).map(Number);
      return [...channels.slice(0, 3), channels[3] ?? 1];
    };
    const over = (foreground, background) => foreground.slice(0, 3).map((value, index) => value * foreground[3] + background[index] * (1 - foreground[3]));
    const luminance = (color) => color.map((value) => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
    const selectors = ['#goal', '#planner-hint', '.detail-error', '.approval-explanation', '.step-state', '.step-description', '.step-output', '.status', '.form-message', '.form-error', '.recovery-hint', '.detail-result strong', '#registered-tools code', '.tool-item p'];
    const failed = [];
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        if (!node.checkVisibility() || node.matches(':disabled')) continue;
        const style = getComputedStyle(node);
        const ancestors = [];
        for (let parent = node; parent; parent = parent.parentElement) ancestors.unshift(parent);
        let background = [255, 255, 255];
        for (const ancestor of ancestors) background = over(rgb(getComputedStyle(ancestor).backgroundColor), background);
        const foreground = over(rgb(node.placeholder && !node.value ? getComputedStyle(node, '::placeholder').color : style.color), background);
        const lights = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
        const ratio = (lights[0] + 0.05) / (lights[1] + 0.05);
        const large = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700);
        if (ratio + 0.02 < (large ? 3 : 4.5)) failed.push({ selector, text: (node.textContent || node.placeholder).slice(0, 90), contrast: Number(ratio.toFixed(2)), theme: document.documentElement.dataset.theme });
      }
    }
    return failed;
  });
  assert.deepEqual(failures, [], 'Visible hints, warnings, errors, tool text, and result colors must remain readable');
}

async function captureThemes(page, name, { detail = false } = {}) {
  const viewport = page.viewportSize();
  const theme = await page.locator('html').getAttribute('data-theme');
  const detailWasOpen = await page.locator('#tasks-view').evaluate((node) => node.classList.contains('detail-visible'));
  for (const mode of ['light', 'dark']) {
    await setTheme(page, mode);
    for (const width of [1440, 768, 390]) {
      if (detail) await page.locator('#tasks-view').evaluate((node) => node.classList.add('detail-visible'));
      await capture(page, width, `theme-${mode}-${name}-${width}`);
      await assertReadable(page);
    }
  }
  await page.locator('#tasks-view').evaluate((node, open) => node.classList.toggle('detail-visible', open), detailWasOpen);
  await page.setViewportSize(viewport);
  await setTheme(page, theme);
}

async function plannerModes(browser, url, token) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.route('**/api/planner', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ default: 'local', openai_available: true, model: 'browser-test-model-with-a-long-deployment-name', message: null }),
    }));
    await connect(page, url, token);
    assert.equal(await page.locator('#planner').inputValue(), 'local');
    assert.equal(await page.locator('#planner-openai').isDisabled(), false);
    await page.locator('#require-approval').uncheck();
    await page.locator('#planner').selectOption('openai');
    assert.equal(await page.locator('#require-approval').isChecked(), true);
    assert.equal(await page.locator('#require-approval').isDisabled(), true);
    assert.match(await page.locator('#planner-hint').textContent(), /sent to.*AI provider/i);
    await page.locator('#planner').selectOption('local');
    assert.equal(await page.locator('#require-approval').isChecked(), false, 'Returning to local restores its approval preference');
    assert.equal(await page.locator('#require-approval').isDisabled(), false);
    await page.locator('#planner').selectOption('openai');
    await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    await page.waitForFunction(() => document.getElementById('planner').getAttribute('aria-busy') === 'false');
    assert.equal(await page.locator('#planner').inputValue(), 'openai', 'Refreshing must preserve the selected planner');
    await capture(page, 1440, 'planner-ai-desktop');
    await capture(page, 768, 'planner-ai-tablet');
    await page.setViewportSize({ width: 390, height: 844 });
    if (!await page.locator('#goal').isVisible()) await page.locator('#mobile-new-task').click();
    await capture(page, 390, 'planner-ai-mobile');
    await page.setViewportSize({ width: 1440, height: 900 });

    let submitted;
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      submitted = route.request().postDataJSON();
      // Exercise the UI contract using a real local workflow, without contacting an AI provider.
      const response = await route.fetch({ postData: JSON.stringify({ ...submitted, planner: 'local' }) });
      await route.fulfill({ response });
    });
    await page.locator('#goal').fill('calculate (2 + 3) * 4');
    const created = page.waitForResponse((response) => response.url().endsWith('/api/tasks') && response.request().method() === 'POST');
    await page.locator('#run-button').click();
    const waiting = await (await created).json();
    await page.waitForFunction(() => !document.getElementById('run-button').disabled);
    assert.equal(submitted.planner, 'openai');
    assert.equal(submitted.require_approval, true);
    assert.equal(waiting.status, 'waiting_for_approval');
    assert.ok(waiting.steps.every((step) => step.requires_approval));
    await page.unroute('**/api/tasks');

    await page.unroute('**/api/planner');
    await page.route('**/api/planner', (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Planner configuration unavailable.' }) }));
    await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    await page.waitForFunction(() => document.getElementById('planner').getAttribute('aria-busy') === 'false');
    assert.equal(await page.locator('#planner').inputValue(), 'local');
    assert.equal(await page.locator('#planner-openai').isDisabled(), true);
    assert.equal(await page.locator('#planner-hint').isVisible(), true);
    await page.setViewportSize({ width: 390, height: 844 });
    if (!await page.locator('#goal').isVisible()) await page.locator('#mobile-new-task').click();
    await capture(page, 390, 'planner-unavailable-mobile');
    await page.setViewportSize({ width: 1440, height: 900 });
    const local = await create(page, 'add 4 and 5');
    assert.equal(local.status, 'completed', 'Local planning remains usable when planner metadata cannot load');
    assert.equal(Number(local.result), 9);

    await page.unroute('**/api/planner');
    await page.route('**/api/planner', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ default: null, openai_available: true, model: 'test-model', message: 'AGENTOS_PLANNER must be local or openai.', timeout_seconds: 20 }),
    }));
    await connect(page, url, token);
    assert.equal(await page.locator('#planner').inputValue(), 'local', 'An invalid server default must select local initially');
    assert.equal(await page.locator('#planner-openai').isDisabled(), false, 'A valid AI provider remains selectable despite an invalid default');
    assert.match(await page.locator('#planner-hint').textContent(), /AGENTOS_PLANNER.*Local is selected for this task/);
    await page.locator('#planner').selectOption('openai');
    assert.match(await page.locator('#planner-hint').textContent(), /AGENTOS_PLANNER.*sent to.*AI provider/i);
    assert.equal(await page.locator('#require-approval').isChecked(), true);
    assert.equal(await page.locator('#require-approval').isDisabled(), true);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
}

async function dashboardPolish(browser, url, token) {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  const submissions = [];
  const deferred = () => {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return { promise, resolve };
  };
  let flight = { captured: deferred(), release: deferred() };
  const settled = () => page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  const openComposer = async () => {
    if (await page.locator('.mobile-back').isVisible()) await page.locator('.mobile-back').click();
    if (!await page.locator('#goal').isVisible()) await page.locator('#mobile-new-task').click();
  };
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/tasks') submissions.push(request.postDataJSON());
  });
  try {
    await page.route('**/api/planner', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ default: 'local', openai_available: true, model: 'browser-test-model', message: null, timeout_seconds: 20 }),
    }));
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST') return route.continue();
      const body = route.request().postDataJSON();
      if (body.planner !== 'openai') return route.continue();
      const pending = flight;
      // Persist a real unsupported local plan to exercise the AI failure UI without a provider.
      const response = await route.fetch({ postData: JSON.stringify({ ...body, planner: 'local' }) });
      pending.captured.resolve();
      await pending.release.promise;
      await route.fulfill({ response });
    });
    await connect(page, url, token);
    const catalogResponse = await page.request.get(`${url}/api/tools`, { headers: { Authorization: `Bearer ${token}` } });
    const catalog = await catalogResponse.json();
    assert.deepEqual((await page.locator('#registered-tools code').allTextContents()).sort(), catalog.tools.map((tool) => tool.name).sort(), 'Composer capabilities must come from the actual registry');
    await openComposer();
    await page.locator('#require-approval').uncheck();
    await page.locator('#planner').selectOption('openai');
    const unsupported = 'Please work out seven plus three, then double it.';
    await page.locator('#goal').fill(unsupported);
    const created = page.waitForResponse((response) => response.url().endsWith('/api/tasks') && response.request().method() === 'POST');
    await page.locator('#run-button').click();
    await flight.captured.promise;
    assert.equal(await page.locator('#composer-progress').isVisible(), true, 'A slow creation request must show progress');
    assert.equal(await page.locator('#composer-progress').getAttribute('role'), 'status');
    assert.match(await page.locator('#composer-progress').textContent(), /planning|AI|tool/i);
    for (const control of ['#run-button', '#preview-button', '#planner', '#goal']) assert.equal(await page.locator(control).isDisabled(), true, `${control} must be disabled during creation`);
    await capture(page, 390, 'polish-planning-mobile');
    await captureThemes(page, 'ai-loading');
    flight.release.resolve();
    const failed = await (await created).json();
    assert.equal(failed.status, 'failed');
    assert.equal(failed.steps.length, 0);
    await page.waitForFunction(() => !document.getElementById('run-button').disabled);
    assert.equal(await page.locator('#composer-progress').evaluate((node) => node.hidden), true);
    assert.equal((await page.locator('#composer-progress').textContent()).trim(), '');
    assert.equal(await page.locator('[data-action="edit-local"]').isVisible(), true);
    await capture(page, 390, 'polish-failed-mobile');

    const beforeRecovery = submissions.length;
    await page.locator('[data-action="edit"]').click();
    assert.equal(await page.locator('#goal').isVisible(), true, 'Edit goal opens the mobile composer');
    assert.equal(await page.locator('#goal').inputValue(), unsupported);
    assert.equal(await page.locator('#planner').inputValue(), 'openai', 'Edit goal preserves the selected planner');
    assert.equal(submissions.length, beforeRecovery, 'Editing a failed task must not submit it');
    const draft = 'add 90 and 10';
    await page.locator('#goal').fill(draft);
    await page.locator(`[data-task-id="${failed.task_id}"]`).click();
    await page.locator('[data-action="edit-local"]').click();
    assert.equal(await page.locator('#goal').isVisible(), true);
    assert.equal(await page.locator('#goal').inputValue(), draft, 'Recovery must preserve a different draft');
    assert.equal(await page.locator('#planner').inputValue(), 'openai', 'A draft conflict must preserve its planner');
    assert.match(await page.locator('#composer-message').textContent(), /clear.*draft|draft.*clear/i);
    assert.equal(submissions.length, beforeRecovery);
    await capture(page, 390, 'polish-draft-conflict-mobile');
    await page.locator('#goal').fill('');
    await page.locator(`[data-task-id="${failed.task_id}"]`).click();
    await page.locator('[data-action="edit-local"]').click();
    assert.equal(await page.locator('#goal').inputValue(), unsupported);
    assert.equal(await page.locator('#planner').inputValue(), 'local');
    assert.equal(await page.locator('#require-approval').isChecked(), false);
    assert.equal(submissions.length, beforeRecovery, 'Use local only changes the draft; it must never run it');
    const recovered = await create(page, 'calculate (7 + 3) * 2');
    assert.equal(recovered.status, 'completed');
    assert.equal(Number(recovered.result), 20);
    assert.equal(submissions.at(-1).planner, 'local');
    await capture(page, 390, 'polish-recovered-mobile');

    await openComposer();
    await page.locator('#planner').selectOption('openai');
    await page.locator('#goal').fill('Please plan a different unsupported workflow.');
    flight = { captured: deferred(), release: deferred() };
    const delayed = page.waitForResponse((response) => response.url().endsWith('/api/tasks') && response.request().method() === 'POST');
    await page.locator('#run-button').click();
    await flight.captured.promise;
    assert.equal(await page.locator('#composer-progress').isVisible(), true);
    await page.locator('#mobile-disconnect').click();
    assert.equal(await page.locator('#composer-progress').evaluate((node) => node.hidden), true);
    assert.equal((await page.locator('#composer-progress').textContent()).trim(), '');
    flight.release.resolve();
    await delayed;
    await settled();
    assert.equal(await page.locator('#workspace').isVisible(), false, 'A late creation response must not reconnect the workspace');
    assert.equal(await page.locator('.task-row').count(), 0);
    assert.equal((await page.locator('#composer-progress').textContent()).trim(), '');

    await connect(page, url, token);
    await openComposer();
    await page.locator('#goal').fill('');
    const beforePress = submissions.length;
    const button = page.locator('#preview-button');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await button.focus();
    await page.keyboard.down('Space');
    assert.equal(await button.evaluate((node) => node.classList.contains('is-pressed')), false, 'Keyboard input must not trigger pointer press feedback');
    assert.equal(await button.evaluate((node) => getComputedStyle(node).transform), 'none');
    await page.keyboard.up('Space');
    const press = async () => {
      const box = await button.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForFunction(() => document.getElementById('preview-button').classList.contains('is-pressed'));
    };
    const release = async () => {
      await page.mouse.move(0, 0);
      await page.mouse.up();
      await page.waitForFunction(() => !document.getElementById('preview-button').classList.contains('is-pressed'));
    };
    await press();
    await page.waitForFunction(() => getComputedStyle(document.getElementById('preview-button')).transform !== 'none');
    await release();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    // The preceding release can still be mid-transition when CDP changes the preference.
    // Wait for that rendered state to settle before testing a new reduced-motion press.
    await page.waitForFunction(() => matchMedia('(prefers-reduced-motion: reduce)').matches && getComputedStyle(document.getElementById('preview-button')).transform === 'none');
    await press();
    assert.equal(await button.evaluate((node) => getComputedStyle(node).transform), 'none', 'Reduced motion must disable the press transform');
    await release();
    assert.equal(submissions.length, beforePress, 'Press-feedback checks must not submit an empty goal');
    assert.deepEqual(errors, []);
  } finally {
    flight.release.resolve();
    await page.close();
  }
}

async function themeBehavior(browser, url, token) {
  const context = await browser.newContext({ colorScheme: 'dark', reducedMotion: 'reduce' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.__firstThemeFrame = null;
    requestAnimationFrame(() => { window.__firstThemeFrame = document.documentElement.dataset.theme; });
  });
  try {
    await page.goto(url);
    await page.waitForFunction(() => window.__firstThemeFrame !== null);
    assert.equal(await page.evaluate(() => window.__firstThemeFrame), 'dark', 'The OS theme must be applied before the first rendered frame');
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    assert.equal(await page.evaluate(() => localStorage.length), 0, 'Following the OS must not create a stored preference');
    await page.emulateMedia({ colorScheme: 'light' });
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await setTheme(page, 'light');
    assert.equal(await page.evaluate(() => localStorage.getItem('agentos.theme')), 'light');
    await page.emulateMedia({ colorScheme: 'light' });
    await page.emulateMedia({ colorScheme: 'dark' });
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light', 'An explicit preference overrides later OS changes');
    await page.reload();
    await page.waitForFunction(() => window.__firstThemeFrame !== null);
    assert.equal(await page.evaluate(() => window.__firstThemeFrame), 'light', 'A saved preference must apply on the first reload frame');
    await page.locator('#access-token').fill('invalid-theme-test-token');
    await page.locator('#connect-button').click();
    await page.locator('#connect-error').waitFor({ state: 'visible' });
    await captureThemes(page, 'connect-error');
    await connect(page, url, token);
    await setTheme(page, 'dark');
    const stored = await page.evaluate(() => ({ entries: Object.entries(localStorage), session: Object.entries(sessionStorage), html: document.documentElement.innerHTML }));
    assert.deepEqual(stored.entries, [['agentos.theme', 'dark']], 'Only the theme preference belongs in persistent browser storage');
    assert.deepEqual(stored.session, []);
    assert.equal(JSON.stringify(stored).includes(token), false, 'The access token must not appear in storage or the DOM');
    await page.locator('#disconnect').click();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark', 'Disconnect must preserve the theme');
    await page.reload();
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    assert.equal(await page.locator('#connect-view').isVisible(), true);
    assert.equal(await page.locator('#workspace').isVisible(), false);
    assert.deepEqual(errors, []);
  } finally { await context.close(); }

  const blocked = await browser.newContext({ colorScheme: 'dark', reducedMotion: 'reduce' });
  const blockedPage = await blocked.newPage();
  const blockedErrors = [];
  blockedPage.on('pageerror', (error) => blockedErrors.push(error.message));
  await blockedPage.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('Storage is blocked.', 'SecurityError'); } });
  });
  try {
    await blockedPage.goto(url);
    await blockedPage.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await blockedPage.emulateMedia({ colorScheme: 'light' });
    await blockedPage.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    await setTheme(blockedPage, 'dark');
    await blockedPage.emulateMedia({ colorScheme: 'dark' });
    await blockedPage.emulateMedia({ colorScheme: 'light' });
    assert.equal(await blockedPage.locator('html').getAttribute('data-theme'), 'dark', 'An in-memory preference must still work when storage is blocked');
    await blockedPage.reload();
    await blockedPage.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    await connect(blockedPage, url, token);
    assert.equal(await blockedPage.locator('#workspace').isVisible(), true, 'Blocked theme storage must not prevent authentication');
    assert.deepEqual(blockedErrors, []);
  } finally { await blocked.close(); }
}

async function taskMotion(browser, url, token) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'no-preference' });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => {
    window.__animationRuns = [];
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (...args) {
      const animation = animate.apply(this, args);
      const entry = { animation, target: this, cancelled: false, finished: false };
      animation.addEventListener('cancel', () => { entry.cancelled = true; });
      animation.addEventListener('finish', () => { entry.finished = true; });
      window.__animationRuns.push(entry);
      return animation;
    };
  });
  const gate = () => {
    let captured, release;
    return {
      captured: new Promise((resolve) => { captured = resolve; }),
      released: new Promise((resolve) => { release = resolve; }),
      capture: () => captured(), release: () => release(),
    };
  };
  let flight = gate();
  let delayNext = true;
  const mark = () => page.evaluate(() => window.__animationRuns.length);
  const since = (index) => page.evaluate((start) => window.__animationRuns.slice(start).filter((entry) => /^agentos-(step|result|summary)-/.test(entry.animation.id)).map((entry) => entry.animation.id), index);
  try {
    await page.route('**/api/tasks', async (route) => {
      if (route.request().method() !== 'POST' || !delayNext) return route.continue();
      delayNext = false;
      const pending = flight;
      const response = await route.fetch();
      pending.capture();
      await pending.released;
      await route.fulfill({ response });
    });
    await connect(page, url, token);
    await page.locator('#goal').fill('calculate (7 + 3) * 2');
    const beforeRun = await mark();
    const firstResponse = page.waitForResponse((response) => response.url().endsWith('/api/tasks') && response.request().method() === 'POST');
    await page.locator('#run-button').click();
    await flight.captured;
    assert.equal(await page.locator('#composer-progress').isVisible(), true);
    flight.release();
    await page.waitForFunction((start) => window.__animationRuns.slice(start).some((entry) => entry.animation.id === 'agentos-step-enter'), beforeRun);
    const moving = await page.evaluate(() => document.getAnimations().filter((animation) => /^agentos-(step|result|summary)-/.test(animation.id) && animation.playState === 'running').map((animation) => ({ id: animation.id, keyframes: animation.effect.getKeyframes(), duration: animation.effect.getComputedTiming().duration })));
    assert.ok(moving.some((animation) => animation.id === 'agentos-step-enter'), 'A real pointer Run task must animate the arriving steps');
    assert.ok(moving.every((animation) => animation.duration > 0));
    assert.ok(moving.some((animation) => animation.keyframes[0].opacity !== animation.keyframes.at(-1).opacity), 'The observed animation must visibly change the element');
    await page.keyboard.press('Escape');
    await page.waitForFunction((start) => window.__animationRuns.slice(start).some((entry) => entry.cancelled && !entry.finished), beforeRun);
    assert.equal(await page.evaluate(() => document.getAnimations().filter((animation) => animation.id.startsWith('agentos-')).length), 0, 'Keyboard input cancels in-flight authored motion');
    await firstResponse;
    await page.waitForFunction(() => !document.getElementById('run-button').disabled);
    const beforeRefresh = await mark();
    await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.deepEqual(await since(beforeRefresh), [], 'Refreshing an unchanged task must not replay its motion');

    const beforePreview = await mark();
    let waiting = await create(page, 'calculate (2 + 3) * 4', true, true);
    assert.ok((await since(beforePreview)).includes('agentos-step-enter'), 'Pointer Preview must animate the newly created plan');
    waiting = await action(page, 'Execute plan', waiting.task_id, 'execute');
    const beforeApproval = await mark();
    waiting = await action(page, 'Approve next step', waiting.task_id, 'approve');
    const approvalMotion = await since(beforeApproval);
    assert.ok(approvalMotion.includes('agentos-step-update'));
    assert.equal(approvalMotion.includes('agentos-step-enter'), false, 'Approval must not replay the entire plan');
    const beforeResult = await mark();
    const completed = await action(page, 'Approve next step', waiting.task_id, 'approve');
    assert.equal(completed.status, 'completed');
    const resultMotion = await since(beforeResult);
    assert.equal(resultMotion.filter((id) => id === 'agentos-result-update').length, 1, 'The new result animates once for its revision');

    await page.locator('#require-approval').uncheck();
    await page.locator('#goal').fill('add 4 and 6');
    const beforeKeyboard = await mark();
    const keyboardResponse = page.waitForResponse((response) => response.url().endsWith('/api/tasks') && response.request().method() === 'POST');
    await page.locator('#goal').focus();
    await page.keyboard.press('Control+Enter');
    assert.equal((await (await keyboardResponse).json()).status, 'completed');
    await page.waitForFunction(() => !document.getElementById('run-button').disabled);
    assert.deepEqual(await since(beforeKeyboard), [], 'Keyboard-created tasks must appear without entrance motion');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.waitForFunction(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
    const beforeReduced = await mark();
    const reducedTask = await create(page, 'multiply 3 by 5');
    assert.equal(reducedTask.status, 'completed');
    assert.deepEqual(await since(beforeReduced), [], 'Reduced motion disables task animations even for pointer actions');

    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await page.waitForFunction(() => !matchMedia('(prefers-reduced-motion: reduce)').matches);
    await page.locator('#goal').fill('add 8 and 9');
    flight = gate();
    delayNext = true;
    const beforeInterrupted = await mark();
    const interruptedResponse = page.waitForResponse((response) => response.url().endsWith('/api/tasks') && response.request().method() === 'POST');
    await page.locator('#run-button').click();
    await flight.captured;
    await page.keyboard.press('Tab');
    flight.release();
    await interruptedResponse;
    await page.waitForFunction(() => !document.getElementById('run-button').disabled);
    assert.deepEqual(await since(beforeInterrupted), [], 'Keyboard input while a response is delayed must invalidate its pending entrance motion');
    const evidence = await page.evaluate(() => window.__animationRuns.filter((entry) => entry.animation.id.startsWith('agentos-')).map((entry) => ({ id: entry.animation.id, target: entry.target.className, cancelled: entry.cancelled, finished: entry.finished, timing: entry.animation.effect.getTiming() })));
    fs.writeFileSync(path.join(out, 'motion-events.json'), JSON.stringify({ result: 'passed', moving, animations: evidence }, null, 2) + '\n');
    assert.deepEqual(errors, []);
  } finally {
    flight.release();
    await page.close();
  }
}

async function verifyDashboard({ url = process.env.AGENTOS_TEST_URL || 'http://127.0.0.1:8000', token = process.env.AGENTOS_TEST_TOKEN } = {}) {
  if (!token) throw new Error('Set AGENTOS_TEST_TOKEN for an isolated test server before running.');
  return withBrowser(async (browser) => {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => { if (message.type() === 'error' && !message.text().includes('401')) errors.push(message.text()); });
    await page.goto(url);
    await page.locator('#access-token').fill('incorrect-test-token');
    await page.locator('#connect-button').click();
    await page.locator('#connect-error').waitFor({ state: 'visible' });
    assert.match(await page.locator('#connect-error').textContent(), /token.*not accepted/i);
    await connect(page, url, token);
    assert.equal(await page.locator('#planner').inputValue(), 'local');
    assert.equal(await page.locator('#planner-openai').isDisabled(), true, 'The isolated runner must not enable a real AI provider');
    assert.equal(await page.locator('#planner-hint').isVisible(), true, 'Unavailable AI must include configuration guidance');
    if (await page.locator('.task-row').count() === 0) {
      await page.setViewportSize({ width: 390, height: 844 });
      assert.equal(await page.locator('#goal').isVisible(), true, 'The first-run composer opens on mobile');
      await page.locator('#mobile-new-task').click();
      assert.equal(await page.locator('#goal').isVisible(), false, 'Even an empty workspace can hide the mobile composer');
      await page.locator('#mobile-new-task').click();
      assert.equal(await page.locator('#goal').isVisible(), true);
    }
    await capture(page, 1440, 'desktop-start');
    await captureThemes(page, 'empty');

    let task = await create(page, 'calculate (2 + 3) * 4');
    assert.equal(task.status, 'completed');
    assert.equal(Number(task.result), 20);
    assert.equal(await page.locator('.detail-result strong').textContent(), task.result);
    assert.equal(await page.locator('.step').count(), 2);
    await captureThemes(page, 'completed', { detail: true });

    task = await create(page, 'add 9 and 6', true);
    assert.equal(task.status, 'pending');
    task = await action(page, 'Execute plan', task.task_id, 'execute');
    assert.equal(task.status, 'completed');
    assert.equal(Number(task.result), 15);

    task = await create(page, 'calculate (2 + 3) * 4', false, true);
    assert.equal(task.status, 'waiting_for_approval');
    await assertApprovalCall(page, task);
    assert.equal(await page.locator('#composer-message').evaluate((node) => node.classList.contains('sr-only')), true, 'Successful creation announcements should remain available to assistive technology without duplicating visible status');
    assert.match(await page.locator('#composer-message').textContent(), /paused.*approval/i);
    task = await action(page, 'Approve next step', task.task_id, 'approve');
    assert.equal(task.status, 'waiting_for_approval');
    await assertApprovalCall(page, task);
    assert.equal((await page.locator('#composer-message').textContent()).trim(), '', 'Approval must clear the stale composer paused notice');
    assert.equal(await page.locator('#detail-message').evaluate((node) => node.classList.contains('sr-only')), true);
    assert.match(await page.locator('#detail-message').textContent(), /next step.*approval/i);
    await capture(page, 1440, 'desktop-approval');
    await captureThemes(page, 'approval', { detail: true });
    task = await action(page, 'Approve next step', task.task_id, 'approve');
    assert.equal(task.status, 'completed');
    assert.equal((await page.locator('#composer-message').textContent()).trim(), '', 'A completed task must not retain a paused composer notice');

    task = await create(page, 'add 7 and 2', true);
    task = await action(page, 'Cancel task', task.task_id, 'cancel');
    assert.equal(task.status, 'cancelled');
    task = await create(page, 'divide 1 by 0');
    assert.equal(task.status, 'failed');
    assert.match(await page.locator('.detail-error').first().textContent(), /zero/i);
    assert.equal(await page.locator('[data-action="edit"]').count(), 1);
    assert.equal(await page.locator('[data-action="edit-local"]').count(), 0, 'A failure during tool execution must not offer a planner fallback');
    await captureThemes(page, 'failed', { detail: true });

    await page.getByRole('button', { name: 'Failed', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('task-list').getAttribute('aria-busy') === 'false');
    const failedTags = await page.locator('.task-list .status').allTextContents();
    assert.ok(failedTags.length > 0 && failedTags.every((text) => text === 'Failed'));
    await page.getByRole('button', { name: 'All', exact: true }).click();
    await page.waitForFunction(() => document.getElementById('task-list').getAttribute('aria-busy') === 'false');
    await page.locator('#task-search').fill('no-such-task-filter-2026');
    await page.getByText('No matching tasks', { exact: true }).waitFor();
    await page.locator('#task-search').fill('');
    await page.waitForFunction(() => document.querySelectorAll('.task-row').length > 0);

    await page.locator('a[data-route="tools"]').click();
    await page.locator('#tools-view').waitFor({ state: 'visible' });
    assert.equal(await page.locator('.tool-item').count(), 5);
    await page.locator('.tool-item summary').first().click();
    assert.match(await page.locator('.tool-item pre').first().textContent(), /properties/);
    await capture(page, 768, 'tablet-tools');
    await captureThemes(page, 'tools');
    await page.locator('a[data-route="tasks"]').click();
    await capture(page, 390, 'mobile-list');
    await page.locator('.task-row').first().click();
    await page.locator('.mobile-back').waitFor({ state: 'visible' });
    await capture(page, 390, 'mobile-detail');
    await page.getByRole('button', { name: 'Back to saved tasks', exact: true }).click();
    await page.locator('.task-list-section').waitFor({ state: 'visible' });
    await page.setViewportSize({ width: 1440, height: 900 });

    const dangerousGoal = '<img src=x onerror="window.__injected=true"> ' + 'longgoal'.repeat(90);
    task = await create(page, dangerousGoal);
    assert.equal(task.status, 'failed');
    assert.equal(await page.evaluate(() => Boolean(window.__injected)), false);
    await capture(page, 1440, 'desktop-long-goal');
    const storage = await page.evaluate(() => ({ local: Object.entries(localStorage), session: sessionStorage.length, html: document.documentElement.innerHTML }));
    assert.ok(storage.local.every(([key, value]) => key === 'agentos.theme' && ['light', 'dark'].includes(value)));
    assert.equal(storage.session, 0);
    assert.equal(storage.html.includes(token), false);
    await page.locator('#disconnect').click();
    await page.locator('#connect-view').waitFor({ state: 'visible' });
    assert.equal(await page.locator('.task-row').count(), 0);
    assert.equal(await page.locator('#access-token').inputValue(), '');
    assert.deepEqual(errors, []);
    await plannerModes(browser, url, token);
    await dashboardPolish(browser, url, token);
    await themeBehavior(browser, url, token);
    await taskMotion(browser, url, token);
    console.log(JSON.stringify({ result: 'passed', checked: ['connection and rejected token', 'execution and plan preview', 'approval and cancellation', 'failed tasks and filtering', 'tool schema disclosure', 'desktop/tablet/mobile layout', 'long text and safe rendering', 'token memory and disconnect', 'local planner fallback and AI approval controls', 'planning progress and safe mobile failure recovery', 'draft preservation and local retry', 'pointer feedback and reduced motion', 'OS theme, explicit persistence, blocked storage, and contrast', 'real plan/result motion with refresh and keyboard cancellation'], screenshots: out }, null, 2));
  });
}

module.exports = { verifyDashboard, verifyTheme: ({ url, token }) => withBrowser((browser) => themeBehavior(browser, url, token)) };
if (require.main === module) verifyDashboard().catch((error) => { console.error(error); process.exitCode = 1; });
