/**
 * Bug 3 前端佐证测试：编辑公告时 scope_tenant_ids 丢失
 *
 * 缺陷描述：
 *   后端 AnnouncementAdminDetailView 返回 ann.to_view(include_content=True)，
 *   但 to_view() 不包含 _scope_tenant_ids 字段。
 *   前端 Form.js 编辑初始化时从 record._scope_tenant_ids 取值，
 *   该值始终为 undefined，导致 target_tenant_ids 被设为空数组。
 *   保存时空数组传给后端，_sync_scopes 清空所有范围记录。
 *
 * 验证方式：
 *   模拟后端返回的详情数据和前端 Form.js 的初始化逻辑，
 *   证明 target_tenant_ids 始终为空。
 */

// ============================================================
// 模拟后端 to_view() 返回的数据（不含 _scope_tenant_ids）
// ============================================================
function mockBackendDetailView(scopeType) {
  return {
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
    // 注意：后端 to_view() 不返回 _scope_tenant_ids
  };
}

// ============================================================
// 模拟 Form.js 编辑初始化逻辑（Form.js:20-42）
// ============================================================
function simulateFormInit(record) {
  const SCOPE_ALL = 'all';
  const SCOPE_TENANT = 'tenant';

  const init = {
    title: record.title,
    content: record.content,
    scope_type: record.scope_type,
    target_tenant_ids: record.scope_type === SCOPE_TENANT
      ? (record._scope_tenant_ids || [])   // ← 关键：后端不返回此字段
      : [],
    publish_department_id: record.publish_department_id || undefined,
    is_important: record.is_important,
  };

  return init;
}

// ============================================================
// 模拟 Form.js 保存 payload 构造逻辑（Form.js:44-61）
// ============================================================
function simulateFormSavePayload(formValues, record) {
  const SCOPE_ALL = 'all';
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
describe('Bug 3 前端佐证：编辑时 target_tenant_ids 始终为空', () => {
  test('后端详情不返回 _scope_tenant_ids 字段', () => {
    const detail = mockBackendDetailView('tenant');

    // 核心断言：后端 to_view() 不包含 _scope_tenant_ids
    expect(detail).not.toHaveProperty('_scope_tenant_ids');
    expect(detail._scope_tenant_ids).toBeUndefined();
  });

  test('编辑指定部门公告时，初始化后 target_tenant_ids 为空数组', () => {
    const detail = mockBackendDetailView('tenant');
    const formValues = simulateFormInit(detail);

    // 断言：target_tenant_ids 被设为空数组（因为 _scope_tenant_ids 为 undefined）
    expect(formValues.target_tenant_ids).toEqual([]);
    expect(formValues.scope_type).toBe('tenant');
  });

  test('编辑全平台公告时，target_tenant_ids 也为空数组（正确行为）', () => {
    const detail = mockBackendDetailView('all');
    const formValues = simulateFormInit(detail);

    // 全平台公告不需要 target_tenant_ids，空数组是正确的
    expect(formValues.target_tenant_ids).toEqual([]);
    expect(formValues.scope_type).toBe('all');
  });

  test('保存 payload 中 target_tenant_ids 为空数组', () => {
    // 模拟完整的编辑流程
    const detail = mockBackendDetailView('tenant');
    const formValues = simulateFormInit(detail);
    const payload = simulateFormSavePayload(formValues, detail);

    // 断言：保存时 target_tenant_ids 为空数组
    expect(payload.target_tenant_ids).toEqual([]);
    expect(payload.id).toBe(42);
    expect(payload.scope_type).toBe('tenant');
  });

  test('即使后端返回了 _scope_tenant_ids，前端也能正确处理（对照组）', () => {
    // 模拟修复后的后端返回
    const fixedDetail = mockBackendDetailView('tenant');
    fixedDetail._scope_tenant_ids = ['t_target1', 't_target2'];

    const formValues = simulateFormInit(fixedDetail);
    const payload = simulateFormSavePayload(formValues, fixedDetail);

    // 修复后应正确回填
    expect(formValues.target_tenant_ids).toEqual(['t_target1', 't_target2']);
    expect(payload.target_tenant_ids).toEqual(['t_target1', 't_target2']);
  });
});
