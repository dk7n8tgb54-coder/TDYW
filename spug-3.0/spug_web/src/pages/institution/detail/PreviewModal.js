/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Modal } from 'antd';

/**
 * 模块内轻量预览弹窗：iframe 内嵌 kkFileView/原生预览地址。
 * preview_url 为短时效 preview_token 链接（后端签发），不暴露 x-token。
 * title 必须说明版本来源（预览当前生效版 vN / 预览待发布草稿 /
 * 预览历史版本 vN），未传时回退通用标题。
 */
function PreviewModal({visible, url, fileName, title, onClose}) {
  return (
    <Modal visible={visible} width={960}
      title={title || `预览：${fileName || ''}`}
      footer={null} destroyOnClose onCancel={onClose}>
      {url && (
        <iframe title="institution-preview" src={url}
          style={{width: '100%', height: '72vh', border: 0}}/>
      )}
    </Modal>
  );
}

export default PreviewModal;
