/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import { buildManualPayload } from '../ManualForm';

describe('buildManualPayload', () => {
  it('antd 清空后的 undefined 显式转为空数组/空串（键不丢失）', () => {
    const payload = buildManualPayload({
      name: '  部门管理手册  ',
      code: undefined,
      category_id: undefined,
      owner_name: undefined,
      view_role_ids: undefined,
      edit_role_ids: undefined,
      publish_role_ids: undefined,
    });
    expect(payload.name).toBe('部门管理手册');
    expect(payload).toHaveProperty('code', '');
    expect(payload).toHaveProperty('category_id', null);
    expect(payload).toHaveProperty('owner_name', '');
    expect(payload).toHaveProperty('view_role_ids', []);
    expect(payload).toHaveProperty('edit_role_ids', []);
    expect(payload).toHaveProperty('publish_role_ids', []);
    // JSON 序列化不丢键
    const keys = Object.keys(JSON.parse(JSON.stringify(payload)));
    expect(keys).toContain('code');
    expect(keys).toContain('edit_role_ids');
  });

  it('新建缺省：归属部门、启用、编制者可见发布版', () => {
    const payload = buildManualPayload({name: 'x'});
    expect(payload.owner_type).toBe('department');
    expect(payload.status).toBe('active');
    expect(payload.editor_can_view_published).toBe(true);
  });

  it('编辑缺省回落到手册现值，显式提交的 false 不被覆盖', () => {
    const defaults = {owner_type: 'section', status: 'archived',
      editor_can_view_published: true};
    expect(buildManualPayload({name: 'x'}, defaults).owner_type).toBe('section');
    expect(buildManualPayload({name: 'x'}, defaults).status).toBe('archived');
    expect(buildManualPayload({name: 'x'}, defaults).editor_can_view_published)
      .toBe(true);
    expect(buildManualPayload({name: 'x', editor_can_view_published: false}, defaults)
      .editor_can_view_published).toBe(false);
  });

  it('文本字段去除首尾空白', () => {
    const payload = buildManualPayload({name: ' a ', code: ' b ', owner_name: ' c '});
    expect(payload.name).toBe('a');
    expect(payload.code).toBe('b');
    expect(payload.owner_name).toBe('c');
  });
});
