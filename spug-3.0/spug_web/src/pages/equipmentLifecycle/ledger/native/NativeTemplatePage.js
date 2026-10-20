/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生维护台账模板管理页（2026-10-18 接入，与 Excel 台账模板并行）。
 *
 * 支持范围（第一阶段）：新建模板 → iframe 在线编辑（版式/字段绑定/
 * 批量绑定/纸张设置）→ 草稿保存 → 发布不可变版本；台账创建/填写/
 * 完成填写/更正/作废与单条 PDF 导出在维护台账列表内进行。
 * 暂不支持：周期批量生成、批量 PDF、Excel 导入导出（页面明确标注）。
 * 权限：复用 equipment_lifecycle.ledger_template.*（后端独立校验）。
 */
import React, {useEffect, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Tooltip} from 'antd';
import {DeleteOutlined, EditOutlined, PlusOutlined, StopOutlined} from '@ant-design/icons';
import {AuthButton, AuthDiv} from 'components';

import NativeTemplateEditorHost from './NativeTemplateEditorHost';
import {PERM_T} from '../constants';
import store from './nativeTemplateStore';
import useWorkTabUnsaved from 'layout/useWorkTabUnsaved';
const LEDGER_TYPE_TEXT = {week_month: '周月维护', seasonal: '季维护'};
const STATUS_TEXT = {draft: '草稿', published: '已发布', used: '使用中', deleted: '已停用'};
const STATUS_COLOR = {draft: 'default', published: 'blue', used: 'green', deleted: 'default'};

function CreateModal({visible, onCancel}) {
  const [form] = Form.useForm();
  React.useEffect(() => {
    if (visible) form.resetFields();
  }, [visible, form]);

  const handleOk = () => {
    form.validateFields().then(values => {
      store.createTemplate(values)
        .then(() => {
          store.setEditing(true);
          onCancel();
        })
        .catch(() => {});
    }).catch(() => {});
  };

  return (
    <Modal title="新建原生台账模板" visible={visible} confirmLoading={store.creating}
           okText="创建并编辑" cancelText="取消" onOk={handleOk} onCancel={onCancel}
           destroyOnClose>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="模板名称" rules={[
          {required: true, message: '请输入模板名称'},
          {max: 100, message: '模板名称不超过 100 字'}]}>
          <Input data-testid="native-template-name" placeholder="例如：通信信道季度维护台账"/>
        </Form.Item>
        <Form.Item name="ledger_type" label="台账类型" rules={[
          {required: true, message: '请选择台账类型'}]}>
          <Select data-testid="native-template-type" placeholder="创建后不可修改">
            <Select.Option value="week_month">周月维护</Select.Option>
            <Select.Option value="seasonal">季维护</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item name="description" label="说明" rules={[
          {max: 500, message: '说明不超过 500 字'}]}>
          <Input.TextArea rows={2} placeholder="选填"/>
        </Form.Item>
        <Alert type="info" showIcon
               message="创建后进入在线编辑器：绘制底表 → 绑定字段 → 设置纸张 → 保存草稿 → 发布版本（发布后版本不可变）。"/>
      </Form>
    </Modal>
  );
}

