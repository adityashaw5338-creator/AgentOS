/* Shared browser lifecycle for standalone checks and the isolated test runner. */
const browsers = new Set();

function playwright() {
  try {
    return require(process.env.PLAYWRIGHT_MODULE_PATH || process.env.PLAYWRIGHT_PATH || 'playwright');
  } catch (error) {
    throw new Error('Install Playwright or set PLAYWRIGHT_MODULE_PATH to its package directory.', { cause: error });
  }
}

async function withBrowser(check) {
  const options = { headless: true, timeout: 30000 };
  if (process.env.AGENTOS_BROWSER_CHANNEL) options.channel = process.env.AGENTOS_BROWSER_CHANNEL;
  const pending = playwright().chromium.launch(options);
  browsers.add(pending);
  try {
    const browser = await pending;
    return await check(browser);
  } finally {
    await pending.then((browser) => browser.close(), () => {});
    browsers.delete(pending);
  }
}

async function closeBrowsers() {
  await Promise.allSettled([...browsers].map((pending) => pending.then((browser) => browser.close())));
}

module.exports = { withBrowser, closeBrowsers };
