/* Portable browser verification. Node 22+ and Playwright are required.
   Starts this checkout on an unused loopback port with an in-memory database.
   AGENTOS_TEST_PYTHON selects Python; AGENTOS_BROWSER_CHANNEL selects e.g. msedge.
   PLAYWRIGHT_MODULE_PATH can point to an isolated Playwright installation. */
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { closeBrowsers } = require('./browser-support.cjs');
const { verifyDashboard } = require('./verify-dashboard.cjs');
const { verifyDashboardRaces } = require('./verify-dashboard-races.cjs');

const root = path.resolve(__dirname, '..');
const output = path.join(root, '.verification/browser-results');
const localPython = path.join(root, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');
const python = process.env.AGENTOS_TEST_PYTHON || (fs.existsSync(localPython) ? localPython : process.platform === 'win32' ? 'python' : 'python3');

async function deadline(promise, milliseconds, message) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), milliseconds); }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function verify() {
  fs.mkdirSync(output, { recursive: true });
  const started = Date.now();
  const token = randomBytes(32).toString('hex');
  const cancellation = new AbortController();
  const interrupted = new Promise((_, reject) => cancellation.signal.addEventListener('abort', () => reject(cancellation.signal.reason), { once: true }));
  interrupted.catch(() => {});
  const stop = () => cancellation.abort(new Error('Browser verification interrupted.'));
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  const serverEnv = {
    ...process.env,
    PYTHONDONTWRITEBYTECODE: '1',
    AGENTOS_TEST_TOKEN: token,
    AGENTOS_PLANNER: 'local',
  };
  for (const key of ['OPENAI_API_KEY', 'AGENTOS_MODEL', 'OPENAI_BASE_URL', 'AGENTOS_AI_TIMEOUT']) delete serverEnv[key];
  const server = spawn(python, ['-u', path.join(__dirname, 'browser-server.py')], {
    cwd: root,
    env: serverEnv,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let closing = false;
  let serverEnded = false;
  let serverInfo;
  let pendingLine = '';
  let serverLog = '';
  let outcome = { result: 'failed' };
  const ended = new Promise((resolve) => server.once('close', (code, signal) => {
    serverEnded = true;
    if (!closing) cancellation.abort(new Error(`Browser test server stopped unexpectedly (${code ?? signal}).`));
    resolve();
  }));
  server.once('error', (error) => cancellation.abort(new Error(`Could not start Python: ${python}`, { cause: error })));
  const record = (chunk) => { serverLog = (serverLog + chunk).slice(-65536); };
  server.stderr.on('data', record);
  server.stdout.on('data', (chunk) => {
    record(chunk);
    pendingLine += chunk;
    let end;
    while ((end = pendingLine.indexOf('\n')) !== -1) {
      const line = pendingLine.slice(0, end).trim();
      pendingLine = pendingLine.slice(end + 1);
      if (line.startsWith('AGENTOS_BROWSER_SERVER ')) {
        try { serverInfo = JSON.parse(line.slice('AGENTOS_BROWSER_SERVER '.length)); }
        catch (error) { cancellation.abort(new Error('Invalid test server startup response.', { cause: error })); }
      }
    }
  });

  async function ready() {
    while (!cancellation.signal.aborted) {
      if (serverInfo) {
        try {
          const response = await fetch(`${serverInfo.url}/api/health`, {
            signal: AbortSignal.any([cancellation.signal, AbortSignal.timeout(1000)]),
          });
          if (response.ok && (await response.json()).status === 'ok') return;
        } catch (error) {
          if (cancellation.signal.aborted) throw error;
        }
      }
      await delay(100, undefined, { signal: cancellation.signal });
    }
    cancellation.signal.throwIfAborted();
  }

  try {
    await deadline(Promise.race([ready(), interrupted]), 30000, 'Test server did not become ready within 30 seconds.');
    assert.equal(path.resolve(serverInfo.source), path.join(root, 'agent_engine/__init__.py'), 'The server must import this checkout.');
    const response = await fetch(`${serverInfo.url}/api/tasks?limit=1`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.any([cancellation.signal, AbortSignal.timeout(5000)]),
    });
    assert.equal(response.status, 200, 'Isolated test credentials must be accepted.');
    const history = await response.json();
    assert.equal(history.total, 0, 'Browser tests must start with an empty isolated database.');
    console.log(`Browser checks: ${serverInfo.url}; source: ${serverInfo.source}; browser: ${process.env.AGENTOS_BROWSER_CHANNEL || 'Chromium'}`);
    const checks = async () => {
      await verifyDashboard({ url: serverInfo.url, token });
      cancellation.signal.throwIfAborted();
      await verifyDashboardRaces({ url: serverInfo.url, token });
    };
    await deadline(Promise.race([checks(), interrupted]), 180000, 'Browser checks exceeded the three-minute timeout.');
    outcome = { result: 'passed', checked: ['dashboard', 'dashboard races'], source: serverInfo.source };
  } catch (error) {
    outcome.error = error.message;
    throw error;
  } finally {
    closing = true;
    cancellation.abort(new Error('Browser verification finished.'));
    try {
      await closeBrowsers();
    } finally {
      if (!serverEnded) {
        server.kill('SIGTERM');
        try { await deadline(ended, 5000, 'Server shutdown timed out.'); }
        catch {
          server.kill('SIGKILL');
          await deadline(ended, 5000, 'Could not stop the browser test server.');
        }
      }
      process.removeListener('SIGINT', stop);
      process.removeListener('SIGTERM', stop);
      outcome.elapsed_ms = Date.now() - started;
      outcome.server_stopped = serverEnded;
      fs.writeFileSync(path.join(output, 'server.log'), serverLog.replaceAll(token, '[test token]'));
      fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(outcome, null, 2) + '\n');
      console.log(`Isolated browser test server stopped. Results: ${path.join(output, 'results.json')}`);
    }
  }
}

verify().catch((error) => {
  console.error(error);
  console.error(`Server diagnostics: ${path.join(output, 'server.log')}`);
  process.exitCode = 1;
});
