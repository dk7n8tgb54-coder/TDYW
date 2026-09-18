/**
 * 运维台账表单提交载荷契约测试（步骤 3.2）。
 *
 * 不渲染组件，直接在 LedgerForm.prototype 实例上驱动 submit()，
 * 捕获 http.post 载荷，验证台账类型与维护周期组合满足后端
 * validate_ledger_type_cycle 契约：
 * - 巡检：maintenance_cycle 固定空串；
 * - 周月维护：提交所选周期（week/month）；
 * - 季维护：必须提交 'season'（后端校验"季维护台账维护周期固定为季"，
 *   前端若传空串则季维护台账永远无法创建）。
 */
import LedgerForm from '../LedgerForm';

const mockHttpPost = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: jest.fn(),
    post: (...args) => mockHttpPost(...args),
    put: jest.fn(),
    delete: jest.fn(),
  },
  hasPermission: jest.fn(() => true),
}));

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

function makeRowState() {
  return {
    client_key: 'k1', id: undefined, system_id: 1, template_item_id: undefined,
    inspection_point_id: undefined, location: '机柜A', item_name: '外观检查',
    standard: '', input_type: 'text', unit: '', normal_range: '', choices: [],
    number_min: null, number_max: null, is_required: false,
    value_text: '正常', value_number: null, value_bool: null,
    result: 'normal', correction_reason: '', abnormal_desc: '', na_reason: '',
    onsite_action: '', executor_name: '', executed_at: null, is_temporary: true,
  };
}

function makeInstance(ledgerType, statePatch) {
  const store = {
    ledgerType,
    record: {},
    formVisible: true,
    fetchRecords: jest.fn(),
  };
  // @observer 原地增强并返回同一类；submit 等箭头函数类属性在实例上，
  // 必须真实构造（不渲染），随后覆写 state 与 setState
  const instance = new LedgerForm({store});
  instance.props = {store};
  instance.state = {
    loading: false,
    createdFrom: 'template',
    systems: [],
    systemTypeNames: {},
    templateEntries: [],
    templateOptions: {},
    pointsMap: {},
    rows: [],
    cycle: undefined,
    header: {
      executed_date: '2026-09-19',
      executed_start: null,
      executed_end: null,
      shift: '',
      location_scope: '',
      executor_names: '',
      collaborator_names: '',
      summary: '',
      entry_note: '',
    },
    version: undefined,
    ...statePatch,
  };
  instance.setState = jest.fn(patch => {
    instance.state = {
      ...instance.state,
      ...(typeof patch === 'function' ? patch(instance.state) : patch),
    };
  });
  return instance;
}

beforeEach(() => {
  mockHttpPost.mockReset();
});

describe('LedgerForm.submit 载荷契约', () => {
  test('季维护台账必须提交 maintenance_cycle=season', async () => {
    mockHttpPost.mockResolvedValue({});
    const instance = makeInstance('seasonal');
    instance.state.rows = [makeRowState()];
    instance.submit();
    await flush();
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const payload = mockHttpPost.mock.calls[0][1];
    expect(payload.ledger_type).toBe('seasonal');
    expect(payload.maintenance_cycle).toBe('season');
  });

  test('巡检台账提交空维护周期', async () => {
    mockHttpPost.mockResolvedValue({});
    const instance = makeInstance('inspection');
    instance.state.rows = [makeRowState()];
    instance.submit();
    await flush();
    const payload = mockHttpPost.mock.calls[0][1];
    expect(payload.ledger_type).toBe('inspection');
    expect(payload.maintenance_cycle).toBe('');
  });

  test('周月维护台账提交所选周期', async () => {
    mockHttpPost.mockResolvedValue({});
    const instance = makeInstance('week_month', {cycle: 'week'});
    instance.state.rows = [makeRowState()];
    instance.submit();
    await flush();
    const payload = mockHttpPost.mock.calls[0][1];
    expect(payload.ledger_type).toBe('week_month');
    expect(payload.maintenance_cycle).toBe('week');
  });

  test('提交成功后关闭弹窗并刷新列表', async () => {
    mockHttpPost.mockResolvedValue({});
    const instance = makeInstance('inspection');
    instance.state.rows = [makeRowState()];
    instance.submit();
    await flush();
    expect(instance.props.store.formVisible).toBe(false);
    expect(instance.props.store.fetchRecords).toHaveBeenCalled();
  });
});
