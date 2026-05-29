/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 审批流程Hook
 * 
 * 封装通用的审批操作逻辑
 */
import React, { useCallback } from 'react';
import { Modal, Form, Input, message } from 'antd';
import { http } from 'libs';

/**
 * 创建审批确认弹窗
 * @param {string} title - 弹窗标题
 * @param {string} formId - 表单ID
 * @param {Function} onSubmit - 提交回调
 */
const createApprovalModal = (title, formId, onSubmit) => {
  Modal.confirm({
    title,
    content: (
      <Form id={formId} layout="vertical">
        <Form.Item label="备注" name="remarks">
          <Input.TextArea rows={3} placeholder="请输入备注" />
        </Form.Item>
      </Form>
    ),
    onOk: () => {
      const textarea = document.getElementById(formId)?.querySelector('textarea');
      const remarks = textarea?.value || '';
      return onSubmit(remarks);
    }
  });
};

/**
 * 使用审批操作的Hook
 * 
 * @param {Object} options
 * @param {string} options.apiUrl - API端点URL
 * @param {Function} options.onSuccess - 操作成功回调
 * @param {Function} options.refreshData - 刷新数据回调
 */
export function useApproval({ apiUrl, onSuccess, refreshData }) {
  
  /**
   * 审批通过
   */
  const approve = useCallback((record) => {
    createApprovalModal(
      '审批通过',
      'approveForm',
      (remarks) => {
        return http.patch(apiUrl, {
          id: record.id,
          status: 'approved',
          remarks
        }).then(() => {
          message.success('审批成功');
          refreshData();
          if (onSuccess) onSuccess();
        });
      }
    );
  }, [apiUrl, onSuccess, refreshData]);

  /**
   * 审批拒绝
   */
  const reject = useCallback((record) => {
    createApprovalModal(
      '审批拒绝',
      'rejectForm',
      (remarks) => {
        return http.patch(apiUrl, {
          id: record.id,
          status: 'rejected',
          remarks
        }).then(() => {
          message.success('已拒绝');
          refreshData();
          if (onSuccess) onSuccess();
        });
      }
    );
  }, [apiUrl, onSuccess, refreshData]);

  /**
   * 撤销
   */
  const cancel = useCallback((record, options = {}) => {
    const { withRestore = false, extraParams = {} } = options;
    
    Modal.confirm({
      title: '撤销确认',
      content: withRestore 
        ? '确定要撤销吗？撤销后将恢复原排班。'
        : '确定要撤销此申请吗？',
      onOk: () => {
        const params = {
          id: record.id,
          status: 'cancelled',
          ...extraParams
        };
        
        return http.patch(apiUrl, params).then(() => {
          message.success('已撤销');
          refreshData();
          if (onSuccess) onSuccess();
        });
      }
    });
  }, [apiUrl, onSuccess, refreshData]);

  /**
   * 删除
   */
  const remove = useCallback((record, options = {}) => {
    const { withRestore = false } = options;
    
    Modal.confirm({
      title: '删除确认',
      content: withRestore
        ? '确定要删除吗？删除后将恢复原排班，此操作不可恢复！'
        : '确定要删除此记录吗？此操作不可恢复！',
      okText: '确定删除',
      okType: 'danger',
      onOk: () => {
        return http.delete(apiUrl, { params: { id: record.id } }).then(() => {
          message.success('已删除');
          refreshData();
          if (onSuccess) onSuccess();
        });
      }
    });
  }, [apiUrl, onSuccess, refreshData]);

  return {
    approve,
    reject,
    cancel,
    remove
  };
}

export default useApproval;
