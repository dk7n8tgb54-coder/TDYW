# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: permissions\permissions.spec.js >> Permission Tests >> P005 - System management route requires auth
- Location: tests\permissions\permissions.spec.js:51:3

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
  1   | /**
  2   |  * Permission tests - verify access control works correctly.
  3   |  */
  4   | const { test, expect } = require('../../fixtures/auth.fixture');
  5   | const { loginAndCreateContext, apiGet } = require('../../helpers/api');
  6   | 
  7   | const ADMIN_USER = process.env.E2E_ADMIN_USERNAME || 'admin';
  8   | const ADMIN_PWD = process.env.E2E_ADMIN_PASSWORD || 'E2E@Test2026!';
  9   | 
  10  | test.describe('Permission Tests', () => {
  11  |   test('P001 - Admin can see all menu items', async ({ page, request }) => {
  12  |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  13  |     const session = await apiLogin(request, 'admin');
  14  |     await injectAuth(page, session);
  15  |     await page.goto('/home');
  16  |     await page.waitForLoadState('networkidle');
  17  | 
  18  |     // Admin (is_supper) should see system management
  19  |     const submenu = page.locator('.ant-menu-submenu-title').filter({ hasText: '系统管理' });
  20  |     expect(await submenu.count()).toBeGreaterThan(0);
  21  |   });
  22  | 
  23  |   test('P002 - Unauthenticated user cannot access protected API', async ({ request }) => {
  24  |     // Try to access API without token
  25  |     const response = await request.get('/api/account/user/');
  26  |     const body = await response.json();
  27  | 
  28  |     // Should return error (not authenticated)
  29  |     expect(body.error || response.status() >= 400).toBeTruthy();
  30  |   });
  31  | 
  32  |   test('P003 - Unauthenticated user cannot access document API', async ({ request }) => {
  33  |     const response = await request.get('/api/document/folder/');
  34  |     const body = await response.json();
  35  |     expect(body.error || response.status() >= 400).toBeTruthy();
  36  |   });
  37  | 
  38  |   test('P004 - Protected route requires authentication', async ({ page }) => {
  39  |     await page.goto('/');
  40  |     await page.evaluate(() => sessionStorage.clear());
  41  |     await page.goto('/system/account');
  42  |     await page.waitForLoadState('networkidle');
  43  |     await page.waitForTimeout(3000);
  44  | 
  45  |     // The app should redirect to login page after API 401
  46  |     const url = page.url();
  47  |     const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
  48  |     expect(hasLoginInput > 0 || url.endsWith('/') || url.endsWith(':8080/')).toBeTruthy();
  49  |   });
  50  | 
  51  |   test('P005 - System management route requires auth', async ({ page }) => {
  52  |     await page.goto('/');
  53  |     await page.evaluate(() => sessionStorage.clear());
  54  |     await page.goto('/system/role');
  55  |     await page.waitForLoadState('networkidle');
  56  |     await page.waitForTimeout(3000);
  57  | 
  58  |     const url = page.url();
  59  |     const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
> 60  |     expect(hasLoginInput > 0 || url.endsWith('/') || url.endsWith(':8080/')).toBeTruthy();
      |                                                                              ^ Error: expect(received).toBeTruthy()
  61  |   });
  62  | 
  63  |   test('P006 - Document route requires auth', async ({ page }) => {
  64  |     await page.goto('/');
  65  |     await page.evaluate(() => sessionStorage.clear());
  66  |     await page.goto('/document');
  67  |     await page.waitForLoadState('networkidle');
  68  |     await page.waitForTimeout(3000);
  69  | 
  70  |     const url = page.url();
  71  |     const hasLoginInput = await page.locator('input[placeholder="请输入账户"]').count();
  72  |     expect(hasLoginInput > 0 || url.endsWith('/') || url.endsWith(':8080/')).toBeTruthy();
  73  |   });
  74  | 
  75  |   test('P007 - Invalid token is rejected', async ({ request }) => {
  76  |     const response = await request.get('/api/account/user/', {
  77  |       headers: { 'X-Token': 'invalid_token_12345' },
  78  |     });
  79  |     const body = await response.json();
  80  |     expect(body.error || response.status() >= 400).toBeTruthy();
  81  |   });
  82  | 
  83  |   test('P008 - Home page statistic API requires auth', async ({ request }) => {
  84  |     const response = await request.get('/api/home/statistic/');
  85  |     const body = await response.json();
  86  |     expect(body.error || response.status() >= 400).toBeTruthy();
  87  |   });
  88  | 
  89  |   test('P009 - Audit log API requires auth', async ({ request }) => {
  90  |     const response = await request.get('/api/logs/audit/');
  91  |     const body = await response.json();
  92  |     expect(body.error || response.status() >= 400).toBeTruthy();
  93  |   });
  94  | 
  95  |   test('P010 - Deleted schedule API returns 404 or error', async ({ request }) => {
  96  |     const { loginAndCreateContext } = require('../../helpers/api');
  97  |     const result = await loginAndCreateContext('admin');
  98  |     const response = await result.context.get('/api/schedule/');
  99  |     // Should return 404 or error (module deleted)
  100 |     expect(response.status() === 404 || response.status() === 405).toBeTruthy();
  101 |     await result.context.dispose();
  102 |   });
  103 | });
  104 | 
```