# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: cross_module\cross_module.spec.js >> Cross-Module Integration Tests >> X003 - Home page todo API works
- Location: tests\cross_module\cross_module.spec.js:29:3

# Error details

```
SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
```

# Test source

```ts
  1   | /**
  2   |  * Cross-module tests - verify real cross-module interactions.
  3   |  */
  4   | const { test, expect } = require('../../fixtures/auth.fixture');
  5   | const { loginAndCreateContext, apiGet, apiPost, apiDelete } = require('../../helpers/api');
  6   | 
  7   | test.describe('Cross-Module Integration Tests', () => {
  8   |   test('X001 - Home page shows announcement panel', async ({ page, request }) => {
  9   |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  10  |     const session = await apiLogin(request, 'admin');
  11  |     await injectAuth(page, session);
  12  |     await page.goto('/home');
  13  |     await page.waitForLoadState('networkidle');
  14  | 
  15  |     // Home page should have content
  16  |     const bodyText = await page.locator('body').innerText();
  17  |     expect(bodyText.length).toBeGreaterThan(0);
  18  |   });
  19  | 
  20  |   test('X002 - Home page statistic API returns integrated data', async ({}) => {
  21  |     const result = await loginAndCreateContext('admin');
  22  |     const data = await apiGet(result.context, '/api/home/statistic/');
  23  |     expect(data).toBeDefined();
  24  |     // Should not have error
  25  |     expect(data.error || '').toBe('');
  26  |     await result.context.dispose();
  27  |   });
  28  | 
  29  |   test('X003 - Home page todo API works', async ({}) => {
  30  |     const result = await loginAndCreateContext('admin');
> 31  |     const data = await apiGet(result.context, '/api/home/todo/');
      |                  ^ SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
  32  |     expect(data).toBeDefined();
  33  |     await result.context.dispose();
  34  |   });
  35  | 
  36  |   test('X004 - Navigation API returns menu structure', async ({}) => {
  37  |     const result = await loginAndCreateContext('admin');
  38  |     const data = await apiGet(result.context, '/api/home/navigation/');
  39  |     expect(data).toBeDefined();
  40  |     await result.context.dispose();
  41  |   });
  42  | 
  43  |   test('X005 - Home announcement API returns published announcements', async ({}) => {
  44  |     const result = await loginAndCreateContext('admin');
  45  |     const data = await apiGet(result.context, '/api/home/announcement/');
  46  |     expect(data).toBeDefined();
  47  |     await result.context.dispose();
  48  |   });
  49  | 
  50  |   test('X006 - Radio license badge API integrates with home expiry panel', async ({}) => {
  51  |     const result = await loginAndCreateContext('admin');
  52  |     const data = await apiGet(result.context, '/api/radio-license/badge/');
  53  |     expect(data).toBeDefined();
  54  |     await result.context.dispose();
  55  |   });
  56  | 
  57  |   test('X007 - Contract agreement badge API integrates with home expiry panel', async ({}) => {
  58  |     const result = await loginAndCreateContext('admin');
  59  |     const data = await apiGet(result.context, '/api/contract-agreement/badge/');
  60  |     expect(data).toBeDefined();
  61  |     await result.context.dispose();
  62  |   });
  63  | 
  64  |   test('X008 - Runlog in-progress items appear on home page', async ({}) => {
  65  |     const result = await loginAndCreateContext('admin');
  66  |     const data = await apiGet(result.context, '/api/runlog/?status=in_progress&page_size=5');
  67  |     expect(data).toBeDefined();
  68  |     await result.context.dispose();
  69  |   });
  70  | 
  71  |   test('X009 - Home page loads all overview panels', async ({ page, request }) => {
  72  |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  73  |     const session = await apiLogin(request, 'admin');
  74  |     await injectAuth(page, session);
  75  | 
  76  |     const failedRequests = [];
  77  |     page.on('response', response => {
  78  |       if (response.status() >= 500) {
  79  |         failedRequests.push(`${response.status()} ${response.url()}`);
  80  |       }
  81  |     });
  82  | 
  83  |     await page.goto('/home');
  84  |     await page.waitForLoadState('networkidle');
  85  |     await page.waitForTimeout(3000);
  86  | 
  87  |     // No 500 errors on home page
  88  |     expect(failedRequests.filter(r => !r.includes('favicon'))).toHaveLength(0);
  89  |   });
  90  | 
  91  |   test('X010 - Data analysis page loads without 500 errors', async ({ page, request }) => {
  92  |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  93  |     const session = await apiLogin(request, 'admin');
  94  |     await injectAuth(page, session);
  95  | 
  96  |     const failedRequests = [];
  97  |     page.on('response', response => {
  98  |       if (response.status() >= 500) {
  99  |         failedRequests.push(`${response.status()} ${response.url()}`);
  100 |       }
  101 |     });
  102 | 
  103 |     await page.goto('/data-analysis');
  104 |     await page.waitForLoadState('networkidle');
  105 |     await page.waitForTimeout(3000);
  106 | 
  107 |     expect(failedRequests.filter(r => !r.includes('favicon'))).toHaveLength(0);
  108 |   });
  109 | });
  110 | 
```