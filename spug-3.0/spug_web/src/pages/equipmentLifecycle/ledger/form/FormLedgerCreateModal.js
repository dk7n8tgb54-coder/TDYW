/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板创建台账弹窗（2026-10-21，与 ExcelLedgerCreateModal 同构）。
 *
 * - 只加载当前台账类型的已发布数字表单模板（available 接口已过滤停用与
 *   无发布版本模板，每模板只返回当前在用版本）；
 * - 选择模板即用其当前在用版本创建（client_token 幂等；提交旧版本 ID 由
 *   后端行锁复核独立拒绝）；创建成功回调 onCreated（调用方进入填写视图）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Modal, Select, message} from 'antd';
import {LEDGER_TYPE_TEXT} from '../constants';

function FormLedgerCreateModal({visible, ledgerType, store, onCancel, onCreated}) {
  const [versionId, setVersionId] = useState(undefined);
  const [clientToken, setClientToken] = useState('');

  useEffect(() => {
    if (!visible) return;
    setVersionId(undefined);
    setClientToken(`flf_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`);
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
      message.warning('请选择数字表单模板');
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
    <Modal title={`选择数字表单模板创建${LEDGER_TYPE_TEXT[ledgerType] || ''}台账`}
           visible={visible} confirmLoading={store.creating} destroyOnClose
           okText="确定" cancelText="取消"
           onOk={handleOk} onCancel={onCancel}>
      <div style={{marginBottom: 10, marginTop: 4}}>模板（自动使用当前在用版本）</div>
      <Select data-testid="form-create-version" placeholder="选择数字表单模板"
              style={{width: '100%'}} value={versionId}
              onChange={value => setVersionId(value)}>
        {templates.map(t => (t.versions || []).map(v => (
          <Select.Option key={v.id} value={v.id}>
            {t.name} v{v.version_no}（{LEDGER_TYPE_TEXT[t.ledger_type] || t.ledger_type}，{v.field_count} 字段）
          </Select.Option>
        )))}
      </Select>
      {selectedVersion && (
        <div style={{color: '#999', marginTop: 4}}>
          当前在用版本：v{selectedVersion.version_no}（发布后不可变）
          ，创建后台账始终绑定该版本快照。
        </div>
      )}
    </Modal>
  );
}

export default observer(FormLedgerCreateModal);
