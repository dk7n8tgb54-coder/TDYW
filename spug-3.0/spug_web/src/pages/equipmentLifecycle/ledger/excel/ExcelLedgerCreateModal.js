/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 正式新增台账入口的 Excel/WPS 模板创建弹窗（2026-10 统一入口）。
 *
 * - ledgerType 由页面注入并固定（周月维护/季维护入口各选各的模板）；
 * - 只加载当前台账类型对应的已发布 Excel 模板版本（available 接口已过滤
 *   停用模板与无发布版本模板），前端按 ledger_type 再过滤一道；
 * - 展示模板名称、版本号、字段数量、源文件名；选择版本后填写实际执行
 *   日期与执行人，经 excelLedgerStore.createLedger 调用既有
 *   POST /excel-ledgers/ 创建（client_token 幂等，后端二次校验模板
 *   类型/发布状态/启用状态/权限/租户归属）；
 * - 创建成功回调 onCreated（store 已持有详情，调用方切换到详情视图）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {DatePicker, Input, Modal, Select, message} from 'antd';
import moment from 'moment';
import {LEDGER_TYPE_TEXT} from '../constants';

function ExcelLedgerCreateModal({visible, ledgerType, store, onCancel, onCreated}) {
  const [versionId, setVersionId] = useState(undefined);
  const [executedDate, setExecutedDate] = useState(moment());
  const [executorNames, setExecutorNames] = useState('');
  const [clientToken, setClientToken] = useState('');

  useEffect(() => {
    // 每次打开重置表单并生成新的幂等令牌（一次弹窗一次创建）
    if (!visible) return;
    setVersionId(undefined);
    setExecutedDate(moment());
    setExecutorNames('');
    setClientToken(`elf_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`);
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
    if (!versionId || !executedDate) {
      message.warning('请选择模板版本和实际执行日期');
      return;
    }
    store.createLedger({
      version_id: versionId,
      executed_date: executedDate.format('YYYY-MM-DD'),
      executor_names: executorNames,
      ledger_type: ledgerType,
      client_token: clientToken,
    }).then(() => {
      onCreated && onCreated(store.detail);
    }).catch(() => {
      // 业务错误提示由 http 拦截器统一弹出，不重复提示、不关闭弹窗
    });
  };

  return (
    <Modal title={`选择 Excel/WPS 模板创建${LEDGER_TYPE_TEXT[ledgerType] || ''}台账`}
           visible={visible} confirmLoading={store.creating} destroyOnClose
           okText="确定" cancelText="取消"
           onOk={handleOk} onCancel={onCancel}>
      <div style={{marginBottom: 10, marginTop: 4}}>模板版本（发布后不可变）</div>
      <Select data-testid="excel-create-version" placeholder="选择已发布版本"
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
          源文件：{selectedVersion.source_filename}
        </div>
      )}
      <div style={{marginBottom: 10, marginTop: 12}}>实际执行日期</div>
      <DatePicker data-testid="excel-create-date" style={{width: '100%'}}
                  value={executedDate}
                  onChange={value => setExecutedDate(value)}/>
      <div style={{marginBottom: 10, marginTop: 12}}>执行人</div>
      <Input data-testid="excel-create-executor" maxLength={200} placeholder="多人以顿号分隔"
             value={executorNames}
             onChange={e => setExecutorNames(e.target.value)}/>
    </Modal>
  );
}

export default observer(ExcelLedgerCreateModal);
