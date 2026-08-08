# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: smoke\smoke.spec.js >> Smoke Tests - System Availability >> S009 - Protected route redirects when not authenticated
- Location: tests\smoke\smoke.spec.js:176:3

# Error details

```
Error: expect(received).toBeTruthy()

Received: false
```

# Page snapshot

```yaml
- generic [ref=f1e3]:
  - complementary [ref=f1e4]:
    - generic [ref=f1e5]:
      - img "Logo" [ref=f1e7]
      - generic [ref=f1e8]:
        - menu
  - generic [ref=f1e9]:
    - generic [ref=f1e10]:
      - img "menu-fold" [ref=f1e12] [cursor=pointer]
      - generic [ref=f1e17] [cursor=pointer]
    - main [ref=f1e20]:
      - generic [ref=f1e24]:
        - heading "404" [level=1] [ref=f1e25]
        - generic [ref=f1e26]: 抱歉，你访问的页面不存在
    - generic [ref=f1e27]: © 2026 YTTD
```

# Test source

```ts
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
  128 |       '/api/home/notice/',
  129 |       '/api/reminder/',
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
  177 |     // Clear any existing session and navigate to protected route
  178 |     await page.goto('/');
  179 |     await page.evaluate(() => sessionStorage.clear());
  180 |     await page.goto('/system/account');
  181 |     await page.waitForLoadState('networkidle');
  182 | 
  183 |     // The app should redirect to login page (pathname '/') after API 401
  184 |     // Wait for URL to change to '/' or login input to appear
  185 |     await page.waitForTimeout(3000);
  186 |     const url = page.url();
  187 |     const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
  188 |     // Either redirected to login page, or showing login form
> 189 |     expect(hasLoginInput > 0 || url.endsWith('/') || url.endsWith(':8080/')).toBeTruthy();
      |                                                                              ^ Error: expect(received).toBeTruthy()
  190 |   });
  191 | 
  192 |   test('S010 - Deleted schedule module is not accessible', async ({ page, request }) => {
  193 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  194 |     const session = await apiLogin(request, 'admin');
  195 |     await injectAuth(page, session);
  196 | 
  197 |     // Schedule menu should not exist
  198 |     await page.goto('/home');
  199 |     await page.waitForLoadState('networkidle');
  200 |     const scheduleMenu = page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: '排班' });
  201 |     expect(await scheduleMenu.count()).toBe(0);
  202 | 
  203 |     // Direct route should not show schedule content
  204 |     await page.goto('/schedule');
  205 |     await page.waitForLoadState('networkidle');
  206 |     const bodyText = await page.locator('body').innerText();
  207 |     // Should not contain schedule-specific content
  208 |     expect(bodyText).not.toContain('排班管理');
  209 |     expect(bodyText).not.toContain('交接班');
  210 |   });
  211 | 
  212 |   test('S011 - Deleted shift/swap modules are not accessible', async ({ page, request }) => {
  213 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  214 |     const session = await apiLogin(request, 'admin');
  215 |     await injectAuth(page, session);
  216 | 
  217 |     await page.goto('/home');
  218 |     await page.waitForLoadState('networkidle');
  219 | 
  220 |     const deletedTerms = ['交接班', '换班', '替班', '代班', '调班'];
  221 |     for (const term of deletedTerms) {
  222 |       const menuItems = page.locator('.ant-menu-item, .ant-menu-submenu-title').filter({ hasText: term });
  223 |       expect(await menuItems.count(), `Found menu item for deleted term: ${term}`).toBe(0);
  224 |     }
  225 |   });
  226 | });
  227 | 
```