// observer：直接读取 store.list/loading，列表加载完成必须触发本组件重渲染
const TemplateTable = observer(function TemplateTable({onEdit}) {
  const [deleteRecord, setDeleteRecord] = useState(null);
  const columns = [
    {title: '模板名称', dataIndex: 'name', ellipsis: true},
    {
      title: '台账类型', dataIndex: 'ledger_type', width: 100,
      render: v => LEDGER_TYPE_TEXT[v] || v,
    },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (v, record) => (
        <Tag color={STATUS_COLOR[v] || 'default'}>{STATUS_TEXT[v] || v}</Tag>
      ),
    },
    {
      title: '版本', key: 'versions', width: 90,
      render: (v, record) => record.latest_version_no ? `v${record.latest_version_no}` : '—',
    },
    {title: '引用台账', dataIndex: 'ledgers_count', width: 90},
    {
      title: '草稿更新时间', dataIndex: 'draft_updated_at', width: 170,
      render: v => v ? String(v).slice(0, 19).replace('T', ' ') : '—',
    },
    {title: '说明', dataIndex: 'description', ellipsis: true, width: 200, render: v => v || '—'},
    {
      title: '操作', key: 'actions', width: 170, align: 'center', fixed: 'right',
      render: (v, record) => record.is_active ? (
        <Space size={4}>
          <AuthButton auth={PERM_T.TPL_EDIT} data-testid="native-template-edit"
                      icon={<EditOutlined/>} onClick={() => onEdit(record)}>编辑</AuthButton>
          {record.ledgers_count ? (
            <Tooltip title="模板已被台账引用，不能删除；如需停止使用请停用">
              <AuthButton auth={PERM_T.TPL_DEL} icon={<StopOutlined/>}
                          onClick={() => store.deactivate(record.id).then(() => store.fetchList()).catch(() => {})}>
                停用
              </AuthButton>
            </Tooltip>
          ) : (
            <React.Fragment>
              <AuthButton auth={PERM_T.TPL_DEL} icon={<StopOutlined/>}
                          onClick={() => store.deactivate(record.id).then(() => store.fetchList()).catch(() => {})}>
                停用
              </AuthButton>
              <AuthButton auth={PERM_T.TPL_DEL} danger icon={<DeleteOutlined/>}
                          data-testid="native-template-delete"
                          onClick={() => setDeleteRecord(record)}/>
            </React.Fragment>
          )}
        </Space>
      ) : (
        <Tag>已停用</Tag>
      ),
    },
  ];
  return (
    <React.Fragment>
      <Table
        rowKey="id"
        loading={store.loading}
        dataSource={store.list}
        columns={columns}
        scroll={{x: 1000}}
        pagination={false}
      />
      <Modal
        title={`删除模板（${deleteRecord ? deleteRecord.name : ''}）`}
        visible={!!deleteRecord}
        okText="确认删除" okButtonProps={{danger: true}} cancelText="取消"
        onCancel={() => setDeleteRecord(null)}
        onOk={() => {
          store.destroy(deleteRecord.id)
            .then(() => store.fetchList())
            .catch(() => {})
            .finally(() => setDeleteRecord(null));
        }}>
        <p style={{color: '#f5222d'}}>
          删除将同时删除全部未引用版本草稿，且不可恢复；被台账引用（含已作废）的模板由后端拒绝删除。
        </p>
      </Modal>
    </React.Fragment>
  );
});

function NativeTemplatePage({location}) {
  const [createVisible, setCreateVisible] = useState(false);
  const editing = store.editing && !!store.detail;
  // 在线编辑器有未保存修改（editorDirty）时，当前页签不参与自动淘汰：
  // iframe 编辑内容不落盘，页签被自动关闭会丢失编辑中的版式修改
  useWorkTabUnsaved(!!store.editorDirty);

  useEffect(() => {
    store.fetchList().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleEdit = record => {
    store.fetchDetail(record.id)
      .then(() => store.setEditing(true))
      .catch(() => {});
  };

  const handleBack = () => {
    store.setEditing(false);
    store.fetchList().catch(() => {});
  };

  return (
    <AuthDiv auth={PERM_T.TPL_VIEW}>
      {editing ? (
        <NativeTemplateEditorHost store={store} onBack={handleBack}/>
      ) : (
        <React.Fragment>
          <Alert
            style={{marginBottom: 12}}
            type="info" showIcon
            message="原生台账模板与 Excel/WPS 模板并行，共用正式台账的编号、权限、状态与审计规则。"
            description="当前支持：在线编辑版式、字段绑定、纸张设置、草稿保存、发布不可变版本，以及按版本创建台账、填写、完成/更正/作废与单条 PDF 导出。暂不支持：周期批量生成与重建、批量 PDF 导出、Excel 导入导出。"
          />
          <div style={{marginBottom: 12}}>
            <AuthButton
              auth={PERM_T.TPL_ADD}
              type="primary"
              icon={<PlusOutlined/>}
              data-testid="native-template-create"
              onClick={() => setCreateVisible(true)}>
              新建原生模板
            </AuthButton>
            <Button style={{marginLeft: 8}} onClick={() => store.fetchList().catch(() => {})}>
              刷新
            </Button>
          </div>
          <Card bordered={false}>
            <TemplateTable onEdit={handleEdit}/>
          </Card>
        </React.Fragment>
      )}
      <CreateModal visible={createVisible} onCancel={() => setCreateVisible(false)}/>
    </AuthDiv>
  );
}

export default observer(NativeTemplatePage);
