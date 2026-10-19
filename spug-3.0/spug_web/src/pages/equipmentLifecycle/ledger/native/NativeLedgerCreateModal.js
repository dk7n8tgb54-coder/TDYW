/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生模板创建台账弹窗（与 ExcelLedgerCreateModal 并列，2026-10-18）。
 *
 * - ledgerType 由页面注入并固定；只加载当前台账类型对应的已发布原生
 *   模板版本（available 接口已过滤停用模板与无发布版本模板）；
 * - 选择版本后经 nativeLedgerStore.createLedger 调用 POST /native-ledgers/
 *   创建（client_token 幂等，后端二次校验模板类型/发布状态/启用状态/
 *   权限/租户归属；执行日期由台账表格内容承载，不在创建时单列）；
 * - 创建成功回调 onCreated（store 已持有详情，调用方切换到详情视图）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Modal, Select, message} from 'antd';
import {LEDGER_TYPE_TEXT} from '../constants';

function NativeLedgerCreateModal({visible, ledgerType, store, onCancel, onCreated}) {
  const [versionId, setVersionId] = useState(undefined);
  const [clientToken, setClientToken] = useState('');

  useEffect(() => {
    // 每次打开重置表单并生成新的幂等令牌（一次弹窗一次创建）
    if (!visible) return;
    setVersionId(undefined);
    setClientToken(`eln_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`);
    store.fetchAvailable(ledgerType).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  // 双保险：available 已按 ledger_type 过滤，此处再按页面类型收敛一次
  const templates = store.available.filter(t => t.ledger_type === ledgerType);
  const selectedVersion = (() => {
    for (const t of templates) {
      const hit = (t.versions || []).find(v => v.id === versionId);
      if (hit) return hit;
    }
    return null;
  })();

  const handleOk = () => {
    if (!versionId) {
      message.warning('请选择模板版本');
      return;
    }
    store.createLedger({
      version_id: versionId,
      ledger_type: ledgerType,
      client_token: clientToken,
    }).then(() => {
      onCreated && onCreated(store.detail);
    }).catch(() => {
      // 业务错误提示由 http 拦截器统一弹出，不重复提示、不关闭弹窗
    });
  };

  return (
    <Modal title={`选择原生模板创建${LEDGER_TYPE_TEXT[ledgerType] || ''}台账`}
           visible={visible} confirmLoading={store.creating} destroyOnClose
           okText="确定" cancelText="取消"
           onOk={handleOk} onCancel={onCancel}>
      <div style={{marginBottom: 10, marginTop: 4}}>模板版本（发布后不可变）</div>
      <Select data-testid="native-create-version" placeholder="选择已发布版本"
              style={{width: '100%'}} value={versionId}
              onChange={value => setVersionId(value)}>
        {templates.map(t => (t.versions || []).map(v => (
          <Select.Option key={v.id} value={v.id}>
            {t.name} v{v.version_no}（{v.field_count} 字段）
          </Select.Option>
        )))}
      </Select>
      {selectedVersion && (
        <div style={{color: '#999', marginTop: 4}}>
          发布于 {selectedVersion.published_at
            ? String(selectedVersion.published_at).slice(0, 19).replace('T', ' ') : '—'}
        </div>
      )}
    </Modal>
  );
}

export default observer(NativeLedgerCreateModal);
