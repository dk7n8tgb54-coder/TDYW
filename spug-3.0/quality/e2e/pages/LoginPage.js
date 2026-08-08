/**
 * LoginPage - Page Object for the login page.
 */
const { expect } = require('@playwright/test');

class LoginPage {
  constructor(page) {
    this.page = page;
    this.usernameInput = page.locator('input[placeholder="请输入账户"]');
    this.passwordInput = page.locator('input[placeholder="请输入密码"]');
    this.loginButton = page.getByRole('button', { name: /登\s*录/ });
  }

  async goto() {
    await this.page.goto('/');
    await this.page.waitForLoadState('networkidle');
  }

  async login(username, password) {
    await this.usernameInput.fill(username);
    await this.passwordInput.fill(password);
    await this.loginButton.click();
  }

  async loginSuccessfully(username, password) {
    await this.login(username, password);
    await this.page.waitForURL('**/home**', { timeout: 15000 });
    await this.page.waitForLoadState('networkidle');
  }

  async expectLoginError(errorText) {
    const errorMsg = this.page.locator('.ant-message-notice, .ant-form-item-explain-error, .ant-notification-notice').filter({ hasText: errorText });
    await expect(errorMsg.first()).toBeVisible({ timeout: 5000 });
  }

  async expectLoginPageVisible() {
    await expect(this.usernameInput).toBeVisible();
    await expect(this.passwordInput).toBeVisible();
    await expect(this.loginButton).toBeVisible();
  }
}

module.exports = { LoginPage };
