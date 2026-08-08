/**
 * Assertion helpers for E2E tests.
 */

/**
 * Assert that a table row containing the test data exists in the page.
 */
async function expectRowInTable(page, text, options = {}) {
  const tableSelector = options.tableSelector || '.ant-table-tbody';
  const row = page.locator(`${tableSelector} tr`).filter({ hasText: text });
  await expect(row.first()).toBeVisible({ timeout: options.timeout || 10000 });
  return row;
}

/**
 * Assert that an API response doesn't contain an error field.
 * This handles the project's HTTP 200 + {"error": "..."} pattern.
 */
function expectNoApiError(result, context = '') {
  if (result && result.error) {
    throw new Error(`Unexpected API error${context ? ` in ${context}` : ''}: ${result.error}`);
  }
}

/**
 * Assert that a modal or drawer is visible.
 */
async function expectModalVisible(page, title) {
  const modal = page.locator('.ant-modal').filter({ hasText: title });
  await expect(modal).toBeVisible({ timeout: 5000 });
}

/**
 * Assert that an antd notification message appears.
 */
async function expectSuccessMessage(page, text) {
  const msg = page.locator('.ant-message-notice').filter({ hasText: text || '成功' });
  await expect(msg.first()).toBeVisible({ timeout: 5000 });
}

/**
 * Assert page did not white-screen (body has content).
 */
async function expectNoWhiteScreen(page) {
  const bodyText = await page.locator('body').innerText();
  expect(bodyText.trim().length).toBeGreaterThan(0);
}

module.exports = {
  expectRowInTable,
  expectNoApiError,
  expectModalVisible,
  expectSuccessMessage,
  expectNoWhiteScreen,
};
