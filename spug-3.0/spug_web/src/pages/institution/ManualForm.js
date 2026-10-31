/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Form, Input, Select, Modal, message } from 'antd';
import { http } from 'libs';
import store from './store';

const {Option} = Select;

/**
 * 构造提交载荷：antd 清空 Select 后值为 undefined，JSON.stringify 会丢键，
 * 后端无法区分"未提交"与"清空"，因此文本字段显式转空串。
 * 手册级查看/编制/发布授权（2026-10-31 授权模型）改由详情页「权限配置」
 * 页签的逐本账号授权维护，不再随手册表单提交角色字段。
 */
export function buildManualPayload(values, defaults = {}) {
  return {
    name: (values.name || '').trim(),
    code: (values.code || '').trim(),
    category_id: values.category_id || null,
    org_type: values.org_type || defaults.org_type || 'department',
    org_name: (values.org_name || '').trim(),
    status: values.status || defaults.status || 'active',
  };
}

@observer
class ManualForm extends React.Component {
  constructor(props) {
    super(props);
    this.formRef = React.createRef();
  }

  componentDidMount() {
    store.fetchCategories();
  }

  state = {submitting: false};

  /**
   * 兼容旧调用：组件内统一走模块级 buildManualPayload
   */
  buildPayload(values) {
    return buildManualPayload(values, store.record);
  }

  handleSubmit = () => {
    this.formRef.current.validateFields()
      .then(values => {
        this.setState({submitting: true});
        const info = store.record;
        const payload = this.buildPayload(values);
        const request = info.id
          ? http.put(`/api/institution/manuals/${info.id}/`, payload)
          : http.post('/api/institution/manuals/create/', payload);
        request.then(() => {
          message.success(info.id ? '保存成功' : '创建成功');
          store.formVisible = false;
          store.fetchRecords();
        }).finally(() => this.setState({submitting: false}));
      })
      .catch(() => {});
  };

  render() {
    const info = store.record;
    return (
      <Modal
        visible
        width={640}
        title={info.id ? '编辑手册' : '新建手册'}
        confirmLoading={this.state.submitting}
        onCancel={() => store.formVisible = false}
        onOk={this.handleSubmit}>
        <Form ref={this.formRef} labelCol={{span: 6}} wrapperCol={{span: 16}}
          initialValues={info.id ? {
            name: info.name, code: info.code,
            category_id: info.category_id || undefined,
            org_type: info.org_type, org_name: info.org_name,
            status: info.status,
          } : {
            org_type: 'department', status: 'active',
          }}>
          <Form.Item name="name" label="手册名称"
            rules={[{required: true, message: '请输入手册名称'}]}>
            <Input placeholder="例如：部门管理手册" maxLength={255}/>
          </Form.Item>
          <Form.Item name="code" label="手册编号">
            <Input placeholder="例如：GL-2026-001" maxLength={100}/>
          </Form.Item>
          <Form.Item name="category_id" label="手册类别">
            <Select allowClear placeholder="选择类别">
              {store.categories.filter(c => c.is_active).map(c => (
                <Option key={c.id} value={c.id}>{c.name}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="org_type" label="业务归属" required>
            <Select>
              <Option value="department">部门</Option>
              <Option value="section">科室</Option>
            </Select>
          </Form.Item>
          <Form.Item name="org_name" label="归属单位">
            <Input placeholder="部门或科室名称（业务数据，页面维护）" maxLength={255}/>
          </Form.Item>
          {/* 手册级账号授权（查看/编制/发布）在详情页「权限配置」页签
              逐本维护（2026-10-31 授权模型改造），不再随手册表单提交 */}
          <Form.Item name="status" label="状态">
            <Select>
              <Option value="active">启用</Option>
              <Option value="archived">归档</Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    );
  }
}

export default ManualForm;
