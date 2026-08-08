# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: technical_operations\alert.spec.js >> System Alert - Technical Operations >> ALT003 - Alert API returns data
- Location: tests\technical_operations\alert.spec.js:30:3

# Error details

```
SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
```

# Test source

```ts
  1  | /**
  2  |  * System Alert - View tests
  3  |  */
  4  | const { test, expect } = require('../../fixtures/auth.fixture');
  5  | const { loginAndCreateContext, apiGet } = require('../../helpers/api');
  6  | 
  7  | test.describe('System Alert - Technical Operations', () => {
  8  |   test('ALT001 - Alert list page loads', async ({ page, request }) => {
  9  |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  10 |     const session = await apiLogin(request, 'admin');
  11 |     await injectAuth(page, session);
  12 |     await page.goto('/maintenance/alert');
  13 |     await page.waitForLoadState('networkidle');
  14 | 
  15 |     const bodyText = await page.locator('body').innerText();
  16 |     expect(bodyText.length).toBeGreaterThan(0);
  17 |   });
  18 | 
  19 |   test('ALT002 - Data quality page loads', async ({ page, request }) => {
  20 |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  21 |     const session = await apiLogin(request, 'admin');
  22 |     await injectAuth(page, session);
  23 |     await page.goto('/maintenance/data-quality');
  24 |     await page.waitForLoadState('networkidle');
  25 | 
  26 |     const bodyText = await page.locator('body').innerText();
  27 |     expect(bodyText.length).toBeGreaterThan(0);
  28 |   });
  29 | 
  30 |   test('ALT003 - Alert API returns data', async ({}) => {
  31 |     const result = await loginAndCreateContext('admin');
> 32 |     const data = await apiGet(result.context, '/api/alert/records/');
     |                  ^ SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
  33 |     expect(data).toBeDefined();
  34 |     await result.context.dispose();
  35 |   });
  36 | 
  37 |   test('ALT004 - Alert rules API returns data', async ({}) => {
  38 |     const result = await loginAndCreateContext('admin');
  39 |     const data = await apiGet(result.context, '/api/alert/rules/');
  40 |     expect(data).toBeDefined();
  41 |     await result.context.dispose();
  42 |   });
  43 | });
  44 | 
```