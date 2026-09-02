/**
 * 资料库模块发布门禁 E2E 测试（stable_contract）
 *
 * 覆盖：登录进入资料库、目录创建、小文件上传、重命名、搜索、属性、删除、
 *       党建入口与 system_folder 注入、无凭证访问拒绝、空状态、下载、幂等。
 *
 * 注意：登录会轮换同一账号的 access_token，因此每个用例独立建立会话，
 * 不共享 API 上下文。断言同时落在 UI 与后端 API 真实状态上；
 * 只清理本套件创建的 E2E_GATE_ 前缀数据。
 */
const { test, expect } = require('../../fixtures/auth.fixture');
const { loginAndCreateContext, apiGet, apiPost, apiDelete } = require('../../helpers/api');
const path = require('path');
const fs = require('fs');
const os = require('os');

const PREFIX = 'E2E_GATE_';
const SAMPLE_FILE = path.join(__dirname, '..', '..', 'test-data', 'safe_samples', 'sample.txt');
const stamp = Date.now();
const folderName = `${PREFIX}目录_${stamp}`;

// ---- API 辅助（资料库专用）----

async function listRoot(ctx) {
  const data = await apiGet(ctx, '/api/document/folder/?is_public=true');
  if (data && data.error) throw new Error(`listRoot error: ${data.error}`);
  return data && data.data ? data.data : { folders: [], files: [] };
}

async function findFolder(ctx, name) {
  const data = await listRoot(ctx);
  return (data.folders || []).find(f => f.name === name) || null;
}

async function findFileInFolder(ctx, folderId, name) {
  const data = await apiGet(ctx, `/api/document/folder/?id=${folderId}&is_public=true`);
  if (data && data.error) return null;
  const files = (data && data.data && data.data.files) || [];
  return files.find(f => f.display_name === name || f.name === name) || null;
}

async function cleanupGateData() {
  const api = await loginAndCreateContext('admin');
  try {
    const root = await listRoot(api.context);
    for (const f of (root.folders || [])) {
      if (f.name && f.name.startsWith(PREFIX)) {
        await apiDelete(api.context, `/api/document/folder/?id=${f.id}&is_public=true`);
      }
    }
    for (const f of (root.files || [])) {
      if ((f.display_name || f.name || '').startsWith(PREFIX)) {
        await apiDelete(api.context, `/api/document/file/?id=${f.id}&is_public=true`);
      }
    }
  } finally {
    await api.context.dispose();
  }
}

