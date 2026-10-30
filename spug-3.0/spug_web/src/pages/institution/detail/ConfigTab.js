/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Select, Switch, Button, Input, Form, Modal, message } from 'antd';
import { http } from 'libs';
import { formatDateTime } from '../utils';
import store from './store';

const {Option} = Select;

@observer
class ConfigTab extends React.Component {
  rolesFormRef = React.createRef();
  passwordFormRef = React.createRef();
  state = {savingRoles: false, savingPassword: false};

  componentDidMount() {
    store.fetchRoles();
  }

  handleSaveRoles = () => {
    this.rolesFormRef.current.validateFields().then(values => {
      this.setState({savingRoles: true});
      const payload = {
        view_role_ids: values.view_role_ids || [],
        edit_role_ids: values.edit_role_ids || [],
        publish_role_ids: values.publish_role_ids || [],
      };
      http.put(`/api/institution/manuals/${store.id}/roles/`, payload)
        .then(() => {
          message.success('角色关联已更新');
          store.fetchDetail(store.id);
        })
        .finally(() => this.setState({savingRoles: false}));
    }).catch(() => {});
  };

  handleSavePassword = () => {
    this.passwordFormRef.current.validateFields().then(values => {
      Modal.confirm({
        title: '重置编辑密码',
        content: '重置后所有进行中的编辑会话立即失效，需要新密码重新进入编辑。确定重置？',
        onOk: () => {
          this.setState({savingPassword: true});
          return http.put(`/api/institution/manuals/${store.id}/password/`,
            {password: values.password})
            .then(() => {
              message.success('密码已更新，旧会话已全部失效');
              this.passwordFormRef.current.resetFields();
              store.fetchDetail(store.id);
            })
            .finally(() => this.setState({savingPassword: false}));
        },
      });
    }).catch(() => {});
  };

  handleToggleEditorVisible = (checked) => {
    const manual = store.manual;
    http.put(`/api/institution/manuals/${store.id}/`, {
      name: manual.name, code: manual.code, category_id: manual.category_id,
      owner_type: manual.owner_type, owner_name: manual.owner_name,
      status: manual.status, editor_can_view_published: checked,
    }).then(() => {
      message.success('已保存');
      store.fetchDetail(store.id);
    });
  };

  render() {
    const manual = store.manual || {};
    const roleOptions = store.roles.map(r => (
      <Option key={r.id} value={r.id}>{r.name}</Option>
    ));
    return (
      <div style={{maxWidth: 720}}>
        <Card title="角色关联（查看 / 编制 / 发布）" size="small" style={{marginBottom: 16}}>
          <Form ref={this.rolesFormRef} labelCol={{span: 5}} wrapperCol={{span: 18}}
            initialValues={{
              view_role_ids: (manual.view_roles || []).map(x => x.id),
              edit_role_ids: (manual.edit_roles || []).map(x => x.id),
              publish_role_ids: (manual.publish_roles || []).map(x => x.id),
            }}>
            <Form.Item name="view_role_ids" label="查看角色"
              extra="可查看手册与已发布版本">
              <Select mode="multiple" allowClear placeholder="选择角色">{roleOptions}</Select>
            </Form.Item>
            <Form.Item name="edit_role_ids" label="编制角色"
              extra="经验证该手册编辑密码后可编辑草稿">
              <Select mode="multiple" allowClear placeholder="选择角色">{roleOptions}</Select>
            </Form.Item>
            <Form.Item name="publish_role_ids" label="发布角色"
              extra="可发布版本与废止（需填写变更说明）">
              <Select mode="multiple" allowClear placeholder="选择角色">{roleOptions}</Select>
            </Form.Item>
            <Button type="primary" size="small" loading={this.state.savingRoles}
              onClick={this.handleSaveRoles}>保存角色关联</Button>
          </Form>
        </Card>
        <Card title="编辑密码" size="small" style={{marginBottom: 16}}>
          <p>
            {manual.has_password
              ? `已设置（更新时间：${formatDateTime(manual.password_updated_at)}）`
              : <strong style={{color: '#fa8c16'}}>尚未设置，编制者将无法进入编辑</strong>}
          </p>
          <Form ref={this.passwordFormRef} layout="inline">
            <Form.Item name="password"
              rules={[{required: true, message: '请输入新密码'},
                {min: 4, message: '至少 4 位'}]}>
              <Input.Password placeholder="新编辑密码" style={{width: 220}} autoComplete="new-password"/>
            </Form.Item>
            <Button size="small" type="primary" danger={!!manual.has_password}
              loading={this.state.savingPassword} onClick={this.handleSavePassword}>
              {manual.has_password ? '重置密码' : '设置密码'}
            </Button>
          </Form>
          <p style={{marginTop: 8, color: '#999', fontSize: 12}}>
            密码仅用于开启编辑会话；连续输错 5 次将锁定 15 分钟；重置不影响历史版本。
          </p>
        </Card>
        <Card title="发布版可见性" size="small">
          <p style={{marginBottom: 8}}>
            <Switch checked={manual.editor_can_view_published}
              onChange={this.handleToggleEditorVisible}/>
            <span style={{marginLeft: 8}}>编制角色可查看已发布版本</span>
          </p>
          <p style={{color: '#999', fontSize: 12}}>
            跨部门共同编制时，可逐本关闭，使外部编制者只能访问草稿而看不到最终发布版。
          </p>
        </Card>
      </div>
    );
  }
}

export default ConfigTab;
