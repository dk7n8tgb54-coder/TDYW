/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * TransferListContainer - 传输列表容器组件
 * 根据文件数量智能选择使用原生列表还是虚拟列表
 */
import React from 'react';
import { observer } from 'mobx-react';
import TransferList from './TransferList';
import VirtualTransferList from './VirtualTransferList';
import { UPLOAD_CONSTANTS } from '../stores/constants/upload';

const { FALLBACK_THRESHOLD } = UPLOAD_CONSTANTS.VIRTUAL_LIST;

const TransferListContainer = (props) => {
  const {
    uploadingItems = [],
    completedItems = [],
    errorItems = [],
    cancelledItems = [],
  } = props;

  // 计算总数量（cancelledItems 由 TransferList 内部并入"失败"Tab）
  const totalCount =
    uploadingItems.length +
    completedItems.length +
    errorItems.length +
    cancelledItems.length;

  // 少量文件使用原生渲染，大量文件使用虚拟列表
  if (totalCount < FALLBACK_THRESHOLD) {
    return <TransferList {...props} />;
  }

  return <VirtualTransferList {...props} />;
};

export default observer(TransferListContainer);
