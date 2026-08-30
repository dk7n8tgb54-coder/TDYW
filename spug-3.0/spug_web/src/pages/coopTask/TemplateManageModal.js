/**
 * 材料模板管理弹窗（发起方视角）
 * 上传/删除/预览单个材料的模板附件；关闭时由父组件刷新材料清单中的模板链接
 */
import React from 'react';
import {Modal, Button} from 'antd';
import AttachmentManager from 'components/AttachmentManager';

const TEMPLATE_ACCEPT = '.pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z';

export default function TemplateManageModal(props) {
  const {item, onClose} = props;
  return (
    <Modal
      title={`材料模板：${item ? item.name : ''}`}
      visible={!!item}
      width={640}
      footer={<Button onClick={onClose}>关闭</Button>}
      onCancel={onClose}
    >
      {item && (
        <AttachmentManager
          module="coop_task"
          recordId={item.id}
          listUrl={`/api/coop-task/items/${item.id}/templates/`}
          uploadUrl={`/api/coop-task/items/${item.id}/templates/`}
          deleteUrl={`/api/coop-task/items/${item.id}/templates/`}
          downloadUrlPrefix="/api/coop-task/attachments/"
          previewUrlPrefix="/api/coop-task/attachments/"
          uploadPerm="coop.task.edit"
          deletePerm="coop.task.edit"
          maxFileSize={50}
          multiple
          maxFilesPerBatch={20}
          accept={TEMPLATE_ACCEPT}
        />
      )}
    </Modal>
  );
}
