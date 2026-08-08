# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: smoke\smoke.spec.js >> Smoke Tests - System Availability >> S009 - Protected route redirects when not authenticated
- Location: tests\smoke\smoke.spec.js:176:3

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('input[placeholder="请输入账户"]')
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" with timeout 10000ms
  - waiting for locator('input[placeholder="请输入账户"]')

```

```yaml
- complementary:
  - img "Logo"
  - menu
- img "menu-fold"
- img
- main:
  - heading "404" [level=1]
  - text: 抱歉，你访问的页面不存在
- text: © 2026 YTTD
```

# Test source

```ts
  85  |       '/runlog',
  86  |       '/device/device_resume',
  87  |       '/exec/fault/record',
  88  |       '/interference',
  89  |       '/duty',
  90  |       '/system/announcement',
  91  |       '/reminder',
  92  |       '/system/account',
  93  |       '/system/role',
  94  |       '/system/setting',
  95  |       '/system/login',
  96  |       '/maintenance/audit',
  97  |     ];
  98  | 
  99  |     for (const route of routes) {
  100 |       await page.goto(route);
  101 |       await page.waitForLoadState('networkidle');
  102 |       const bodyText = await page.locator('body').innerText();
  103 |       expect(bodyText.trim().length, `White screen on ${route}`).toBeGreaterThan(0);
  104 |     }
  105 |   });
  106 | 
  107 |   test('S006 - Key static resources load successfully', async ({ page }) => {
  108 |     const failedResources = [];
  109 |     page.on('response', response => {
  110 |       if (response.status() >= 500) {
  111 |         failedResources.push(`${response.status()} ${response.url()}`);
  112 |       }
  113 |     });
  114 | 
  115 |     const loginPage = new LoginPage(page);
  116 |     await loginPage.goto();
  117 |     await page.waitForLoadState('networkidle');
  118 | 
  119 |     expect(failedResources.filter(r => !r.includes('favicon'))).toHaveLength(0);
  120 |   });
  121 | 
  122 |   test('S007 - Key API endpoints do not return 500', async ({ page, request }) => {
  123 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  124 |     const session = await apiLogin(request, 'admin');
  125 |     await injectAuth(page, session);
  126 | 
  127 |     const apiEndpoints = [
  128 |       '/api/home/notices/',
  129 |       '/api/home/reminders/',
  130 |       '/api/home/navigation/',
  131 |       '/api/account/users/',
  132 |       '/api/account/roles/',
  133 |     ];
  134 | 
  135 |     for (const endpoint of apiEndpoints) {
  136 |       const response = await page.request.get(endpoint, {
  137 |         headers: { 'X-Token': session.token },
  138 |       });
  139 |       expect(response.status(), `API ${endpoint} returned ${response.status()}`).toBeLessThan(500);
  140 |     }
  141 |   });
  142 | 
  143 |   test('S008 - Logout redirects to login page', async ({ page, request }) => {
  144 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  145 |     const session = await apiLogin(request, 'admin');
  146 |     await injectAuth(page, session);
  147 |     await page.goto('/home');
  148 |     await page.waitForLoadState('networkidle');
  149 | 
  150 |     // Click logout
  151 |     const navPage = new NavigationPage(page);
  152 |     // Try to find and click the user dropdown
  153 |     const userTrigger = page.locator('.ant-dropdown-trigger, .header-user, [class*="user"]').first();
  154 |     if (await userTrigger.isVisible()) {
  155 |       await userTrigger.click();
  156 |       await page.waitForTimeout(500);
  157 |       const logoutLink = page.getByText('退出登录');
  158 |       if (await logoutLink.isVisible()) {
  159 |         await logoutLink.click();
  160 |         await page.waitForLoadState('networkidle');
  161 |       }
  162 |     }
  163 | 
  164 |     // Alternatively, clear session and verify redirect
  165 |     await page.evaluate(() => {
  166 |       sessionStorage.clear();
  167 |     });
  168 |     await page.goto('/home');
  169 |     await page.waitForLoadState('networkidle');
  170 | 
  171 |     // Should redirect to login
  172 |     const loginInput = page.locator('input[placeholder="请输入账户"]');
  173 |     await expect(loginInput).toBeVisible({ timeout: 10000 });
  174 |   });
  175 | 
  176 |   test('S009 - Protected route redirects when not authenticated', async ({ page }) => {
  177 |     // Clear any existing session
  178 |     await page.goto('/');
  179 |     await page.evaluate(() => sessionStorage.clear());
  180 |     await page.goto('/system/account');
  181 |     await page.waitForLoadState('networkidle');
  182 | 
  183 |     // Should be redirected to login
  184 |     const loginInput = page.locator('input[placeholder="请输入账户"]');
> 185 |     await expect(loginInput).toBeVisible({ timeout: 10000 });
      |                              ^ Error: expect(locator).toBeVisible() failed
  186 |   });
  187 | 
  188 |   test('S010 - Deleted schedule module is not accessible', async ({ page, request }) => {
  189 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  190 |     const session = await apiLogin(request, 'admin');
  191 |     await injectAuth(page, session);
  192 | 
  193 |     // Schedule menu should not exist
  194 |     await page.goto('/home');
  195 |     await page.waitForLoadState('networkidle');
  196 |     const scheduleMenu = page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: '排班' });
  197 |     expect(await scheduleMenu.count()).toBe(0);
  198 | 
  199 |     // Direct route should not show schedule content
  200 |     await page.goto('/schedule');
  201 |     await page.waitForLoadState('networkidle');
  202 |     const bodyText = await page.locator('body').innerText();
  203 |     // Should not contain schedule-specific content
  204 |     expect(bodyText).not.toContain('排班管理');
  205 |     expect(bodyText).not.toContain('交接班');
  206 |   });
  207 | 
  208 |   test('S011 - Deleted shift/swap modules are not accessible', async ({ page, request }) => {
  209 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  210 |     const session = await apiLogin(request, 'admin');
  211 |     await injectAuth(page, session);
  212 | 
  213 |     await page.goto('/home');
  214 |     await page.waitForLoadState('networkidle');
  215 | 
  216 |     const deletedTerms = ['交接班', '换班', '替班', '代班', '调班'];
  217 |     for (const term of deletedTerms) {
  218 |       const menuItems = page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: term });
  219 |       expect(await menuItems.count(), `Found menu item for deleted term: ${term}`).toBe(0);
  220 |     }
  221 |   });
  222 | });
  223 | 
```