/* Browser smoke test against an isolated AgentOS server and database.
   npm-installed Playwright or PLAYWRIGHT_MODULE_PATH is needed; Microsoft Edge is used.
   AGENTOS_TEST_URL defaults to http://127.0.0.1:8000.
   AGENTOS_TEST_TOKEN must match the isolated server's AGENTOS_API_TOKEN. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

let playwright;
try { playwright = require(process.env.PLAYWRIGHT_MODULE_PATH || process.env.PLAYWRIGHT_PATH || 'playwright'); }
catch { console.error('Install Playwright for this optional check, or set PLAYWRIGHT_MODULE_PATH to its package directory.'); process.exit(2); }
const url = process.env.AGENTOS_TEST_URL || 'http://127.0.0.1:8000';
const token = process.env.AGENTOS_TEST_TOKEN;
if (!token) { console.error('Set AGENTOS_TEST_TOKEN for an isolated test server before running.'); process.exit(2); }
const out = path.resolve(__dirname, '../.verification/dashboard');
fs.mkdirSync(out, { recursive: true });

async function connect(page) {
  await page.goto(url);
  await page.locator('#access-token').fill(token);
  await page.locator('#connect-button').click();
  await page.locator('#workspace').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.getElementById('task-list').getAttribute('aria-busy') === 'false');
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

(async () => {
  const browser = await playwright.chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error' && !message.text().includes('401')) errors.push(message.text()); });
  try {
    await page.goto(url);
    await page.locator('#access-token').fill('incorrect-test-token');
    await page.locator('#connect-button').click();
    await page.locator('#connect-error').waitFor({ state: 'visible' });
    assert.match(await page.locator('#connect-error').textContent(), /token.*not accepted/i);
    await connect(page);
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
    console.log(JSON.stringify({ result: 'passed', checked: ['connection and rejected token', 'execution and plan preview', 'approval and cancellation', 'failed tasks and filtering', 'tool schema disclosure', 'desktop/tablet/mobile layout', 'long text and safe rendering', 'token memory and disconnect'], screenshots: out }, null, 2));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
