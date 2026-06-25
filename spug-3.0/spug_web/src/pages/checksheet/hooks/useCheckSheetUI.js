/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { useState, useCallback } from 'react';
import { Modal, message } from 'antd';

export default function useCheckSheetUI(loaded, updateCellStatus) {
  const [confirmVisible, setConfirmVisible] = useState(false);

  const handleRightClick = useCallback((project, itemIndex, e) => {
    e.preventDefault();

    Modal.confirm({
      title: '设置异常状态',
      content: '确定要将此检查项标记为异常吗？',
      okText: '确定',
      cancelText: '取消',
      onOk: () => {
        updateCellStatus(project, itemIndex, 'ABNORMAL');
      }
    });
  }, [updateCellStatus]);

  const handleConfirmSignature = useCallback((currentUser) => {
    if (!loaded) {
      message.warning('请先加载数据');
      return;
    }
    if (!currentUser) {
      message.warning('无法获取当前用户信息，请重新登录');
      return;
    }
    setConfirmVisible(true);
  }, [loaded]);

  return {
    confirmVisible,
    setConfirmVisible,
    handleRightClick,
    handleConfirmSignature
  };
}
