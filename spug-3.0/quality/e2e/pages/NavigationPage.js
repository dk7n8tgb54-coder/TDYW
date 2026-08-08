/**
 * NavigationPage - Page Object for menu navigation and common UI operations.
 */
const { expect } = require('@playwright/test');

class NavigationPage {
  constructor(page) {
    this.page = page;
    this.menuItems = page.locator('.ant-menu-item, .ant-menu-submenu-title');
    this.contentArea = page.locator('.spug-content, .ant-layout-content, main');
  }

  /**
   * Navigate to a route by URL hash.
   */
  async gotoRoute(route) {
    await this.page.goto(`/#${route}`);
    await this.page.waitForLoadState('networkidle');
  }

  /**
   * Click a menu item by text.
   */
  async clickMenuItem(text) {
    const item = this.page.locator('.ant-menu-item').filter({ hasText: text });
    if (await item.count() > 0) {
      await item.first().click();
      await this.page.waitForLoadState('networkidle');
      return true;
    }
    return false;
  }

  /**
   * Expand a submenu by title.
   */
  async expandSubmenu(title) {
    const submenu = this.page.locator('.ant-menu-submenu-title').filter({ hasText: title });
    if (await submenu.count() > 0 && await submenu.isVisible()) {
      await submenu.click();
      await this.page.waitForTimeout(300);
      return true;
    }
    return false;
  }

  /**
   * Navigate to a specific menu path, expanding parent menus as needed.
   */
  async navigateTo(...menuPath) {
    for (let i = 0; i < menuPath.length - 1; i++) {
      await this.expandSubmenu(menuPath[i]);
    }
    const lastItem = menuPath[menuPath.length - 1];
    const found = await this.clickMenuItem(lastItem);
    if (!found) {
      // Try direct route navigation
      throw new Error(`Menu item not found: ${lastItem}`);
    }
  }

  /**
   * Click the "New" or "Add" button on a list page.
   */
  async clickNewButton(buttonText = '新建') {
    const btn = this.page.getByRole('button', { name: new RegExp(buttonText) });
    await btn.first().click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Click a button by text.
   */
  async clickButton(text) {
    const btn = this.page.getByRole('button', { name: text });
    await btn.first().click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Fill a form field by label.
   */
  async fillField(label, value) {
    // Try to find the form item by label
    const formItem = this.page.locator('.ant-form-item').filter({ hasText: label });
    const input = formItem.locator('input, textarea').first();
    await input.fill(value);
  }

  /**
   * Select from an antd Select component.
   */
  async selectOption(label, optionText) {
    const formItem = this.page.locator('.ant-form-item').filter({ hasText: label });
    const selector = formItem.locator('.ant-select-selector').first();
    await selector.click();
    await this.page.waitForTimeout(300);
    const option = this.page.locator('.ant-select-item-option').filter({ hasText: optionText });
    await option.first().click();
  }

  /**
   * Click the confirm/save button in a modal.
   */
  async confirmModal() {
    const okBtn = this.page.locator('.ant-modal-footer .ant-btn-primary, .ant-drawer-footer .ant-btn-primary');
    await okBtn.first().click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Cancel/close a modal.
   */
  async cancelModal() {
    const cancelBtn = this.page.locator('.ant-modal-close, .ant-drawer-close');
    await cancelBtn.first().click();
  }

  /**
   * Search in a table.
   */
  async search(keyword) {
    const searchInput = this.page.locator('input[placeholder*="搜索"], input[placeholder*="查询"], input[placeholder*="关键字"]').first();
    if (await searchInput.isVisible()) {
      await searchInput.fill(keyword);
      await this.page.keyboard.press('Enter');
      await this.page.waitForLoadState('networkidle');
    }
  }

  /**
   * Wait for table to load.
   */
  async waitForTable() {
    await this.page.waitForSelector('.ant-table-tbody tr', { timeout: 10000 });
  }

  /**
   * Get table rows.
   */
  getTableRows() {
    return this.page.locator('.ant-table-tbody tr');
  }

  /**
   * Find a row containing specific text.
   */
  findRow(text) {
    return this.page.locator('.ant-table-tbody tr').filter({ hasText: text });
  }

  /**
   * Click an action button (edit/delete/etc.) in a table row.
   */
  async clickRowAction(rowText, actionText) {
    const row = this.findRow(rowText);
    const actionBtn = row.locator('a, button').filter({ hasText: actionText });
    await actionBtn.first().click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Click the delete button in a row and confirm.
   */
  async deleteRow(rowText) {
    await this.clickRowAction(rowText, '删除');
    const confirmBtn = this.page.locator('.ant-popover-buttons .ant-btn-primary, .ant-modal-confirm-btns .ant-btn-primary');
    await confirmBtn.first().click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Check if a menu item is visible.
   */
  async isMenuVisible(text) {
    const item = this.page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: text });
    return item.count() > 0 && item.first().isVisible();
  }

  /**
   * Logout from the system.
   */
  async logout() {
    // Click the user avatar/dropdown
    const userArea = this.page.locator('.ant-dropdown-trigger, .user-info, [class*="avatar"]').first();
    if (await userArea.isVisible()) {
      await userArea.click();
      await this.page.waitForTimeout(300);
    }
    const logoutBtn = this.page.getByText('退出登录');
    if (await logoutBtn.isVisible()) {
      await logoutBtn.click();
      await this.page.waitForLoadState('networkidle');
    }
  }
}

module.exports = { NavigationPage };
