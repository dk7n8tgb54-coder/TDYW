/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Form, Input, Select, Modal, Switch, message } from 'antd';
import { hasPermission, http } from 'libs';
import store from './store';

const {Option} = Select;

/**
 * 构造提交载荷：antd 清空 Select/DatePicker 后值为 undefined，
 * JSON.stringify 会丢键，后端无法区分"未提交"与"清空"，
 * 因此角色列表显式转空数组、文本字段显式转空串。
 */
export function buildManualPayload(values, defaults = {}) {
  return {
    name: (values.name || '').trim(),
    code: (values.code || '').trim(),
    category_id: values.category_id || null,
    owner_type: values.owner_type || defaults.owner_type || 'department',
    owner_name: (values.owner_name || '').trim(),
    status: values.status || defaults.status || 'active',
    editor_can_view_published: values.editor_can_view_published !== undefined
      ? !!values.editor_can_view_published
      : (defaults.editor_can_view_published !== undefined
        ? !!defaults.editor_can_view_published : true),
    view_role_ids: values.view_role_ids || [],
    edit_role_ids: values.edit_role_ids || [],
    publish_role_ids: values.publish_role_ids || [],
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
    // 角色可选项端点以 institution.manual.config 门控：仅配置者请求，
    // 避免 add/edit 权限用户打开弹窗即撞权限拒绝错误
    if (hasPermission('institution.manual.config')) {
      this.fetchRoles();
    }
  }

  fetchRoles() {
    http.get('/api/institution/roles/')
      .then(data => this.setState({roles: data || []}))
      .catch(() => {});
  }

  state = {roles: [], submitting: false};

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
    const canConfig = hasPermission('institution.manual.config');
    const roleOptions = this.state.roles.map(r => (
      <Option key={r.id} value={r.id}>{r.name}</Option>
    ));
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
            owner_type: info.owner_type, owner_name: info.owner_name,
            status: info.status,
            editor_can_view_published: info.editor_can_view_published,
            view_role_ids: (info.view_roles || []).map(x => x.id),
            edit_role_ids: (info.edit_roles || []).map(x => x.id),
            publish_role_ids: (info.publish_roles || []).map(x => x.id),
          } : {
            owner_type: 'department', status: 'active',
            editor_can_view_published: true,
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
          <Form.Item name="owner_type" label="业务归属" required>
            <Select>
              <Option value="department">部门</Option>
              <Option value="section">科室</Option>
            </Select>
          </Form.Item>
          <Form.Item name="owner_name" label="归属单位">
            <Input placeholder="部门或科室名称（业务数据，页面维护）" maxLength={255}/>
          </Form.Item>
          {canConfig && (
            <React.Fragment>
              <Form.Item name="view_role_ids" label="查看角色"
                extra="持有任一角色的账号可查看该手册已发布版本">
                <Select mode="multiple" allowClear placeholder="选择平台级/本租户角色">
                  {roleOptions}
                </Select>
              </Form.Item>
              <Form.Item name="edit_role_ids" label="编制角色"
                extra="持有任一角色的账号经验证编辑密码后可编辑草稿">
                <Select mode="multiple" allowClear placeholder="选择角色">
                  {roleOptions}
                </Select>
              </Form.Item>
              <Form.Item name="publish_role_ids" label="发布角色"
                extra="持有任一角色的账号可发布版本（需填写变更说明）">
                <Select mode="multiple" allowClear placeholder="选择角色">
                  {roleOptions}
                </Select>
              </Form.Item>
            </React.Fragment>
          )}
          <Form.Item name="status" label="状态">
            <Select>
              <Option value="active">启用</Option>
              <Option value="archived">归档</Option>
            </Select>
          </Form.Item>
          <Form.Item name="editor_can_view_published" label="编制者可见发布版"
            valuePropName="checked"
            extra="关闭后，仅持有查看角色的账号可见已发布版本（跨部门参与时逐本配置）">
            <Switch/>
          </Form.Item>
        </Form>
      </Modal>
    );
  }
}

export default ManualForm;
