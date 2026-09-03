/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 附件数量回写 helper
 *
 * 背景：
 *   列表页的「附件」列读的是 store.records 里的 attachment_count（由列表接口下发）。
 *   在详情 / 编辑弹窗里通过 AttachmentManager 上传或删除附件后，
 *   后端数据已变更，但列表行仍是旧值，必须刷新页面或切换模块重新拉取才会更新。
 *
 * 用法：
 *   AttachmentManager 的 onCountChange 会在附件列表变化（首次加载 / 上传 / 删除）时回调，
 *   store 侧接上本 helper 即可实时同步：
 *
 *     // store.js
 *     updateAttachmentCount = (id, count) => syncAttachmentCount(this, id, count);
 *
 *     // Form.js
 *     <AttachmentManager ... onCountChange={count => S.updateAttachmentCount(info.id, count)} />
 *
 * 实现要点：
 *   - 必须整体替换 store.records 的引用：列表页 observer 组件读取的是 store.records
 *     这个属性本身，MobX 5 的依赖追踪只到这一层，原地改数组元素（records[i] = x）
 *     不会通知 observer，界面就不会刷新；
 *   - 行对象同样要换新引用，否则 antd Table 的该行不会重新渲染；
 *   - 数量未变化时不动，避免无意义的重渲染；
 *   - 同时同步 store.record，保证详情弹窗内的「附件数」等字段一起刷新。
 */
export function syncAttachmentCount(store, recordId, count) {
  if (!store || recordId === undefined || recordId === null || recordId === '') return;

  const targetId = String(recordId);
  const records = store.records || [];
  const idx = records.findIndex(r => String(r.id) === targetId);
  if (idx >= 0 && records[idx].attachment_count !== count) {
    store.records = records.map((r, i) => (
      i === idx ? { ...r, attachment_count: count } : r
    ));
  }

  const current = store.record;
  if (current && String(current.id) === targetId && current.attachment_count !== count) {
    store.record = { ...current, attachment_count: count };
  }
}
