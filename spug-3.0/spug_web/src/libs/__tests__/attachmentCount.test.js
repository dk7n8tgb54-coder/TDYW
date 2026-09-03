/**
 * 附件数量回写 helper 的真实行为测试。
 *
 * 覆盖：
 * - helper 回写列表行与当前记录（真实执行代码路径，非源码字符串匹配）
 * - MobX 5 能观察到 observable 数组索引赋值（否则 antd Table 不会重渲染）
 * - 三个业务 store 的 updateAttachmentCount 已接入 helper
 */
jest.mock('libs', () => {
  const actual = jest.requireActual('../attachmentCount');
  return {
    http: { get: jest.fn(), post: jest.fn(), delete: jest.fn() },
    syncAttachmentCount: actual.syncAttachmentCount,
  };
});

const { syncAttachmentCount } = require('../attachmentCount');
const radioStore = require('../../pages/radioLicense/store').default;
const contractStore = require('../../pages/contractAgreement/store').default;
const approvalStore = require('../../pages/stationFrequencyApproval/store').default;
const bridgeStore = require('../../pages/interference/bridge/store').default;
const airStore = require('../../pages/interference/air/store').default;

function makeStore(rowId = 7) {
  return {
    records: [{ id: rowId, name: 'row-a', attachment_count: 0 }],
    record: { id: rowId, attachment_count: 0 },
  };
}

describe('syncAttachmentCount', () => {
  test('上传后回写列表行，并换成新引用（否则 Table 该行不重渲染）', () => {
    const store = makeStore();
    const oldRow = store.records[0];

    syncAttachmentCount(store, 7, 3);

    expect(store.records[0].attachment_count).toBe(3);
    expect(store.records[0]).not.toBe(oldRow);
    expect(store.records[0].name).toBe('row-a');
    expect(store.record.attachment_count).toBe(3);
  });

  test('删除到 0 时同样回写', () => {
    const store = makeStore();
    store.records[0].attachment_count = 2;
    store.record.attachment_count = 2;

    syncAttachmentCount(store, 7, 0);

    expect(store.records[0].attachment_count).toBe(0);
    expect(store.record.attachment_count).toBe(0);
  });

  test('列表行与当前记录 id 不一致时只回写命中的一方', () => {
    const store = makeStore();
    store.record = { id: 99, attachment_count: 0 };

    syncAttachmentCount(store, 7, 2);

    expect(store.records[0].attachment_count).toBe(2);
    expect(store.record.attachment_count).toBe(0);
  });

  test('recordId 数字与字符串互通（列表行 id 为字符串也能命中）', () => {
    const store = {
      records: [{ id: '7', attachment_count: 0 }],
      record: { id: '7', attachment_count: 0 },
    };

    syncAttachmentCount(store, 7, 2);

    expect(store.records[0].attachment_count).toBe(2);
    expect(store.record.attachment_count).toBe(2);
  });

  test('数量未变化时不换引用，避免无意义重渲染', () => {
    const store = makeStore();
    store.records[0].attachment_count = 2;
    store.record.attachment_count = 2;
    const oldRow = store.records[0];
    const oldRecord = store.record;

    syncAttachmentCount(store, 7, 2);

    expect(store.records[0]).toBe(oldRow);
    expect(store.record).toBe(oldRecord);
  });

  test('recordId 为空（新建未保存）时直接返回', () => {
    const store = makeStore();
    store.record = {};

    syncAttachmentCount(store, undefined, 1);

    expect(store.records[0].attachment_count).toBe(0);
    expect(store.record).toEqual({});
  });

  test('只读取 store.records 引用的 reaction 也会被触发（列表页 observer 的真实读取方式）', () => {
    const { autorun, observable } = require('mobx');
    const { syncAttachmentCount: fn } = jest.requireActual('../attachmentCount');
    const store = observable({ records: [{ id: 7, attachment_count: 0 }], record: {} });

    const seen = [];
    const dispose = autorun(() => seen.push(store.records));
    fn(store, 7, 2);
    dispose();

    expect(seen.length).toBe(2);
    expect(seen[1][0].attachment_count).toBe(2);
  });

  test('反例：原地改数组元素不会通知只观察引用的 reaction（本次缺陷根因）', () => {
    const { autorun, observable } = require('mobx');
    const store = observable({ records: [{ id: 7, attachment_count: 0 }], record: {} });

    const seen = [];
    const dispose = autorun(() => seen.push(store.records));
    store.records[0] = { id: 7, attachment_count: 2 };
    dispose();

    expect(seen.length).toBe(1);
  });
});

describe('业务 store 接入', () => {
  const cases = [
    ['radioLicense', radioStore],
    ['contractAgreement', contractStore],
    ['stationFrequencyApproval', approvalStore],
    ['interference/bridge', bridgeStore],
    ['interference/air', airStore],
  ];

  test.each(cases)('%s store.updateAttachmentCount 回写列表行与当前记录', (name, store) => {
    store.records = [{ id: 5, attachment_count: 1 }];
    store.record = { id: 5, attachment_count: 1 };

    store.updateAttachmentCount(5, 4);

    expect(store.records[0].attachment_count).toBe(4);
    expect(store.record.attachment_count).toBe(4);
  });

  test.each(cases)('%s store 中不存在该行时不抛错', (name, store) => {
    store.records = [{ id: 5, attachment_count: 1 }];
    store.record = { id: 5, attachment_count: 1 };

    expect(() => store.updateAttachmentCount(404, 2)).not.toThrow();
    expect(store.records[0].attachment_count).toBe(1);
  });
});
