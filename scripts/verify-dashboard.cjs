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

async function capture(page, width, name) {
  await page.setViewportSize({ width, height: width > 1100 ? 900 : width > 600 ? 1024 : 844 });
  await page.evaluate(() => { window.scrollTo(0, 0); });
  await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
  const measured = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth, fonts: document.fonts.check('14px "IBM Plex Sans"') }));
  assert.ok(measured.scrollWidth <= measured.width + 1, `${name} page overflows horizontally: ${JSON.stringify(measured)}`);
  assert.ok(measured.fonts, 'IBM Plex Sans must load');
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

    let task = await create(page, 'calculate (2 + 3) * 4');
    assert.equal(task.status, 'completed');
    assert.equal(Number(task.result), 20);
    assert.equal(await page.locator('.detail-result strong').textContent(), task.result);
    assert.equal(await page.locator('.step').count(), 2);

    task = await create(page, 'add 9 and 6', true);
    assert.equal(task.status, 'pending');
    task = await action(page, 'Execute plan', task.task_id, 'execute');
    assert.equal(task.status, 'completed');
    assert.equal(Number(task.result), 15);

    task = await create(page, 'calculate (2 + 3) * 4', false, true);
    assert.equal(task.status, 'waiting_for_approval');
    task = await action(page, 'Approve next step', task.task_id, 'approve');
    assert.equal(task.status, 'waiting_for_approval');
    await capture(page, 1440, 'desktop-approval');
    task = await action(page, 'Approve next step', task.task_id, 'approve');
    assert.equal(task.status, 'completed');

    task = await create(page, 'add 7 and 2', true);
    task = await action(page, 'Cancel task', task.task_id, 'cancel');
    assert.equal(task.status, 'cancelled');
    task = await create(page, 'divide 1 by 0');
    assert.equal(task.status, 'failed');
    assert.match(await page.locator('.detail-error').first().textContent(), /zero/i);
    assert.equal(await page.locator('[data-action="edit"]').count(), 1);
    assert.equal(await page.locator('[data-action="edit-local"]').count(), 0, 'A failure during tool execution must not offer a planner fallback');

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
    const storage = await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length, html: document.documentElement.innerHTML }));
    assert.equal(storage.local, 0);
    assert.equal(storage.session, 0);
    assert.equal(storage.html.includes(token), false);
    await page.locator('#disconnect').click();
    await page.locator('#connect-view').waitFor({ state: 'visible' });
    assert.equal(await page.locator('.task-row').count(), 0);
    assert.equal(await page.locator('#access-token').inputValue(), '');
    assert.deepEqual(errors, []);
    await plannerModes(browser, url, token);
    await dashboardPolish(browser, url, token);
    console.log(JSON.stringify({ result: 'passed', checked: ['connection and rejected token', 'execution and plan preview', 'approval and cancellation', 'failed tasks and filtering', 'tool schema disclosure', 'desktop/tablet/mobile layout', 'long text and safe rendering', 'token memory and disconnect', 'local planner fallback and AI approval controls', 'planning progress and safe mobile failure recovery', 'draft preservation and local retry', 'pointer feedback and reduced motion'], screenshots: out }, null, 2));
  });
}

module.exports = { verifyDashboard };
if (require.main === module) verifyDashboard().catch((error) => { console.error(error); process.exitCode = 1; });