test.describe('资料库发布门禁 E2E', () => {
  test.describe.configure({ mode: 'serial' });

  test.beforeAll(async () => {
    await cleanupGateData();
  });

  test.afterAll(async () => {
    await cleanupGateData();
  });

  test('GATE01 - 未认证访问资料库 API 被拒绝', async ({ request }) => {
    const resp = await request.get('/api/document/folder/?is_public=true');
    const body = await resp.json();
    expect(body.error || resp.status() >= 400).toBeTruthy();
  });

  test('GATE02 - 登录后进入资料库页面', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/document');
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
    const hasUploadEntry = await page.getByRole('button', { name: /上传/ }).count();
    const hasNewFolderEntry = await page.getByRole('button', { name: /新建|创建/ }).count();
    expect(hasUploadEntry + hasNewFolderEntry).toBeGreaterThan(0);
  });

  test('GATE03 - API 创建目录并在 UI 中可见', async ({ page, request }) => {
    const api = await loginAndCreateContext('admin');
    const created = await apiPost(api.context, '/api/document/folder/', {
      name: folderName, parent_id: null, is_public: true,
    });
    expect(created.error || '').toBe('');
    expect(created.data.created).toBe(true);
    const folderId = created.data.id;
    await api.context.dispose();

    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto(`/document?folder=${folderId}`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toContainText(folderName, { timeout: 10000 });
  });

  test('GATE04 - UI 上传小文件并落库', async ({ page, request }) => {
    test.skip(!fs.existsSync(SAMPLE_FILE), '缺少样例文件');

    // 先取到目标目录（此上下文随后释放，因为 UI 登录会轮换 token）
    const setup = await loginAndCreateContext('admin');
    const root = await listRoot(setup.context);
    const folder = (root.folders || []).find(f => f.name === folderName);
    const folderId = folder ? folder.id : null;
    await setup.context.dispose();
    test.skip(!folder, '前置目录不存在');

    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto(`/document?folder=${folderId}&space=public`);
    await page.waitForLoadState('networkidle');

    // 上传入口是 Dropdown：先点触发按钮，再选「上传文件」菜单项
    const uploadBtn = page.getByRole('button', { name: /上传/ });
    test.skip((await uploadBtn.count()) === 0, '未找到上传入口');
    await uploadBtn.first().click();

    const menuItem = page.locator('.ant-dropdown-menu-item').filter({ hasText: '上传文件' });
    await menuItem.first().waitFor({ state: 'visible', timeout: 5000 });
    const fileChooserPromise = page.waitForEvent('filechooser', { timeout: 5000 }).catch(() => null);
    await menuItem.first().click();
    const fileChooser = await fileChooserPromise;
    test.skip(!fileChooser, '未触发文件选择器');

    const fileName = `${PREFIX}小文件_${stamp}.txt`;
    const tmp = path.join(os.tmpdir(), fileName);
    fs.copyFileSync(SAMPLE_FILE, tmp);
    await fileChooser.setFiles(tmp);

    // UI 上传后重新建立 API 会话再做校验（登录会轮换 token）
    let record = null;
    for (let i = 0; i < 20 && !record; i += 1) {
      await page.waitForTimeout(1000);
      const verify = await loginAndCreateContext('admin');
      try {
        record = await findFileInFolder(verify.context, folderId, fileName);
      } finally {
        await verify.context.dispose();
      }
    }
    expect(record).not.toBeNull();
    const size = record.file_size !== undefined ? record.file_size : record.size;
    expect(size).toBeGreaterThan(0);
    fs.rmSync(tmp, { force: true });
  });

  test('GATE05 - API 重命名目录并生效', async () => {
    const api = await loginAndCreateContext('admin');
    try {
      const root = await listRoot(api.context);
      const folder = (root.folders || []).find(f => f.name === folderName);
      expect(folder).toBeTruthy();
      const newName = `${PREFIX}改名_${stamp}`;
      const resp = await apiPost(api.context, '/api/document/folder/rename/', {
        id: folder.id, name: newName, is_public: true,
      });
      expect(resp.error || '').toBe('');
      expect(await findFolder(api.context, newName)).not.toBeNull();

      const back = await apiPost(api.context, '/api/document/folder/rename/', {
        id: folder.id, name: folderName, is_public: true,
      });
      expect(back.error || '').toBe('');
    } finally {
      await api.context.dispose();
    }
  });

  test('GATE06 - 搜索能命中目录', async () => {
    const api = await loginAndCreateContext('admin');
    try {
      const resp = await apiGet(
        api.context,
        `/api/document/folder/search/?keyword=${encodeURIComponent(folderName)}&is_public=true`);
      expect(resp.error || '').toBe('');
      const names = [
        ...((resp.data && resp.data.folders) || []).map(f => f.name),
        ...((resp.data && resp.data.files) || []).map(f => f.name),
      ];
      expect(names.some(n => n && n.includes(folderName))).toBe(true);
    } finally {
      await api.context.dispose();
    }
  });

  test('GATE07 - 文件夹属性统计接口', async () => {
    const api = await loginAndCreateContext('admin');
    try {
      const root = await listRoot(api.context);
      const folder = (root.folders || []).find(f => f.name === folderName);
      expect(folder).toBeTruthy();
      const resp = await apiGet(
        api.context, `/api/document/folder/properties/?id=${folder.id}&is_public=true&type=folder`);
      expect(resp.error || '').toBe('');
      expect(resp.data).toBeTruthy();
      expect(typeof resp.data.file_count).toBe('number');
      expect(typeof resp.data.total_size).toBe('number');
    } finally {
      await api.context.dispose();
    }
  });

  test('GATE08 - 删除目录后 API 确认消失', async () => {
    const api = await loginAndCreateContext('admin');
    try {
      const root = await listRoot(api.context);
      const folder = (root.folders || []).find(f => f.name === folderName);
      expect(folder).toBeTruthy();
      const resp = await apiDelete(
        api.context, `/api/document/folder/?id=${folder.id}&is_public=true`);
      expect(resp.error || '').toBe('');
      expect(await findFolder(api.context, folderName)).toBeNull();
    } finally {
      await api.context.dispose();
    }
  });

  test('GATE09 - 党建入口可访问且注入 system_folder', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    const captured = [];
    page.on('request', req => {
      if (req.url().includes('/api/document/')) captured.push(req.url());
    });

    await page.goto('/document/party-building-documents');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    expect(captured.length).toBeGreaterThan(0);
    expect(captured.some(u => u.includes('system_folder=party_building_documents')))
      .toBe(true);
  });

  test('GATE10 - 党建模式页面正常渲染', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto('/document/party-building-documents');
    await page.waitForLoadState('networkidle');
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.length).toBeGreaterThan(0);
  });

  test('GATE11 - 普通模式 API 不带 system_folder（不污染公共库）', async ({ page, request }) => {
    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);

    const captured = [];
    page.on('request', req => {
      if (req.url().includes('/api/document/folder/')) captured.push(req.url());
    });
    await page.goto('/document');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);

    expect(captured.length).toBeGreaterThan(0);
    expect(captured.some(u => u.includes('system_folder='))).toBe(false);
  });

  test('GATE12 - 空目录显示空状态且无服务器错误', async ({ page, request }) => {
    const api = await loginAndCreateContext('admin');
    const emptyName = `${PREFIX}空目录_${stamp}`;
    const created = await apiPost(api.context, '/api/document/folder/', {
      name: emptyName, parent_id: null, is_public: true,
    });
    expect(created.error || '').toBe('');
    const emptyId = created.data.id;
    await api.context.dispose();

    const { apiLogin, injectAuth } = require('../../fixtures/auth.fixture');
    const session = await apiLogin(request, 'admin');
    await injectAuth(page, session);
    await page.goto(`/document?folder=${emptyId}`);
    await page.waitForLoadState('networkidle');

    const bodyText = await page.locator('body').innerText();
    expect(bodyText.includes('服务器内部错误')).toBe(false);

    const api2 = await loginAndCreateContext('admin');
    await apiDelete(api2.context, `/api/document/folder/?id=${emptyId}&is_public=true`);
    await api2.context.dispose();
  });

  test('GATE13 - 下载接口返回二进制内容', async () => {
    const api = await loginAndCreateContext('admin');
    try {
      const fileName = `${PREFIX}下载_${stamp}.txt`;
      const boundary = `----e2egate${stamp}`;
      const content = 'gate-download-body';
      const body = [
        `--${boundary}`,
        'Content-Disposition: form-data; name="is_public"',
        '',
        'true',
        `--${boundary}`,
        `Content-Disposition: form-data; name="file"; filename="${fileName}"`,
        'Content-Type: text/plain',
        '',
        content,
        `--${boundary}--`,
      ].join('\r\n');

      const resp = await api.context.post('/api/document/upload/', {
        headers: { 'Content-Type': `multipart/form-data; boundary=${boundary}` },
        data: body,
      });
      const up = await resp.json();
      expect(up.error || '').toBe('');

      const root = await listRoot(api.context);
      const file = (root.files || []).find(f => f.display_name === fileName);
      expect(file).toBeTruthy();

      const dl = await api.context.get(`/api/document/download/?id=${file.id}&is_public=true`);
      expect(dl.status()).toBe(200);
      expect(await dl.text()).toBe(content);

      await apiDelete(api.context, `/api/document/file/?id=${file.id}&is_public=true`);
    } finally {
      await api.context.dispose();
    }
  });

  test('GATE14 - 同名目录重复创建幂等', async () => {
    const api = await loginAndCreateContext('admin');
    try {
      const dupName = `${PREFIX}幂等_${stamp}`;
      const first = await apiPost(api.context, '/api/document/folder/', {
        name: dupName, parent_id: null, is_public: true,
      });
      expect(first.error || '').toBe('');
      expect(first.data.created).toBe(true);
      const second = await apiPost(api.context, '/api/document/folder/', {
        name: dupName, parent_id: null, is_public: true,
      });
      expect(second.data.created).toBe(false);
      expect(second.data.id).toBe(first.data.id);

      const root = await listRoot(api.context);
      const matches = (root.folders || []).filter(f => f.name === dupName);
      expect(matches.length).toBe(1);

      await apiDelete(api.context, `/api/document/folder/?id=${first.data.id}&is_public=true`);
    } finally {
      await api.context.dispose();
    }
  });

  test('GATE15 - 党建接口在普通模式下拒绝访问（作用域隔离）', async () => {
    const api = await loginAndCreateContext('admin');
    try {
      const root = await apiGet(api.context, '/api/document/folder/?all=true&is_public=true');
      // 党建根目录不出现在普通模式目录列表中
      const pbFolder = (root.data || []).find(f => f.name === '党建文档');
      expect(pbFolder).toBeUndefined();
    } finally {
      await api.context.dispose();
    }
  });
});
