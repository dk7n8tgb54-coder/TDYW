/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Modal } from 'antd';

/**
 * 模块内轻量预览弹窗：iframe 内嵌 kkFileView/原生预览地址。
 * preview_url 为短时效 preview_token 链接（后端签发），不暴露 x-token。
 */
function PreviewModal({visible, url, fileName, onClose}) {
  return (
    <Modal visible={visible} title={`预览：${fileName || ''}`} width={960}
      footer={null} destroyOnClose onCancel={onClose}>
      {url && (
        <iframe title="institution-preview" src={url}
          style={{width: '100%', height: '72vh', border: 0}}/>
      )}
    </Modal>
  );
}

export default PreviewModal;
