# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: permissions\permissions.spec.js >> Permission Tests >> P010 - Deleted schedule API returns 404 or error
- Location: tests\permissions\permissions.spec.js:89:3

# Error details

```
SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
```

# Test source

```ts
  1  | /**
  2  |  * Permission tests - verify access control works correctly.
  3  |  */
  4  | const { test, expect } = require('../../fixtures/auth.fixture');
  5  | const { loginAndCreateContext, apiGet } = require('../../helpers/api');
  6  | 
  7  | const ADMIN_USER = process.env.E2E_ADMIN_USERNAME || 'admin';
  8  | const ADMIN_PWD = process.env.E2E_ADMIN_PASSWORD || 'E2E@Test2026!';
  9  | 
  10 | test.describe('Permission Tests', () => {
  11 |   test('P001 - Admin can see all menu items', async ({ page, request }) => {
  12 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  13 |     const session = await apiLogin(request, 'admin');
  14 |     await injectAuth(page, session);
  15 |     await page.goto('/home');
  16 |     await page.waitForLoadState('networkidle');
  17 | 
  18 |     // Admin (is_supper) should see system management
  19 |     const submenu = page.locator('.ant-menu-submenu-title').filter({ hasText: '系统管理' });
  20 |     expect(await submenu.count()).toBeGreaterThan(0);
  21 |   });
  22 | 
  23 |   test('P002 - Unauthenticated user cannot access protected API', async ({ request }) => {
  24 |     // Try to access API without token
  25 |     const response = await request.get('/api/account/user/');
  26 |     const body = await response.json();
  27 | 
  28 |     // Should return error (not authenticated)
  29 |     expect(body.error || response.status() >= 400).toBeTruthy();
  30 |   });
  31 | 
  32 |   test('P003 - Unauthenticated user cannot access document API', async ({ request }) => {
  33 |     const response = await request.get('/api/document/folders/');
  34 |     const body = await response.json();
  35 |     expect(body.error || response.status() >= 400).toBeTruthy();
  36 |   });
  37 | 
  38 |   test('P004 - Protected route requires authentication', async ({ page }) => {
  39 |     await page.goto('/');
  40 |     await page.evaluate(() => sessionStorage.clear());
  41 |     await page.goto('/system/account');
  42 |     await page.waitForLoadState('networkidle');
  43 | 
  44 |     // Should redirect to login
  45 |     const loginInput = page.locator('input[placeholder="请输入账户"]');
  46 |     await expect(loginInput).toBeVisible({ timeout: 10000 });
  47 |   });
  48 | 
  49 |   test('P005 - System management route requires auth', async ({ page }) => {
  50 |     await page.goto('/');
  51 |     await page.evaluate(() => sessionStorage.clear());
  52 |     await page.goto('/system/role');
  53 |     await page.waitForLoadState('networkidle');
  54 | 
  55 |     const loginInput = page.locator('input[placeholder="请输入账户"]');
  56 |     await expect(loginInput).toBeVisible({ timeout: 10000 });
  57 |   });
  58 | 
  59 |   test('P006 - Document route requires auth', async ({ page }) => {
  60 |     await page.goto('/');
  61 |     await page.evaluate(() => sessionStorage.clear());
  62 |     await page.goto('/document');
  63 |     await page.waitForLoadState('networkidle');
  64 | 
  65 |     const loginInput = page.locator('input[placeholder="请输入账户"]');
  66 |     await expect(loginInput).toBeVisible({ timeout: 10000 });
  67 |   });
  68 | 
  69 |   test('P007 - Invalid token is rejected', async ({ request }) => {
  70 |     const response = await request.get('/api/account/user/', {
  71 |       headers: { 'X-Token': 'invalid_token_12345' },
  72 |     });
  73 |     const body = await response.json();
  74 |     expect(body.error || response.status() >= 400).toBeTruthy();
  75 |   });
  76 | 
  77 |   test('P008 - Home page statistic API requires auth', async ({ request }) => {
  78 |     const response = await request.get('/api/home/statistic/');
  79 |     const body = await response.json();
  80 |     expect(body.error || response.status() >= 400).toBeTruthy();
  81 |   });
  82 | 
  83 |   test('P009 - Audit log API requires auth', async ({ request }) => {
  84 |     const response = await request.get('/api/logs/audit/');
  85 |     const body = await response.json();
  86 |     expect(body.error || response.status() >= 400).toBeTruthy();
  87 |   });
  88 | 
  89 |   test('P010 - Deleted schedule API returns 404 or error', async ({ request }) => {
  90 |     const { loginAndCreateContext, apiGet } = require('../../helpers/api');
  91 |     const result = await loginAndCreateContext('admin');
> 92 |     const data = await apiGet(result.context, '/api/schedule/');
     |                  ^ SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
  93 |     // Should return error or 404 (module deleted)
  94 |     expect(data.error || true).toBeTruthy();
  95 |     await result.context.dispose();
  96 |   });
  97 | });
  98 | 
```