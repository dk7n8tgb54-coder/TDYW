/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生台账详情动作集合（自 NativeLedgerDetail 拆出，组件只负责渲染）：
 * 必填/日期预检、保存草稿、完成填写、导出 PDF（先保存未提交修改）、
 * 更正模式进出（原因弹窗）、返回守卫（未保存确认）、删除与作废。
 */
import React from 'react';
import {Input, Modal, message} from 'antd';

export default function useNativeLedgerHandlers(store, channel, onBack) {
  const handleSave = () => {
    store.saveValues(channel.collect, channel.notifySaved).catch(() => {});
  };

  const handleComplete = () => {
    const missing = store.requiredMissing();
    if (missing.length) {
      message.warning(`必填字段未填写：${missing.join('、')}`);
      return;
    }
    if (!store.detail.executed_date && store.dateDraft === undefined) {
      message.warning('请先填写实际执行日期');
      return;
    }
    store.complete(channel.collect, channel.notifySaved).catch(() => {});
  };

  const handleExportPdf = async () => {
    // 导出前先保存未提交修改：保证导出内容与已保存数据一致
    if (store.hasUnsaved) {
      try {
        await store._savePendingChanges(await channel.collect().catch(() => null));
        message.success('未保存修改已先保存');
      } catch (e) {
        return; // 保存失败已提示，不继续导出
      }
    }
    const missing = store.requiredMissing();
    if (missing.length) {
      // 必填未填后端也会拦截，这里提前提示避免无效请求
      Modal.confirm({
        title: '导出前检查发现以下问题',
        content: <div>{missing.map(item => <div key={item}>· 必填字段未填写：{item}</div>)}</div>,
        okText: '仍要导出', cancelText: '取消',
        onOk: () => store.exportPdf().catch(() => {}),
      });
      return;
    }
    store.exportPdf().catch(() => {});
  };

  const handleStartCorrect = () => {
    let reason = '';
    Modal.confirm({
      title: '更正已完成台账',
      content: (
        <React.Fragment>
          <p style={{color: '#666'}}>
            更正须填写原因；提交后修改人、时间与修改前后内容将记入更正记录。
          </p>
          <Input.TextArea
            rows={3} maxLength={200}
            placeholder="请填写更正原因（必填）"
            onChange={e => { reason = e.target.value; }}/>
        </React.Fragment>
      ),
      okText: '进入更正', cancelText: '取消',
      onOk: () => {
        if (!reason.trim()) {
          message.warning('更正必须填写原因');
          return Promise.reject();
        }
        store.startCorrection(reason.trim());
      },
    });
  };

  const handleSubmitCorrect = () => {
    store.submitCorrection(channel.collect).catch(() => {});
  };

  const handleBack = () => {
    if (store.hasUnsaved) {
      // 有未保存修改先确认：继续填写保留内容，确认放弃才返回
      Modal.confirm({
        title: '有未保存的修改',
        content: '返回列表将放弃尚未保存的填写值与实际执行日期，是否继续？',
        okText: '放弃修改并返回',
        cancelText: '继续填写',
        onOk: () => onBack(),
      });
      return;
    }
    onBack();
  };

  const handleDelete = () => {
    store.deleteLedger()
      .then(() => {
        message.success('台账已删除');
        onBack();
      })
      .catch(() => {});
  };

  const handleVoid = () => {
    let reason = '';
    Modal.confirm({
      title: '作废台账',
      content: <Input placeholder="请填写作废原因" onChange={e => {
        reason = e.target.value;
      }}/>,
      onOk: () => {
        if (!reason.trim()) {
          message.warning('作废必须填写原因');
          return Promise.reject();
        }
        return store.voidLedger(reason.trim()).catch(() => {});
      },
    });
  };

  return {
    handleSave, handleComplete, handleExportPdf, handleStartCorrect,
    handleSubmitCorrect, handleBack, handleDelete, handleVoid,
  };
}
