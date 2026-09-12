/**
 * 角色权限码目录（codes.js）结构契约测试
 *
 * codes.js 是角色权限编辑的权限目录来源，权限码格式必须为
 * `<module>.<page>.<action>`（AGENTS.md 八.1）。本测试验证：
 * - 目录结构合法：模块/页面/权限三级 key 均非空且不重复
 * - 权限码在全局唯一（同一权限码不得重复出现在目录中）
 * - 关键正式模块的权限码存在（锚点抽查，与模块矩阵对应）
 *
 * 注：路由 auth 与权限码/后端权限的一致性由 quality/permission_audit 专项承担，
 * 此处不重复（routes.js 直接引入全部页面组件，jest 下不可导入）。
 */
import permCodes from '../codes';

function collectCodes(catalog) {
  const codes = [];
  for (const mod of catalog) {
    for (const page of mod.pages || []) {
      for (const perm of page.perms || []) {
        codes.push(`${mod.key}.${page.key}.${perm.key}`);
      }
    }
  }
  return codes;
}

describe('角色权限码目录结构', () => {
  it('模块 key 非空且不重复', () => {
    const keys = permCodes.map(m => m.key);
    keys.forEach(k => expect(k).toBeTruthy());
    expect(new Set(keys).size).toBe(keys.length);
  });

  it('页面 key 在模块内不重复，权限 key 在页面内不重复', () => {
    permCodes.forEach(mod => {
      const pageKeys = (mod.pages || []).map(p => p.key);
      pageKeys.forEach(k => expect(k).toBeTruthy());
      expect(new Set(pageKeys).size).toBe(pageKeys.length);
      (mod.pages || []).forEach(page => {
        const permKeys = (page.perms || []).map(p => p.key);
        permKeys.forEach(k => expect(k).toBeTruthy());
        expect(new Set(permKeys).size).toBe(permKeys.length);
      });
    });
  });

  it('全局权限码唯一（module.page.action 三段式）', () => {
    const codes = collectCodes(permCodes);
    expect(codes.length).toBeGreaterThan(100);
    const dup = codes.filter((c, i) => codes.indexOf(c) !== i);
    expect(dup).toEqual([]);
  });

  it('关键正式模块权限码存在（锚点抽查）', () => {
    const codes = new Set(collectCodes(permCodes));
    // 资料库 / 党建 / 规章
    expect(codes.has('document.document.view')).toBe(true);
    expect(codes.has('document.party_building_document.view')).toBe(true);
    expect(codes.has('document.regulation.category_manage')).toBe(true);
    // 值班日志 / 跨日事项 / 提醒事项（home.reminder.*）
    expect(codes.has('duty.duty.view')).toBe(true);
    expect(codes.has('home.reminder.view')).toBe(true);
    // 操作日志与系统告警（system.audit / system.alert）
    expect(codes.has('system.audit.view')).toBe(true);
    expect(codes.has('system.alert.view')).toBe(true);
    // 数据分析
    expect(codes.has('data_analysis.overview.view')).toBe(true);
  });
});
