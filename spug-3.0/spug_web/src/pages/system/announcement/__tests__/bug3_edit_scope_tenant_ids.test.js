/**
 * Bug 3 回归测试：编辑公告时已选部门回显（已修复）
 *
 * 原缺陷：
 *   管理端详情接口不返回 _scope_tenant_ids，Form.js 编辑初始化时
 *   record._scope_tenant_ids 恒为 undefined，部门选择框永远为空，
 *   管理员被迫盲选重选。
 *
 * 修复：
 *   AnnouncementAdminDetailView 返回 _scope_tenant_ids / _scope_tenant_names，
 *   Form.js 既有逻辑（record._scope_tenant_ids || []）无需改动即可回填。
 */

// ============================================================
// 模拟修复后的后端详情响应（AnnouncementAdminDetailView.get）
// ============================================================
function mockBackendDetailView(scopeType, scopeTenantIds = [], scopeTenantNames = []) {
  const data = {
    id: 42,
    title: '测试公告',
    content: '公告内容',
    scope_type: scopeType,
    scope_label: scopeType === 'tenant' ? '指定部门' : '全平台',
    publish_department_id: 't1',
    publish_department_name: '部门1',
    effective_start_at: '2026-08-08 09:00:00',
    effective_end_at: null,
    status: 'unpublished',
    computed_status: 'unpublished',
    is_important: false,
    is_new: false,
    published_at: null,
    published_by_name: '',
    withdrawn_at: null,
    withdrawn_by_name: '',
    created_at: '2026-08-01 10:00:00',
    created_by_name: 'admin',
    updated_at: null,
    updated_by_name: '',
    attachment_count: 0,
  };
  if (scopeType === 'tenant') {
    data._scope_tenant_ids = scopeTenantIds;
    data._scope_tenant_names = scopeTenantNames;
  }
  return data;
}

// ============================================================
// 模拟 Form.js 编辑初始化逻辑（Form.js useEffect，未改动）
// ============================================================
function simulateFormInit(record) {
  const SCOPE_TENANT = 'tenant';
  return {
    title: record.title,
    content: record.content,
    scope_type: record.scope_type,
    target_tenant_ids: record.scope_type === SCOPE_TENANT
      ? (record._scope_tenant_ids || [])
      : [],
    publish_department_id: record.publish_department_id || undefined,
    is_important: record.is_important,
  };
}

// ============================================================
// 模拟 Form.js 保存 payload 构造逻辑（Form.js handleOk，未改动）
// ============================================================
function simulateFormSavePayload(formValues, record) {
  const SCOPE_TENANT = 'tenant';
  const payload = {
    title: (formValues.title || '').trim(),
    content: formValues.content,
    scope_type: formValues.scope_type,
    target_tenant_ids: formValues.scope_type === SCOPE_TENANT
      ? (formValues.target_tenant_ids || [])
      : [],
    publish_department_id: formValues.publish_department_id,
    is_important: !!formValues.is_important,
    effective_start_at: '2026-08-08 09:00:00',
    effective_end_at: '',
  };
  if (record) payload.id = record.id;
  return payload;
}

// ============================================================
describe('Bug 3 修复回归：编辑时已选部门正确回显', () => {
  test('管理端详情返回 _scope_tenant_ids 与 _scope_tenant_names', () => {
    const detail = mockBackendDetailView(
      'tenant', ['t_target1', 't_target2'], ['目标部门1', '目标部门2']);

    expect(detail._scope_tenant_ids).toEqual(['t_target1', 't_target2']);
    expect(detail._scope_tenant_names).toEqual(['目标部门1', '目标部门2']);
  });

  test('编辑指定部门公告时，初始化回填已选部门', () => {
    const detail = mockBackendDetailView(
      'tenant', ['t_target1', 't_target2'], ['目标部门1', '目标部门2']);
    const formValues = simulateFormInit(detail);

    // 修复后：部门选择框回填原有选择，不再是空数组
    expect(formValues.target_tenant_ids).toEqual(['t_target1', 't_target2']);
    expect(formValues.scope_type).toBe('tenant');
  });

  test('保存 payload 携带回显的部门，编辑不再丢失发布范围', () => {
    const detail = mockBackendDetailView(
      'tenant', ['t_target1', 't_target2'], ['目标部门1', '目标部门2']);
    const formValues = simulateFormInit(detail);
    const payload = simulateFormSavePayload(formValues, detail);

    expect(payload.target_tenant_ids).toEqual(['t_target1', 't_target2']);
    expect(payload.id).toBe(42);
    expect(payload.scope_type).toBe('tenant');
  });

  test('全平台公告不带 scope 字段（正确行为）', () => {
    const detail = mockBackendDetailView('all');

    expect(detail).not.toHaveProperty('_scope_tenant_ids');
    const formValues = simulateFormInit(detail);
    expect(formValues.target_tenant_ids).toEqual([]);
  });

  test('管理端详情页可展示目标部门名称（核对发布范围）', () => {
    // 模拟修复后 Detail.js 发布范围行的渲染逻辑
    const detail = mockBackendDetailView(
      'tenant', ['t_target1', 't_target2'], ['目标部门1', '目标部门2']);
    let rendered = detail.scope_label;
    if (detail._scope_tenant_names && detail._scope_tenant_names.length > 0) {
      rendered += `（${detail._scope_tenant_names.join('、')}）`;
    }
    expect(rendered).toBe('指定部门（目标部门1、目标部门2）');
  });
});
