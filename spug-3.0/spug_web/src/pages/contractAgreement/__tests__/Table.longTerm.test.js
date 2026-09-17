/**
 * 合同协议 Table 长期有效合同渲染测试
 *
 * 真实渲染 Table 组件（ReactDOM + jsdom，仓库惯例），mock libs 与 components
 * （TableCard 以 antd Table 透传，保留真实 antd Table 渲染与列 render 逻辑），验证：
 * - 长期合同行：状态蓝色 Tag「长期有效」、截止日期列「长期有效」、剩余天数「-」
 * - 固定期限合同行渲染保持原样（截止日期原值、剩余天数 N 天、绿色「正常」）
 */
import React from 'react';
import ReactDOM from 'react-dom';
import { act } from 'react-dom/test-utils';
import { Table } from 'antd';
import ComTable from '../Table';
import store from '../store';
import { http } from 'libs';

jest.mock('libs', () => ({
  http: {
    get: jest.fn(() => new Promise(() => {})),
    post: jest.fn(() => Promise.resolve()),
    delete: jest.fn(() => Promise.resolve()),
  },
  hasPermission: jest.fn(() => true),
}));

jest.mock('components', () => {
  const React = require('react');
  const {Table} = require('antd');
  return {
    // 透传给真实 antd Table，保留列 render 的真实渲染行为
    TableCard: ({children, dataSource, rowKey, loading, pagination}) => (
      <Table dataSource={dataSource} rowKey={rowKey} loading={loading} pagination={pagination}>
        {children}
      </Table>
    ),
    Action: Object.assign(
      ({children}) => <span>{children}</span>,
      // Table.js 操作列使用 <Action.Button>，静态子组件必须存在
      {Button: ({children, onClick}) => <button type="button" onClick={onClick}>{children}</button>},
    ),
    AuthButton: ({children}) => <button type="button">{children}</button>,
    AttachmentCountBadge: ({count}) => <span>{count}</span>,
  };
});

if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  });
}

const LONG_TERM_ROW = {
  id: 1,
  contract_name: '长期场地合同',
  contract_no: 'HT-2026-010',
  contract_type_display: '服务保障协议',
  valid_start_date: '2026-01-01',
  valid_end_date: null,
  validity_type: 'long_term',
  has_fee: false,
  fee_amount: '',
  responsible_user_name: '用户甲',
  signing_party: '某服务中心',
  attachment_count: 0,
  computed_status: 'long_term',
  status: 'long_term',
  days_left: null,
  created_at: '2026-09-01 10:00:00',
};

const FIXED_ROW = {
  ...LONG_TERM_ROW,
  id: 2,
  contract_name: '固定采购合同',
  valid_end_date: '2026-10-17',
  validity_type: 'fixed',
  computed_status: 'normal',
  status: 'normal',
  days_left: 30,
};

const PAID_ROW = {
  ...FIXED_ROW,
  id: 3,
  contract_name: '文本费用合同',
  has_fee: true,
  fee_amount: '12000元/年',
};

function findRow(name) {
  return Array.from(container.querySelectorAll('.ant-table-tbody tr'))
    .find(tr => tr.textContent.includes(name));
}

let container = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  jest.clearAllMocks();
  http.get.mockReturnValue(new Promise(() => {}));
  store.records = [LONG_TERM_ROW, FIXED_ROW, PAID_ROW];
  store.isFetching = false;
  store.total = 3;
});

afterEach(() => {
  ReactDOM.unmountComponentAtNode(container);
  container.remove();
  container = null;
  store.records = [];
  store.total = 0;
  store.isFetching = false;
  store.formVisible = false;
  store.detailVisible = false;
  store.record = {};
});

describe('合同协议列表长期有效渲染', () => {
  it('长期合同行显示蓝色「长期有效」Tag、截止日期「长期有效」、剩余天数「-」', () => {
    act(() => {
      ReactDOM.render(<ComTable />, container);
    });
    const row = findRow('长期场地合同');
    expect(row).toBeTruthy();
    const blueTag = row.querySelector('.ant-tag-blue');
    expect(blueTag).toBeTruthy();
    expect(blueTag.textContent).toBe('长期有效');
    // 截止日期列 + 状态列共两处「长期有效」，且不出现 null/undefined 字样
    expect(row.textContent.split('长期有效').length - 1).toBeGreaterThanOrEqual(2);
    expect(row.textContent).not.toContain('null');
    expect(row.textContent).not.toContain('undefined');
  });

  it('固定期限合同行渲染保持原样（日期、剩余天数、绿色正常 Tag）', () => {
    act(() => {
      ReactDOM.render(<ComTable />, container);
    });
    const row = findRow('固定采购合同');
    expect(row).toBeTruthy();
    expect(row.textContent).toContain('2026-10-17');
    expect(row.textContent).toContain('30 天');
    const greenTag = row.querySelector('.ant-tag-green');
    expect(greenTag).toBeTruthy();
    expect(greenTag.textContent).toBe('正常');
    expect(row.querySelector('.ant-tag-blue')).toBeNull();
  });
});

describe('合同协议列表费用列文本化渲染', () => {
  it('有费用行直接显示费用文本，不拼接人民币', () => {
    act(() => {
      ReactDOM.render(<ComTable />, container);
    });
    const row = findRow('文本费用合同');
    expect(row).toBeTruthy();
    expect(row.textContent).toContain('12000元/年');
    expect(row.textContent).not.toContain('人民币');
  });

  it('无费用行显示「无」，页面不出现固定人民币字样', () => {
    act(() => {
      ReactDOM.render(<ComTable />, container);
    });
    const row = findRow('固定采购合同');
    expect(row).toBeTruthy();
    expect(row.textContent).toContain('无');
    expect(container.textContent).not.toContain('人民币');
  });
});
