/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import { buildManualPayload } from '../ManualForm';

describe('buildManualPayload', () => {
  it('antd 清空后的 undefined 显式转为空串/null（键不丢失）', () => {
    const payload = buildManualPayload({
      name: '  部门管理手册  ',
      code: undefined,
      category_id: undefined,
      org_name: undefined,
    });
    expect(payload.name).toBe('部门管理手册');
    expect(payload).toHaveProperty('code', '');
    expect(payload).toHaveProperty('category_id', null);
    expect(payload).toHaveProperty('org_name', '');
    // 2026-10-31 授权模型：手册表单不再提交角色关联字段（账号授权
    // 由详情页「权限配置」页签逐本维护）
    expect(payload).not.toHaveProperty('view_role_ids');
    expect(payload).not.toHaveProperty('edit_role_ids');
    expect(payload).not.toHaveProperty('publish_role_ids');
    // JSON 序列化不丢键
    const keys = Object.keys(JSON.parse(JSON.stringify(payload)));
    expect(keys).toContain('code');
    expect(keys).toContain('org_type');
  });

  it('新建缺省：归属部门、启用、编制者可见发布版', () => {
    const payload = buildManualPayload({name: 'x'});
    expect(payload.org_type).toBe('department');
    expect(payload.status).toBe('active');
    expect(payload.editor_can_view_published).toBe(true);
  });

  it('编辑缺省回落到手册现值，显式提交的 false 不被覆盖', () => {
    const defaults = {org_type: 'section', status: 'archived',
      editor_can_view_published: true};
    expect(buildManualPayload({name: 'x'}, defaults).org_type).toBe('section');
    expect(buildManualPayload({name: 'x'}, defaults).status).toBe('archived');
    expect(buildManualPayload({name: 'x'}, defaults).editor_can_view_published)
      .toBe(true);
    expect(buildManualPayload({name: 'x', editor_can_view_published: false}, defaults)
      .editor_can_view_published).toBe(false);
  });

  it('文本字段去除首尾空白', () => {
    const payload = buildManualPayload({name: ' a ', code: ' b ', org_name: ' c '});
    expect(payload.name).toBe('a');
    expect(payload.code).toBe('b');
    expect(payload.org_name).toBe('c');
  });
});
