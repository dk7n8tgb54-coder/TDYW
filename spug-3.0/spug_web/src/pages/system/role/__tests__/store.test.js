/**
 * 角色权限设置状态隔离回归测试
 *
 * showPagePerm 以 record.page_perms 合并出可编辑的 permissions。
 * 历史缺陷：mergeWith customizer 对数组按引用返回，导致
 * permissions[mod][page] 与 record.page_perms[mod][page] 共享同一数组，
 * PagePerm 勾选时 push/splice 原地污染列表里的记录——点「取消」后
 * 重新打开弹窗仍显示已勾选，再点「确定」会把未保存的勾选提交。
 * 本测试钉死：编辑必须发生在深拷贝上，record.page_perms 不被修改。
 */
import store from '../store';

describe('showPagePerm 权限编辑状态与记录隔离', () => {
  it('勾选修改只作用于 permissions，不污染 record.page_perms', () => {
    const record = {
      id: 1,
      name: '测试角色',
      page_perms: {institution: {manual: ['view']}},
    };
    store.showPagePerm(record);
    expect(store.permissions.institution.manual).toEqual(['view']);

    // 模拟 PagePerm.handlePermCheck 的原地修改
    store.permissions.institution.manual.push('admin');
    expect(store.permissions.institution.manual).toContain('admin');
    expect(record.page_perms.institution.manual).toEqual(['view']);
  });

  it('取消后重新打开，从 record 重建，不含未保存的勾选', () => {
    const record = {
      id: 2,
      name: '另一角色',
      page_perms: {institution: {manual: ['view']}},
    };
    store.showPagePerm(record);
    store.permissions.institution.manual.push('admin');
    // 模拟「取消」后再次打开同一角色
    store.showPagePerm(record);
    expect(store.permissions.institution.manual).toEqual(['view']);
    expect(store.permissions.institution.manual).not.toContain('admin');
  });

  it('record 未配置 page_perms 时按空授权初始化', () => {
    store.showPagePerm({id: 3, name: '新角色'});
    expect(store.permissions.institution.manual).toEqual([]);
  });
});
