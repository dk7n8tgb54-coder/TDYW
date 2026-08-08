# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: document_admin\document.spec.js >> Document Library - Document Admin >> DOC005 - Document file list API works
- Location: tests\document_admin\document.spec.js:93:3

# Error details

```
SyntaxError: Unexpected end of JSON input
```

# Test source

```ts
  1   | /**
  2   |  * Document Library - CRUD tests (folders, upload, download, delete)
  3   |  */
  4   | const { test, expect } = require('../../fixtures/auth.fixture');
  5   | const path = require('path');
  6   | const fs = require('fs');
  7   | 
  8   | const SAMPLE_FILE = path.join(__dirname, '..', '..', 'test-data', 'safe_samples', 'sample.txt');
  9   | 
  10  | test.describe('Document Library - Document Admin', () => {
  11  |   test('DOC001 - Document library page loads', async ({ page, request }) => {
  12  |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  13  |     const session = await apiLogin(request, 'admin');
  14  |     await injectAuth(page, session);
  15  |     await page.goto('/document');
  16  |     await page.waitForLoadState('networkidle');
  17  | 
  18  |     const bodyText = await page.locator('body').innerText();
  19  |     expect(bodyText.length).toBeGreaterThan(0);
  20  |   });
  21  | 
  22  |   test('DOC002 - Create folder via UI', async ({ page, request }) => {
  23  |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  24  |     const session = await apiLogin(request, 'admin');
  25  |     await injectAuth(page, session);
  26  |     await page.goto('/document');
  27  |     await page.waitForLoadState('networkidle');
  28  | 
  29  |     const folderName = `E2E_测试文件夹_${Date.now()}`;
  30  | 
  31  |     // Look for new folder button
  32  |     const newFolderBtn = page.getByRole('button', { name: /新建文件夹|新建目录|创建文件夹/ });
  33  |     if (await newFolderBtn.count() > 0) {
  34  |       await newFolderBtn.first().click();
  35  |       await page.waitForTimeout(500);
  36  | 
  37  |       // Fill folder name
  38  |       const nameInput = page.locator('input').first();
  39  |       if (await nameInput.isVisible()) {
  40  |         await nameInput.fill(folderName);
  41  |       }
  42  | 
  43  |       // Confirm
  44  |       const okBtn = page.locator('.ant-modal-footer .ant-btn-primary, .ant-btn-primary').filter({ hasText: /确定|创建/ });
  45  |       if (await okBtn.count() > 0) {
  46  |         await okBtn.first().click();
  47  |         await page.waitForTimeout(2000);
  48  |       }
  49  | 
  50  |       // Verify folder appears
  51  |       await page.waitForTimeout(1000);
  52  |       const pageText = await page.locator('body').innerText();
  53  |       if (pageText.includes(folderName)) {
  54  |         expect(pageText).toContain(folderName);
  55  |       }
  56  |     }
  57  | 
  58  |     expect(true).toBe(true);
  59  |   });
  60  | 
  61  |   test('DOC003 - Upload file via UI', async ({ page, request }) => {
  62  |     const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
  63  |     const session = await apiLogin(request, 'admin');
  64  |     await injectAuth(page, session);
  65  |     await page.goto('/document');
  66  |     await page.waitForLoadState('networkidle');
  67  | 
  68  |     // Look for upload button
  69  |     const uploadBtn = page.getByRole('button', { name: /上传|导入/ });
  70  |     if (await uploadBtn.count() > 0) {
  71  |       // Set up file chooser handler
  72  |       const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 }).catch(() => null);
  73  |       await uploadBtn.first().click();
  74  | 
  75  |       const fileChooser = await fileChooserPromise;
  76  |       if (fileChooser) {
  77  |         await fileChooser.setFiles(SAMPLE_FILE);
  78  |         await page.waitForTimeout(3000);
  79  |       }
  80  |     }
  81  | 
  82  |     expect(true).toBe(true);
  83  |   });
  84  | 
  85  |   test('DOC004 - Document folder API works', async ({}) => {
  86  |     const { loginAndCreateContext, apiGet } = require('../../helpers/api');
  87  |     const result = await loginAndCreateContext('admin');
  88  |     const data = await apiGet(result.context, '/api/document/folder/');
  89  |     expect(data).toBeDefined();
  90  |     await result.context.dispose();
  91  |   });
  92  | 
  93  |   test('DOC005 - Document file list API works', async ({}) => {
  94  |     const { loginAndCreateContext, apiGet } = require('../../helpers/api');
  95  |     const result = await loginAndCreateContext('admin');
> 96  |     const data = await apiGet(result.context, '/api/document/file/');
      |                  ^ SyntaxError: Unexpected end of JSON input
  97  |     expect(data).toBeDefined();
  98  |     await result.context.dispose();
  99  |   });
  100 | 
  101 |   test('DOC006 - Cleanup E2E test folders', async ({}) => {
  102 |     const { loginAndCreateContext, apiGet, apiDelete } = require('../../helpers/api');
  103 |     const result = await loginAndCreateContext('admin');
  104 | 
  105 |     // Get all folders
  106 |     const data = await apiGet(result.context, '/api/document/folder/');
  107 |     if (data.data && Array.isArray(data.data)) {
  108 |       const testFolders = data.data.filter(f => f.name && f.name.startsWith('E2E_'));
  109 |       for (const folder of testFolders.reverse()) {
  110 |         try {
  111 |           await apiDelete(result.context, `/api/document/folder/${folder.id}/`);
  112 |         } catch (e) {
  113 |           console.log(`Cleanup folder ${folder.id}: ${e.message}`);
  114 |         }
  115 |       }
  116 |     }
  117 | 
  118 |     // Also cleanup test files
  119 |     const filesData = await apiGet(result.context, '/api/document/file/');
  120 |     if (filesData.data && Array.isArray(filesData.data)) {
  121 |       const testFiles = filesData.data.filter(f => f.name && f.name.startsWith('E2E_'));
  122 |       for (const file of testFiles) {
  123 |         try {
  124 |           await apiDelete(result.context, `/api/document/file/${file.id}/`);
  125 |         } catch (e) {
  126 |           console.log(`Cleanup file ${file.id}: ${e.message}`);
  127 |         }
  128 |       }
  129 |     }
  130 | 
  131 |     await result.context.dispose();
  132 |     expect(true).toBe(true);
  133 |   });
  134 | });
  135 | 
```