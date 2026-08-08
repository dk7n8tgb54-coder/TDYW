/**
 * Screenshot helper - captures failure evidence.
 */
const path = require('path');

/**
 * Capture a screenshot with a descriptive name.
 */
async function captureScreenshot(page, name, outputDir) {
  const dir = outputDir || path.join(__dirname, '..', '..', 'reports', 'e2e', 'artifacts', 'screenshots');
  const filename = `${name}_${Date.now()}.png`;
  const filepath = path.join(dir, filename);
  await page.screenshot({ path: filepath, fullPage: true });
  return filepath;
}

/**
 * Log page state for debugging.
 */
async function logPageState(page, context = '') {
  const url = page.url();
  const title = await page.title();
  console.log(`[Page State${context ? `: ${context}` : ''}] URL: ${url}, Title: ${title}`);
}

/**
 * Capture browser console errors.
 */
function attachConsoleLogger(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      errors.push(msg.text());
    }
  });
  page.on('pageerror', error => {
    errors.push(`PAGE ERROR: ${error.message}`);
  });
  return errors;
}

module.exports = {
  captureScreenshot,
  logPageState,
  attachConsoleLogger,
};
