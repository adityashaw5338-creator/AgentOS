/* Real-browser regressions for delayed responses and keyboard task actions.
   Uses the same isolated server/token/Playwright setup as verify-dashboard.cjs. */
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const url = process.env.AGENTOS_TEST_URL || 'http://127.0.0.1:8000';
const token = process.env.AGENTOS_TEST_TOKEN;
if (!token) throw new Error('Set AGENTOS_TEST_TOKEN for an isolated test server.');

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function settled(page) {
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
}

async function connect(page) {
  await page.goto(url);
  await page.locator('#access-token').fill(token);
  await page.locator('#connect-button').click();
  await page.locator('#workspace').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.getElementById('task-list').getAttribute('aria-busy') === 'false');
}

async function create(page, approval = false) {
  await page.locator('#goal').fill('calculate (2 + 3) * 4');
  await page.locator('#require-approval').setChecked(approval);
  const response = page.waitForResponse((res) => res.url().endsWith('/api/tasks') && res.request().method() === 'POST');
  await page.locator(approval ? '#run-button' : '#preview-button').click();
  const task = await (await response).json();
  await page.waitForFunction(() => !document.getElementById('run-button').disabled);
  return task;
}

async function staleRefresh(page) {
  const task = await create(page);
  const captured = deferred(), release = deferred(), delivered = deferred();
  const pattern = `**/api/tasks/${task.task_id}`;
  await page.route(pattern, async (route) => {
    const response = await route.fetch();
    captured.resolve();
    await release.promise;
    await route.fulfill({ response });
    delivered.resolve();
  });
  await page.locator('#refresh').click();
  await captured.promise;
  await page.getByRole('button', { name: 'Execute plan', exact: true }).click();
  await page.locator('#task-detail .status.completed').waitFor();
  release.resolve();
  await delivered.promise;
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  await settled(page);
  assert.equal(await page.locator('#task-detail .status').textContent(), 'Completed', 'An older refresh must not overwrite completed execution');
  assert.equal(await page.getByRole('button', { name: 'Execute plan', exact: true }).count(), 0);
  await page.unroute(pattern);
}

async function staleSelectionError(page) {
  const first = await create(page);
  const second = await create(page);
  const captured = deferred(), release = deferred(), delivered = deferred();
  const pattern = `**/api/tasks/${first.task_id}`;
  await page.route(pattern, async (route) => {
    captured.resolve();
    await release.promise;
    await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Old selection is unavailable.' }) });
    delivered.resolve();
  });
  await page.locator(`[data-task-id="${first.task_id}"]`).click();
  await captured.promise;
  const selected = page.waitForResponse((res) => res.url().endsWith(`/api/tasks/${second.task_id}`));
  await page.locator(`[data-task-id="${second.task_id}"]`).click();
  await selected;
  await settled(page);
  release.resolve();
  await delivered.promise;
  await settled(page);
  assert.equal(await page.locator('#detail-message').isVisible(), false, 'Errors from an old selection must not appear on another task');
  await page.unroute(pattern);
}

async function keyboardApproval(page) {
  const task = await create(page, true);
  const approve = page.getByRole('button', { name: 'Approve next step', exact: true });
  const approved = page.waitForResponse((res) => res.url().endsWith(`/api/tasks/${task.task_id}/approve`));
  await approve.focus();
  await page.keyboard.press('Enter');
  await approved;
  await page.waitForFunction(() => [...document.querySelectorAll('.detail-actions button')].every((button) => !button.disabled));
  assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Approve next step', 'Keyboard focus must follow the next approval action');
  await page.keyboard.press('Enter');
  await page.locator('#task-detail .status.completed').waitFor();
}

async function disconnectDuringRefresh(page) {
  const captured = deferred(), release = deferred(), delivered = deferred();
  await page.route('**/api/tasks?*', async (route) => {
    captured.resolve();
    await release.promise;
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Engine unavailable.' }) });
    delivered.resolve();
  });
  await page.locator('#refresh').click();
  await captured.promise;
  await page.locator('#disconnect').click();
  release.resolve();
  await delivered.promise;
  await settled(page);
  assert.equal(await page.locator('#task-list').getAttribute('aria-busy'), 'false', 'Disconnect must reset the history loading state');
  assert.equal(await page.locator('#composer-message').textContent(), '', 'Disconnect must clear the previous task message');
  assert.equal(await page.locator('#freshness').textContent(), '', 'Disconnect must clear the previous freshness stamp');
  assert.equal(await page.locator('#list-error').textContent(), '');
  assert.equal(await page.locator('#workspace').isVisible(), false);
  await page.unroute('**/api/tasks?*');
}

async function mobileDraftRefresh(page) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#mobile-new-task').click();
  await page.locator('#goal').fill('add 40 and 2');
  await page.locator('#refresh').click();
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#goal').isVisible(), true, 'Refreshing must keep an open mobile task form visible');
  assert.equal(await page.locator('#goal').inputValue(), 'add 40 and 2');
  await page.setViewportSize({ width: 1440, height: 900 });
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await connect(page);
    await staleRefresh(page);
    await staleSelectionError(page);
    await keyboardApproval(page);
    await mobileDraftRefresh(page);
    await disconnectDuringRefresh(page);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ result: 'passed', checked: ['stale refresh', 'stale selection error', 'keyboard approvals', 'mobile draft refresh', 'disconnect during refresh'] }));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
