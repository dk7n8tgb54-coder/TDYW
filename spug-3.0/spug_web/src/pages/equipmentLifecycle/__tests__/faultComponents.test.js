/**
 * 设备全生命周期（步骤 3.1，单系统简化）故障组件渲染测试
 *
 * 真实渲染组件（ReactDOM + jsdom，仓库惯例），mock libs.http，验证：
 * - 故障详情窗口展示故障系统（名称+安装地点快照）、影响程度、状态操作随状态切换
 * - 2026-10 流程合并：无"开始处置"（新建即处置中）；确认恢复与关闭故障
 *   合并为一次"确认恢复并结案"（四项必填一个弹窗，终态保护）
 * - 基本信息三区块（2026-10：故障概况/处置结果/来源与登记），不展示创建人，
 *   故障登记人/登记时间在"来源与登记"区块末行
 * - 详情不再提供"受影响系统"页签
 * - 处理处置时间线按时间展示，处置类型可见，更正留痕可见
 * - "本次工时"录入已删除（2026-10）：存量工时仅时间线只读展示，
 *   新增/更正弹窗无该字段、载荷不携带 work_hours（后端 PUT 未提交保留原值）
 * - 新增处置记录：时间默认当前时间、处置类型/处置结果选填、真实提交载荷
 * - 处置记录页签（关联工单页签已随工单功能删除）与页签条数展示（取列表 total）
 * - 确认恢复并结案弹窗（2026-10 流程合并）测试拆至 faultRecoverClose.test.js
 * - 系统详情故障页签只展示本系统故障（不区分主体/受影响角色）
 * - 不使用旧 fault 页面/接口（所有请求只指向 equipment-lifecycle 前缀）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';

const mockHttpGet = jest.fn();
const mockHttpPost = jest.fn();
const mockHttpPut = jest.fn();
const mockHttpDelete = jest.fn();

jest.mock('libs', () => ({
  http: {
    get: mockHttpGet,
    post: mockHttpPost,
    put: mockHttpPut,
    delete: mockHttpDelete,
  },
  hasPermission: jest.fn(() => true),
  Permission: {isSuper: true},
  history: {},
  X_TOKEN: '',
  exportFile: jest.fn(),
}));

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false, media: query, onchange: null,
    addListener: jest.fn(), removeListener: jest.fn(),
    addEventListener: jest.fn(), removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  document.body.removeChild(container);
  [mockHttpGet, mockHttpPost, mockHttpPut, mockHttpDelete].forEach(fn => fn.mockReset());
});
// 注意：组件渲染测试不使用 jest.resetModules()（会导致 React 多副本触发 Invalid hook call）

function flush() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

const FAULT_DETAIL = {
  id: 11, fault_no: 'GZ20260918-0001',
  system: 7, system_name: '烟台通信系统', system_code: 'SYS-A1',
  system_location: '机房A',
  impact_status: 'fault', impact_status_text: '故障',
  status: 'handling', status_text: '处置中',
  occurred_at: '2026-09-18 08:30', phenomenon: '主用链路频繁丢包',
  fault_object_name: '接入交换机01', fault_object_model: 'H3C-5120', fault_object_sn: '',
  fault_component_name: '接入交换机',
  reason_analysis: '', recovered_at: null,
  recovery_close_note: '',
  recovered_by_name: '', recovered_confirmed_at: null,
  registrar_name: '登记员甲',
  created_by_name: 'admin', created_at: '2026-09-18 08:40',
};

const HANDLING_RECORDS = {
  data: [
    {id: 1, fault: 11, handled_at: '2026-09-18 09:00', handler: 2, handler_name: 'operator',
      content: '现场检查，确认光模块告警', corrections: [], created_at: '2026-09-18 09:05'},
    {id: 2, fault: 11, handled_at: '2026-09-18 09:30', handler: 2, handler_name: 'operator',
      content: '更换备用链路', created_at: '2026-09-18 09:35',
      work_hours: 1.5,
      corrections: [{old: '更换主用链路', new: '更换备用链路', reason: '笔误', by: 'operator',
        at: '2026-09-18 09:40'}]},
    {id: 3, fault: 11, handled_at: '2026-09-18 10:00', handler: 2, handler_name: 'operator',
      content: '历史记录：仅登记处置措施', corrections: [], created_at: '2026-09-18 10:05'},
  ],
  total: 3, page: 1, page_size: 100,
};

async function renderDetail(status, overrides, handlingResponse) {
  const store = require('../faultStore').default;
  const FaultDetail = require('../FaultDetail').default;
  const detail = {...FAULT_DETAIL, status, ...(overrides || {})};
  const handling = handlingResponse || HANDLING_RECORDS;
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/handling-records')) {
      return Promise.resolve(handling);
    }
    // 详情接口：后端 json_response(详情) 经 http 拦截器解包后 resolve 详情本体
    // （旧 mock 多包一层 data 会固化 fetchDetail 的双重解包缺陷）
    return Promise.resolve(detail);
  });
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    // 真实打开路径：列表行与 ?detail= 深链接均经 showDetail 进入，
    // 详情与处置记录请求由 showDetail 统一发起
    store.showDetail(detail);
    ReactDOM.render(<FaultDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

function bodyText() {
  // antd 两字按钮文案渲染为“作 废”（自动空格），比较前统一去空白
  return document.body.textContent.replace(/\s+/g, '');
}

function tabTexts() {
  return Array.from(document.querySelectorAll('.ant-tabs-tab')).map(t => t.textContent);
}

function buttonTexts() {
  // antd 两字按钮渲染为"作 废"（自动空格），比较前统一去空白
  return Array.from(document.querySelectorAll('button')).map(
    b => b.textContent.replace(/\s+/g, ''));
}

describe('故障详情窗口（单系统简化）', () => {
  it('展示故障系统名称与地点快照、影响程度与现象', async () => {
    await renderDetail('handling');
    const text = bodyText();
    expect(text).toContain('GZ20260918-0001');
    expect(text).toContain('烟台通信系统');
    expect(text).not.toContain('SYS-A1');
    expect(text).toContain('机房A');
    expect(text).toContain('主用链路频繁丢包');
    // 故障登记人展示（不代表负责整个故障）；创建人字段已从前端删除
    expect(text).toContain('故障登记人');
    expect(text).toContain('登记员甲');
    expect(text).not.toContain('创建人');
    // 登记时间取代创建时间展示（取记录创建时间）
    expect(text).not.toContain('创建时间');
    expect(text).toContain('登记时间');
    // 登记人/登记时间位于"来源与登记"区块（区块结构见下方专属 describe）
    // 已退役字段不再出现在详情（处置负责人/发现方式/级别/影响范围/故障位置）
    ['处置负责人', '发现方式', '级别', '影响范围', '故障位置'].forEach(label => {
      expect(text).not.toContain(label);
    });
  });

  it('不再提供"受影响系统"页签', async () => {
    await renderDetail('handling');
    const tabs = tabTexts();
    expect(tabs.some(t => t.includes('受影响系统'))).toBe(false);
    expect(tabs).toContain('基本信息');
    // 处置记录页签带条数（2026-10：停在基本信息页签即可看出是否已有处置记录）
    expect(tabs.some(t => t.includes('处置记录'))).toBe(true);
    // 关联工单页签已随工单功能删除（2026-09-30）
    expect(tabs.some(t => t.includes('关联工单'))).toBe(false);
  });

  it('状态按钮随当前状态切换：处置中显示确认恢复并结案与撤销故障登记（2026-10 流程合并）', async () => {
    await renderDetail('handling');
    const text = bodyText();
    // 确认恢复与关闭故障合并为一次"确认恢复并结案"
    expect(text).toContain('确认恢复并结案');
    // 原"作废"操作改称"撤销故障登记"（2026-10-03 撤销登记改版）
    expect(text).toContain('撤销故障登记');
    expect(text).not.toContain('开始处置');
    expect(text).not.toContain('关闭故障');
  });

  it('已关闭/已撤销故障不显示任何继续处置操作（终态保护）', async () => {
    await renderDetail('closed');
    expect(bodyText()).not.toContain('确认恢复并结案');
    expect(buttonTexts()).not.toContain('撤销故障登记');
    expect(buttonTexts()).not.toContain('新增处置记录');
    expect(buttonTexts()).not.toContain('更正');
    // 已撤销同样无操作入口：顶部显示只读追溯横幅 + 撤销登记区块
    await renderDetail('cancelled');
    expect(bodyText()).not.toContain('确认恢复并结案');
    expect(buttonTexts()).not.toContain('撤销故障登记');
    expect(buttonTexts()).not.toContain('新增处置记录');
    // 只读追溯提示与撤销信息（原因/时间/人）正常展示
    expect(bodyText()).toContain('该登记已撤销，仅供历史追溯');
    expect(bodyText()).toContain('撤销原因');
    expect(bodyText()).toContain('撤销时间');
    expect(bodyText()).toContain('撤销人');
  });

  it('处置时间线按时间展示、处置人与更正留痕可见', async () => {
    await renderDetail('handling');
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
    const handlingTab = tabs.find(t => t.textContent.includes('处置记录'));
    await act(async () => {
      handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    const text = bodyText();
    expect(text).toContain('现场检查，确认光模块告警');
    expect(text).toContain('更换备用链路');
    expect(text).toContain('历史记录：仅登记处置措施');
    // 处置人（2026-10 用户文案定名；2026-09 曾用"进展记录人"，旧标签不再出现）
    expect(text).toContain('处置人：operator');
    expect(text).not.toContain('进展记录人');
    // 更正留痕：原内容与原因
    expect(text).toContain('笔误');
    expect(text).toContain('由operator更正');
    // 更正按钮可见（可编辑状态）
    expect(text).toContain('更正');
    // 新增处置记录入口可见
    expect(text).toContain('新增处置记录');
    // 页签说明按现行字段口径描述（处置时间/处置人/处置措施）；
    // 工单功能已删除、处置类型字段已退役（2026-10-05），旧提示不再保留
    expect(text).toContain('每条记录处置时间、处置人与处置措施');
  });

  it('所有请求只指向 equipment-lifecycle 前缀（不使用旧 fault 接口）', async () => {
    await renderDetail('handling');
    const urls = mockHttpGet.mock.calls.map(call => call[0]);
    expect(urls.length).toBeGreaterThan(0);
    for (const url of urls) {
      expect(url.startsWith('/api/equipment-lifecycle/')).toBe(true);
    }
    expect(urls.some(u => u.includes('/fault/'))).toBe(false);
  });
});

describe('处置记录刷新响应式（2026-09 新增处置记录后时间线不更新缺陷回归）', () => {
  it('仅更新 handlingRecords（不动 isDetailFetching）时间线立即显示新记录', async () => {
    // 缺陷机理：HandlingTimeline 未包 observer 时，读取的 handlingRecords
    // 不被 MobX 追踪，时间线只能靠父组件因 isDetailFetching/detail 变化
    // 重渲染"搭车"刷新；新增处置记录成功后若无人触发详情刷新，新记录不显示。
    const store = await renderDetail('handling');
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
    const handlingTab = tabs.find(t => t.textContent.includes('处置记录'));
    await act(async () => {
      handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    expect(bodyText()).toContain('现场检查，确认光模块告警');
    // 模拟 addHandlingRecord 成功后 fetchHandlingRecords 的应用结果：
    // 只发生 handlingRecords 变化（详情请求未被触发）
    await act(async () => {
      store.handlingRecords = [...store.handlingRecords, {
        id: 99, fault: 11, handled_at: '2026-09-18 11:00', handler: 2,
        handler_name: 'operator', recorder_name: '记录员乙',
        content: '新添加的处置措施XYZ', corrections: [],
      }];
    });
    await act(async () => {await flush();});
    expect(bodyText()).toContain('新添加的处置措施XYZ');
    expect(bodyText()).toContain('记录员乙');
  });

  it('仅结束 isHandlingFetching 时时间线 Spin 同步停止（不冻结转圈）', async () => {
    const store = await renderDetail('handling');
    // antd Tabs 未激活页签不渲染内容：先切到处置记录页签
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
    const handlingTab = tabs.find(t => t.textContent.includes('处置记录'));
    await act(async () => {
      handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    // 初始请求已完成，Spin 应为停止状态；再模拟一次进行中→完成，
    // 若 Spin 未被 observer 追踪，其 spinning 状态会冻结在旧值
    await act(async () => {
      store.isHandlingFetching = true;
    });
    await act(async () => {await flush();});
    const spinCountWhileFetching = Array.from(
      document.querySelectorAll('.ant-spin-spinning')).length;
    await act(async () => {
      store.isHandlingFetching = false;
    });
    await act(async () => {await flush();});
    const spinCountAfterFetch = Array.from(
      document.querySelectorAll('.ant-spin-spinning')).length;
    expect(spinCountWhileFetching).toBeGreaterThan(0);
    expect(spinCountAfterFetch).toBe(0);
  });

  it('打开详情只发起一次详情请求与一次处置记录请求（无重复并发）', async () => {
    await renderDetail('handling');
    const detailCalls = mockHttpGet.mock.calls
      .filter(call => call[0] === '/api/equipment-lifecycle/faults/11/').length;
    const handlingCalls = mockHttpGet.mock.calls
      .filter(call => call[0].includes('/handling-records')).length;
    expect(detailCalls).toBe(1);
    expect(handlingCalls).toBe(1);
  });
});

describe('处置记录页签条数展示（2026-10：停在基本信息页签即可看出是否已有处置记录）', () => {
  it('打开详情不切页签即显示处置记录数（showDetail 统一拉取处置记录列表）', async () => {
    await renderDetail('handling');
    const handlingTab = tabTexts().find(t => t.includes('处置记录'));
    expect(handlingTab).toBe('处置记录（3）');
  });

  it('条数取列表接口 total，不受单页截断影响', async () => {
    // 后端默认分页 100 条：本页仅返回 1 条但 total=7，页签应显示 7 而非 1
    await renderDetail('handling', null,
      {data: [HANDLING_RECORDS.data[0]], total: 7, page: 1, page_size: 100});
    const handlingTab = tabTexts().find(t => t.includes('处置记录'));
    expect(handlingTab).toBe('处置记录（7）');
  });

  it('追加处置记录重新拉取列表后条数随 total 同步更新', async () => {
    const store = await renderDetail('handling');
    expect(tabTexts().find(t => t.includes('处置记录'))).toBe('处置记录（3）');
    mockHttpGet.mockImplementation((url) => {
      if (url.includes('/handling-records')) {
        return Promise.resolve({
          data: [...HANDLING_RECORDS.data, {
            id: 4, fault: 11, handled_at: '2026-09-18 11:00',
            recorder_name: '记录员乙',
            content: '持续观察，链路稳定', corrections: [],
          }],
          total: 4, page: 1, page_size: 100,
        });
      }
      return Promise.resolve(FAULT_DETAIL);
    });
    await act(async () => {
      await store.fetchHandlingRecords();
    });
    await act(async () => {await flush();});
    expect(tabTexts().find(t => t.includes('处置记录'))).toBe('处置记录（4）');
  });
});

// 系统详情故障页签测试（2026-10-03 文件超限拆出）：
// 见 faultRecordsTab.test.js

describe('故障影响系统运行开关（运行状态与部件维修分离）', () => {
  async function renderForm(record, detail) {
    const store = require('../faultStore').default;
    const FaultForm = require('../FaultForm').default;
    store.systems = [{id: 7, name: '烟台通信系统', install_location: '机房A'}];
    store.record = record || {};
    store.formVisible = true;
    // 编辑模式：mock 详情回填请求（http 拦截器解包后 resolve 详情本体）
    mockHttpGet.mockResolvedValue(
      detail || {id: 11, system: 7, affects_system_operation: false, impact_status: '',
        occurred_at: '2026-09-18 08:30', phenomenon: '板卡告警'});
    ReactDOM.unmountComponentAtNode(container);
    await act(async () => {
      ReactDOM.render(<FaultForm/>, container);
    });
    await act(async () => {await flush();});
  }

  function switchNode() {
    return document.querySelector('.ant-switch');
  }

  it('新增故障默认不影响系统运行：开关关闭、不渲染影响程度选择', async () => {
    await renderForm({});
    const sw = switchNode();
    expect(sw).toBeTruthy();
    expect(sw.classList.contains('ant-switch-checked')).toBe(false);
    expect(document.body.textContent).not.toContain('系统影响程度');
  });

  it('开启影响系统运行后出现必填的影响程度选择', async () => {
    await renderForm({});
    await act(async () => {
      switchNode().dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    expect(switchNode().classList.contains('ant-switch-checked')).toBe(true);
    expect(document.body.textContent).toContain('系统影响程度');
  });

  it('编辑部件故障（不影响运行）回显开关关闭', async () => {
    await renderForm({id: 11}, {id: 11, system: 7, affects_system_operation: false,
      impact_status: '', occurred_at: '2026-09-18 08:30', phenomenon: '板卡告警'});
    await act(async () => {await flush();});
    const sw = switchNode();
    expect(sw).toBeTruthy();
    expect(sw.classList.contains('ant-switch-checked')).toBe(false);
    expect(document.body.textContent).not.toContain('系统影响程度');
  });

  it('编辑影响运行的故障回显开关开启与影响程度', async () => {
    await renderForm({id: 12}, {id: 12, system: 7, affects_system_operation: true,
      impact_status: 'interrupted', occurred_at: '2026-09-18 08:30', phenomenon: '链路中断'});
    await act(async () => {await flush();});
    const sw = switchNode();
    expect(sw).toBeTruthy();
    expect(sw.classList.contains('ant-switch-checked')).toBe(true);
    expect(document.body.textContent).toContain('系统影响程度');
  });
});

describe('故障首报表单精简（2026-09，字段退役后口径）', () => {
  // 编辑模式回填用的历史故障详情：已退役字段不再由后端返回
  const EDIT_DETAIL = {
    id: 11, system: 7, affects_system_operation: true, impact_status: 'fault',
    occurred_at: '2026-09-18 08:30', phenomenon: '主用链路频繁丢包',
    fault_object_name: '接入交换机01', fault_object_model: 'H3C-5120',
    fault_object_sn: 'SN001', reason_analysis: '',
  };

  async function renderForm(record, detail) {
    const store = require('../faultStore').default;
    const FaultForm = require('../FaultForm').default;
    store.systems = [{id: 7, name: '烟台通信系统', install_location: '机房A'}];
    store.record = record || {};
    store.formVisible = true;
    mockHttpGet.mockResolvedValue(detail || EDIT_DETAIL);
    ReactDOM.unmountComponentAtNode(container);
    await act(async () => {
      ReactDOM.render(<FaultForm/>, container);
    });
    await act(async () => {await flush();});
  }

  it('新增首报表单只显示精简字段，不再渲染发现方式/级别/历史设备字段', async () => {
    await renderForm({});
    const text = bodyText();
    expect(text).toContain('故障部位/设备');
    expect(text).toContain('故障现象');
    // "原因分析"自 2026-10 起为"初步原因分析"子串（新增表单含初步判断区块），
    // 该字面断言失效移除，改由 faultReasonAnalysis.test.js 正向覆盖
    ['发现方式', '故障级别', '影响范围', '故障位置', '故障对象名称',
      '故障对象型号', '对象编号/序列号'].forEach(label => {
      expect(text).not.toContain(label);
    });
  });

  it('字段顺序：故障部位/设备位于故障发生时间与故障现象之间（新增与编辑一致）', async () => {
    await renderForm({});
    let text = bodyText();
    expect(text.indexOf('故障发生时间')).toBeGreaterThan(-1);
    expect(text.indexOf('故障发生时间')).toBeLessThan(text.indexOf('故障部位/设备'));
    expect(text.indexOf('故障部位/设备')).toBeLessThan(text.indexOf('故障现象'));
    await renderForm({id: 11}, EDIT_DETAIL);
    text = bodyText();
    expect(text.indexOf('故障发生时间')).toBeLessThan(text.indexOf('故障部位/设备'));
    expect(text.indexOf('故障部位/设备')).toBeLessThan(text.indexOf('故障现象'));
  });

  it('编辑表单保留原因分析入口（处置阶段填写），历史字段同样不回进表单', async () => {
    await renderForm({id: 11}, EDIT_DETAIL);
    const text = bodyText();
    expect(text).toContain('原因分析');
    expect(text).not.toContain('发现方式');
    expect(text).not.toContain('故障级别');
  });

  it('编辑提交载荷不携带已退役字段与历史设备字段（由后端保留原值）', async () => {
    await renderForm({id: 11}, EDIT_DETAIL);
    mockHttpPut.mockResolvedValue({});
    const okButton = Array.from(document.querySelectorAll('.ant-modal-footer button'))
      .find(b => b.className.includes('ant-btn-primary'));
    await act(async () => {
      okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    expect(mockHttpPut.mock.calls[0][0]).toBe('/api/equipment-lifecycle/faults/11/');
    const payload = mockHttpPut.mock.calls[0][1];
    ['discovery', 'level', 'impact_scope', 'fault_location', 'fault_object_model',
      'fault_object_sn'].forEach(key => {
      expect(payload).not.toHaveProperty(key);
    });
    // 表单仍管理的精简字段正常提交（必填校验由回填值满足）
    expect(payload.system).toBe(7);
    expect(payload.affects_system_operation).toBe(true);
    expect(payload.impact_status).toBe('fault');
    expect(payload.occurred_at).toBe('2026-09-18 08:30');
    expect(payload.fault_object_name).toBe('接入交换机01');
    expect(payload.phenomenon).toBe('主用链路频繁丢包');
  });
});

describe('故障详情系统影响程度展示（运行状态与部件维修分离）', () => {
  it('影响运行的故障展示影响程度标签，部件故障展示"不影响运行"', async () => {
    await renderDetail('handling', {affects_system_operation: true});
    let text = bodyText();
    expect(text).toContain('故障');
    expect(text).not.toContain('不影响运行');
    await renderDetail('handling', {affects_system_operation: false, impact_status: ''});
    text = bodyText();
    expect(text).toContain('不影响运行');
  });
});

describe('故障详情字段顺序', () => {
  it('故障部位/设备位于发生时间之后、故障现象之前（与新增/编辑表单顺序一致）', async () => {
    await renderDetail('handling');
    const text = bodyText();
    const atObject = text.indexOf('故障部位/设备');
    expect(atObject).toBeGreaterThan(-1);
    expect(text.indexOf('发生时间')).toBeLessThan(atObject);
    expect(atObject).toBeLessThan(text.indexOf('故障现象'));
  });
});

describe('基本信息三区块（2026-10 重组：故障概况/处置结果/来源与登记）', () => {
  it('三区块依次展示；标题区不再重复系统/地点/发生时间/登记人（各只出现一次）', async () => {
    await renderDetail('handling');
    const text = bodyText();
    const atProfile = text.indexOf('故障概况');
    const atResult = text.indexOf('处置结果');
    const atSource = text.indexOf('来源与登记');
    const atOverview = text.indexOf('处置记录概览');
    expect(atProfile).toBeGreaterThan(-1);
    expect(atResult).toBeGreaterThan(atProfile);
    expect(atSource).toBeGreaterThan(atResult);
    expect(atOverview).toBeGreaterThan(atSource);
    // 旧标题区事实行已删除：系统名/安装地点/发生时间/登记人姓名全页各只出现一次
    // （bodyText 已折叠空白，日期按折叠后形态匹配）
    expect(text.split('烟台通信系统').length - 1).toBe(1);
    expect(text.split('机房A').length - 1).toBe(1);
    expect(text.split('2026-09-1808:30').length - 1).toBe(1);
    expect(text.split('登记员甲').length - 1).toBe(1);
  });

  it('处置中且无任何恢复数据：处置结果只显示"尚未完成恢复确认"，不铺空的恢复字段', async () => {
    await renderDetail('handling');
    const text = bodyText();
    // 原因分析始终展示（无内容显示"-"）
    expect(text).toContain('原因分析');
    expect(text).toContain('尚未完成恢复确认');
    ['恢复时间', '恢复确认人', '结案说明'].forEach(label => {
      expect(text).not.toContain(label);
    });
  });

  it('处置中但已有部分恢复数据时正常展示恢复字段（含统一结案说明）', async () => {
    await renderDetail('handling', {recovery_close_note: '已倒备用链路，等待备件'});
    const text = bodyText();
    expect(text).not.toContain('尚未完成恢复确认');
    expect(text).toContain('恢复时间');
    expect(text).toContain('结案说明');
    expect(text).toContain('已倒备用链路，等待备件');
    // 旧两字段不再同时展示（统一为结案说明）
    expect(text).not.toContain('恢复确认信息');
    expect(text).not.toContain('最终结果');
  });

  it('已关闭故障完整展示恢复时间/确认人/结案说明（终态不丢恢复事实）', async () => {
    await renderDetail('closed', {
      recovered_at: '2026-09-18 12:00',
      recovered_by_name: '确认人甲',
      recovered_confirmed_at: '2026-09-18 12:10',
      recovery_close_note: '更换备件并复测通过，业务验证通过',
    });
    const text = bodyText();
    expect(text).not.toContain('尚未完成恢复确认');
    expect(text).toContain('恢复时间');
    expect(text).toContain('2026-09-1812:00');
    expect(text).toContain('确认人甲');
    expect(text).toContain('更换备件并复测通过，业务验证通过');
    expect(text).not.toContain('恢复确认信息');
    expect(text).not.toContain('最终结果');
    // 结案说明位于原因分析（已关闭展示最终原因）之后、处置结果区块之内
    expect(text.indexOf('原因分析')).toBeLessThan(text.indexOf('结案说明'));
    // 处置结果区块在"来源与登记"之前：结案说明在故障登记人之前出现
    expect(text.indexOf('结案说明')).toBeLessThan(text.indexOf('故障登记人'));
  });

  it('来源与登记区块按来源类型展示追溯入口，登记人/登记时间始终展示', async () => {
    await renderDetail('handling', {
      source_type: 'runtime_record', source_runtime_record: 33,
      source_runtime_record_no: 'YX20261001-0001',
    });
    let text = bodyText();
    expect(text).toContain('来源运行记录');
    expect(text).toContain('YX20261001-0001');
    expect(text).toContain('故障登记人');
    expect(text).toContain('登记时间');
    await renderDetail('handling', {
      source_type: 'inspection_record', source_inspection_sheet: 8,
      source_inspection_sheet_no: 'XJ20260918-01',
      source_inspection_duty_date: '2026-09-18',
      source_inspection_round_text: '11:00-11:20',
      source_inspection_item_name: '输出功率',
    });
    text = bodyText();
    // 日巡视已下线（2026-10-11）：来源巡检单仅展示追溯文本（单号/值班日期/
    // 轮次/检查项），不再渲染跳转按钮
    expect(text).toContain('来源巡检单');
    expect(text).toContain('XJ20260918-01');
    expect(text).toContain('2026-09-18');
    expect(text).toContain('11:00-11:20');
    expect(text).toContain('输出功率');
    expect(text).toContain('日巡视功能已下线');
    const inspectionButtons = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent.includes('XJ20260918-01'));
    expect(inspectionButtons).toHaveLength(0);
    await renderDetail('handling', {
      source_type: 'ledger_item', source_ledger: 5,
      source_ledger_no: 'TZ20260901-001', source_ledger_type: 'week_month',
    });
    text = bodyText();
    expect(text).toContain('来源台账');
    expect(text).toContain('TZ20260901-001');
  });
});

const moment = require('moment');

async function openDetailHandlingTab() {
  await renderDetail('handling');
  const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
  const handlingTab = tabs.find(t => t.textContent.includes('处置记录'));
  await act(async () => {
    handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

async function openAddModal() {
  await openDetailHandlingTab();
  const addButton = Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes('新增处置记录'));
  expect(addButton).toBeTruthy();
  await act(async () => {
    addButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

function modalText() {
  // 详情已改为 Modal（2026-10-02）：动作弹窗挂载在后，取 DOM 中最后一个（顶层对话框）
  const modals = document.querySelectorAll('.ant-modal');
  return modals.length ? modals[modals.length - 1].textContent : '';
}

function topModal() {
  const modals = document.querySelectorAll('.ant-modal');
  return modals.length ? modals[modals.length - 1] : null;
}

function findFormItem(labelText) {
  const scope = topModal() || document;
  const items = Array.from(scope.querySelectorAll('.ant-form-item'));
  return items.find(n => {
    const label = n.querySelector('.ant-form-item-label');
    return label && label.textContent.includes(labelText);
  }) || null;
}

async function setTextareaValue(label, value) {
  const textarea = findFormItem(label).querySelector('textarea');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

async function submitModal(method) {
  const mock = method === 'put' ? mockHttpPut : mockHttpPost;
  mock.mockResolvedValue({});
  const okButton = Array.from(document.querySelectorAll('.ant-modal-footer button'))
    .find(b => b.className.includes('ant-btn-primary'));
  await act(async () => {
    okButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

describe('新增处置记录弹窗（时间默认当前时间、记录人必填手输、真实提交）', () => {
  it('弹窗强制时间/处置措施/处置人，时间默认当前时间，已删除字段不再出现', async () => {
    await openAddModal();
    const text = modalText();
    expect(text).toContain('处置时间');
    expect(text).toContain('处置措施');
    // "本次工时"字段已删除（2026-10）：弹窗不再出现
    expect(text).not.toContain('本次工时');
    // 处置类型/处置结果字段已删除（2026-10-05）：弹窗不再出现
    expect(text).not.toContain('处置类型');
    expect(text).not.toContain('处置结果');
    // 时间默认当前时间（DatePicker input 已带格式化值）
    const timeInput = findFormItem('处置时间').querySelector('input');
    expect(timeInput.value).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    await typeAndEnter('处置人', '记录人甲');
    await setTextareaValue('处置措施', '发信机告警，现场检查中');
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/handling-records/');
    expect(payload.content).toBe('发信机告警，现场检查中');
    expect(payload.recorder_name).toBe('记录人甲');
    // 处置类型/处置结果已删除：payload 不再携带
    expect(payload).not.toHaveProperty('progress_type');
    expect(payload).not.toHaveProperty('result');
    // 新增处置记录不再提交工时（字段已删除，后端默认存 null）
    expect(payload).not.toHaveProperty('work_hours');
    expect(payload.handled_at).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    expect(Math.abs(moment(payload.handled_at, 'YYYY-MM-DD HH:mm').diff(moment(), 'minutes')))
      .toBeLessThanOrEqual(1);
  });
});

describe('更正处置记录弹窗（回显与留痕提交）', () => {
  it('更正处置记录回显原处置人，payload 不携带已删除字段，留痕提交', async () => {
    await openDetailHandlingTab();
    // 点击第一条存量记录的"更正"
    const firstItem = Array.from(document.querySelectorAll('.ant-timeline-item'))
      .find(n => n.textContent.includes('现场检查，确认光模块告警'));
    const correctButton = Array.from(firstItem.querySelectorAll('button'))
      .find(b => b.textContent.includes('更正'));
    await act(async () => {
      correctButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    // 回显原处置人（历史记录无姓名时回落操作账号用户名）
    expect(selectionTags('处置人')).toEqual(['operator']);
    // 已删除字段（处置类型/处置结果）不再出现在弹窗
    expect(modalText()).not.toContain('处置类型');
    expect(modalText()).not.toContain('处置结果');
    // 更正必须填写原因
    await setTextareaValue('更正原因', '文字修订更正');
    await submitModal('put');
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPut.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/handling-records/1/');
    expect(payload.recorder_name).toBe('operator');
    expect(payload).not.toHaveProperty('progress_type');
    expect(payload).not.toHaveProperty('result');
    expect(payload.correction_reason).toBeTruthy();
  });

  it('"本次工时"录入已删除：存量工时仅时间线只读展示，更正载荷不携带 work_hours', async () => {
    await openDetailHandlingTab();
    // 存量记录的工时仍在时间线只读展示（bodyText 折叠空白："工时 1.5h"）
    expect(bodyText()).toContain('工时1.5h');
    // 更正弹窗不再提供本次工时字段
    const item = Array.from(document.querySelectorAll('.ant-timeline-item'))
      .find(n => n.textContent.includes('更换备用链路'));
    const correctButton = Array.from(item.querySelectorAll('button'))
      .find(b => b.textContent.includes('更正'));
    await act(async () => {
      correctButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    expect(modalText()).not.toContain('本次工时');
    await setTextareaValue('更正原因', '补充更正说明');
    await submitModal('put');
    expect(mockHttpPut).toHaveBeenCalledTimes(1);
    const [, payload] = mockHttpPut.mock.calls[0];
    // 载荷不携带 work_hours：后端 PUT 未提交时保留原值，存量工时不被清除
    expect(payload).not.toHaveProperty('work_hours');
  });
});

// ===== 故障登记人与处置人（2026-09 人员记录优化，手动输入姓名，可多个） =====

async function renderFaultForm({record = {}, detail = null} = {}) {
  const store = require('../faultStore').default;
  const FaultForm = require('../FaultForm').default;
  store.systems = [{id: 7, name: '烟台通信系统', install_location: '机房A'}];
  store.record = record;
  store.formVisible = true;
  if (detail) {
    mockHttpGet.mockResolvedValue(detail);
  }
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    ReactDOM.render(<FaultForm/>, container);
  });
  await act(async () => {await flush();});
}

// tags 选择器中已确认的姓名标签文本
function selectionTags(formLabel) {
  const item = findFormItem(formLabel);
  if (!item) return null;
  return Array.from(item.querySelectorAll('.ant-select-selection-item'))
    .map(n => n.getAttribute('title') || n.textContent);
}

function selectInput(formLabel) {
  return findFormItem(formLabel).querySelector('.ant-select input');
}

async function typeAndEnter(formLabel, text) {
  // 输入与回车分两次 act：模拟真实输入节奏（同 act 内提交不触发）
  const input = selectInput(formLabel);
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, text);
    input.dispatchEvent(new Event('input', {bubbles: true}));
  });
  await act(async () => {await flush();});
  await act(async () => {
    const ev = new KeyboardEvent('keydown', {key: 'Enter', bubbles: true});
    Object.defineProperty(ev, 'keyCode', {get: () => 13});
    Object.defineProperty(ev, 'which', {get: () => 13});
    input.dispatchEvent(ev);
  });
  await act(async () => {await flush();});
}

async function renderDetailCustom({detail, records}) {
  const store = require('../faultStore').default;
  const FaultDetail = require('../FaultDetail').default;
  mockHttpGet.mockImplementation((url) => {
    if (url.includes('/handling-records')) {
      return Promise.resolve({data: records, total: records.length, page: 1, page_size: 100});
    }
    return Promise.resolve(detail);
  });
  ReactDOM.unmountComponentAtNode(container);
  await act(async () => {
    // 真实打开路径：请求由 showDetail 统一发起（挂载不再重复请求）
    store.showDetail(detail);
    ReactDOM.render(<FaultDetail/>, container);
  });
  await act(async () => {await flush();});
  return store;
}

// 在自定义详情上打开"新增处置记录"弹窗（不经过公共 renderDetail，避免详情被重置）
async function openAddModalOn(detail) {
  await renderDetailCustom({detail, records: HANDLING_RECORDS.data});
  const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
  const handlingTab = tabs.find(t => t.textContent.includes('处置记录'));
  await act(async () => {
    handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
  const addButton = Array.from(document.querySelectorAll('button'))
    .find(b => b.textContent.replace(/\s+/g, '').includes('新增处置记录'));
  expect(addButton).toBeTruthy();
  await act(async () => {
    addButton.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  });
  await act(async () => {await flush();});
}

describe('故障登记人与处置人（手动输入姓名，可多个）', () => {
  it('新增故障表单显示"故障登记人"，不预填任何默认姓名，输入姓名回车可添加多人', async () => {
    await renderFaultForm();
    const text = bodyText();
    expect(text).toContain('故障登记人');
    // 初始为空：占位文案可见（必填、不预填当前用户/登记人）
    expect(text).toContain('输入姓名后回车确认');
    expect(selectionTags('故障登记人')).toEqual([]);
    // 手输姓名回车添加（无需是系统用户），支持多人
    await typeAndEnter('故障登记人', '实际登记人张三');
    await typeAndEnter('故障登记人', '实际登记人李四');
    expect(selectionTags('故障登记人')).toEqual(['实际登记人张三', '实际登记人李四']);
  });

  it('编辑故障表单不显示故障登记人（登记人仅新增可填，后端保留原值）', async () => {
    await renderFaultForm({record: {id: 11}, detail: FAULT_DETAIL});
    expect(bodyText()).not.toContain('故障登记人');
  });

  it('新增处置记录表单显示"处置人"，不预填（登记人/当前用户均不默认），手输回车后真实提交', async () => {
    // 故障已登记登记人姓名也不联动预填
    await openAddModalOn({...FAULT_DETAIL, registrar_name: '值班甲、值班乙'});
    expect(modalText()).toContain('处置人');
    expect(selectionTags('处置人')).toEqual([]);
    // 手输姓名回车添加后真实提交（顿号拼接）
    await typeAndEnter('处置人', '实际记录人李四');
    await setTextareaValue('处置措施', '更换主板后本方测试正常');
    await submitModal('post');
    expect(mockHttpPost).toHaveBeenCalledTimes(1);
    const [url, payload] = mockHttpPost.mock.calls[0];
    expect(url).toBe('/api/equipment-lifecycle/faults/11/handling-records/');
    expect(payload.recorder_name).toBe('实际记录人李四');
    expect(payload.content).toBe('更换主板后本方测试正常');
  });

  it('历史记录缺处置人姓名时回落操作账号用户名，两者皆无显示"-"', async () => {
    await renderDetailCustom({
      detail: {...FAULT_DETAIL, registrar_name: ''},
      records: [
        {id: 9, fault: 11, handled_at: '2026-01-05 09:00',
          handler: 2, handler_name: 'operator', recorder_name: '',
          content: '历史记录（有操作账号）', corrections: []},
        {id: 10, fault: 11, handled_at: '2026-01-05 10:00',
          handler: null, handler_name: '', recorder_name: '',
          content: '更早历史记录（无任何人员）', corrections: []},
      ],
    });
    const tabs = Array.from(document.querySelectorAll('.ant-tabs-tab'));
    const handlingTab = tabs.find(t => t.textContent.includes('处置记录'));
    await act(async () => {
      handlingTab.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    });
    await act(async () => {await flush();});
    const text = bodyText();
    // 历史记录回落操作账号用户名；无任何人员显示"-"；不渲染报错
    expect(text).toContain('处置人：operator');
    expect(text).toContain('处置人：-');
    expect(text).toContain('历史记录（有操作账号）');
    expect(text).toContain('更早历史记录（无任何人员）');
    // 详情：历史故障无登记人显示"-"
    expect(text).toContain('故障登记人');
  });
});
