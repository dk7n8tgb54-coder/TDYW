/**
 * 未读版本更新提示
 *
 * - 登录后（Layout 挂载）自动检查未读更新，有未读则弹窗展示摘要
 * - 弹窗为纯告知性质：更新由平台侧完成，用户无需也无法「允许/取消」；
 *   普通更新点击「我知道了」在服务端标记已读并关闭；点右上角关闭则
 *   保持未读，下次登录仍会提示
 * - 弹窗内提供「每次更新后自动弹出更新日志」勾选框（用户个人偏好，默认勾选）：
 *   勾选时每次更新自动弹窗；取消后不再自动弹窗，用户可从头像菜单
 *   「更新日志」随时查看，并在抽屉内重新开启
 * - 重要更新（is_required）：必须点击「我已确认，继续」调用确认接口，
 *   未确认前不允许关闭，服务端未记录确认前会持续提示
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Modal, Alert, Button, Typography, Checkbox} from 'antd';
import store from './store';

export default observer(function ReleaseNoteNotification() {
  const [visible, setVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    store.fetchUnread().then(items => {
      // 用户偏好「每次更新后自动弹出更新日志」关闭时不自动弹窗，仅保留角标与菜单入口
      if (items && items.length && store.showAfterUpdate) setVisible(true);
    });
  }, []);

  const unreadItems = store.unreadItems;
  const current = unreadItems.length ? unreadItems[0] : null;
  if (!current) return null;

  const required = !!current.is_required;
  const restCount = Math.max(store.unreadCount - 1, 0);

  /** 切换「每次更新后自动弹出更新日志」偏好：立即保存，失败时勾选框自动回弹 */
  function handlePrefChange(e) {
    store.savePopupSetting(e.target.checked).catch(() => {});
  }

  /** 确认已读：普通更新标记已读，重要更新记录确认，成功后关闭弹窗 */
  function handleConfirm() {
    setSubmitting(true);
    const action = required ? store.acknowledge : store.markRead;
    action(current.id)
      .then(() => {
        setSubmitting(false);
        setVisible(false);
      })
      .catch(() => setSubmitting(false));
  }

  const footer = [
    <Button key="confirm" type="primary" loading={submitting}
            onClick={handleConfirm}>{required ? '我已确认，继续' : '我知道了'}</Button>
  ];

  return (
    <Modal
      visible={visible}
      title={<span>版本更新 · {current.version}</span>}
      closable={!required}
      maskClosable={!required}
      keyboard={!required}
      onCancel={() => setVisible(false)}
      footer={footer}
      destroyOnClose>
      {required && (
        <Alert type="warning" showIcon style={{marginBottom: 12}}
               message="本次更新为重要变更，请阅读并确认后继续使用"/>
      )}
      <Typography.Title level={5} style={{marginBottom: 8}}>{current.title}</Typography.Title>
      <div style={{whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto'}}>
        {current.content}
      </div>
      {restCount > 0 && (
        <div style={{marginTop: 12, color: '#8c8c8c'}}>还有 {restCount} 条未读更新</div>
      )}
      <div style={{marginTop: 12, borderTop: '1px solid #f0f0f0', paddingTop: 12}}>
        <Checkbox checked={store.showAfterUpdate} onChange={handlePrefChange}>
          每次更新后自动弹出更新日志
        </Checkbox>
      </div>
    </Modal>
  );
});
