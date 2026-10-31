/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 权限配置页签（2026-10-31 授权模型改造重做）：
 * - 页签对 持 config 权限码 / 手册所有者 / 制度管理员 可见（详情页控制），
 *   页签内各卡片再按身份收窄：
 *   · 手册所有者卡：显示所有者或「未指定」；仅制度管理员可指定/接管/
 *     移交（候选=owner-candidates，全部启用账号），所有者本人只读——
 *     受控移交必须经管理员，所有者不能自我移交；
 *   · 账号授权卡（AuthorizationCard）：仅所有者/制度管理员可读写
 *     （逐本账号授权，替代旧角色关联）；仅持 config 码的账号不渲染
 *     授权卡，显示说明文案；
 *   · 编辑密码卡：仅持 config 权限码渲染表单；所有者/制度管理员无
 *     config 码时显示说明「密码由持配置权限的账号维护」。
 * - 各操作成功提示只在实际成功响应之后；失败由 HTTP 拦截器提示一次，
 *   这里不重复弹错。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Select, Button, Input, Form, Modal, Tag, Alert, message } from 'antd';
import { hasPermission, http } from 'libs';
import { formatDateTime } from '../utils';
import store from './store';
import AuthorizationCard from './AuthorizationCard';

const {Option} = Select;

@observer
class ConfigTab extends React.Component {
  passwordFormRef = React.createRef();
  state = {savingPassword: false, ownerAccountId: undefined, settingOwner: false};

  componentDidMount() {
    // 所有者候选仅制度管理员可调（后端同口径），非管理员不请求
    if (store.manual && store.manual.is_admin) {
      store.fetchOwnerCandidates(store.id);
    }
  }

  handleSavePassword = () => {
    this.passwordFormRef.current.validateFields().then(values => {
      Modal.confirm({
        title: '重置编辑密码',
        content: '重置后所有进行中的编辑会话立即失效，需要新密码重新进入编辑。确定重置？',
        onOk: () => {
          this.setState({savingPassword: true});
          return httpPutPassword(values.password)
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

  /** 指定/接管/移交所有者（仅制度管理员）：确认窗明确说明语义 */
  handleSetOwner = () => {
    const accountId = this.state.ownerAccountId;
    if (!accountId) {
      message.warning('请先选择新的所有者账号');
      return;
    }
    const manual = store.manual || {};
    const candidate = (store.ownerCandidates || []).find(
      o => o.id === accountId);
    const newName = candidate ? candidate.name : '所选账号';
    const hasOwner = !!manual.owner_id;
    Modal.confirm({
      title: hasOwner ? '移交 / 接管手册所有者' : '指定手册所有者',
      content: (
        <div>
          <p>
            将把手册「{manual.name}」的所有者
            {hasOwner ? `（当前：${manual.owner_name || '未指定'}）` : ''}
            设为「{newName}」。
          </p>
          <p style={{color: '#888'}}>
            所有者负责本手册的账号授权与文件分工；所有者身份不自动获得
            编辑/发布权，也不自动可见发布版（仍按账号授权判定）。
            {hasOwner ? '原所有者如需继续访问，请确认其已被授予相应授权。' : ''}
          </p>
        </div>
      ),
      okText: '确认设置',
      onOk: () => {
        this.setState({settingOwner: true});
        return store.setManualOwner(store.id, accountId)
          .then(() => {
            message.success('手册所有者已更新');
            this.setState({ownerAccountId: undefined});
          })
          .catch(() => {})
          .finally(() => this.setState({settingOwner: false}));
      },
    });
  };

  renderOwnerCard(manual, isAdmin, isOwner) {
    return (
      <Card title="手册所有者" size="small" style={{marginBottom: 16}}>
        <p style={{marginTop: 0}}>
          {manual.owner_name
            ? <Tag color="purple">{manual.owner_name}</Tag>
            : <Tag color="orange">未指定</Tag>}
          <span style={{color: '#999', fontSize: 12}}>
            所有者负责本手册的账号授权与文件分工
          </span>
        </p>
        {isAdmin && (
          <div style={{display: 'flex', gap: 8, flexWrap: 'wrap',
            alignItems: 'center', marginTop: 8}}>
            {store.ownerCandidatesError ? (
              <Alert type="warning" showIcon style={{flex: 1, minWidth: 240}}
                message={`所有者候选加载失败：${store.ownerCandidatesError}`}
                action={<Button size="small" type="primary"
                  onClick={() => store.fetchOwnerCandidates(store.id)}>重试</Button>}/>
            ) : (
              <Select style={{minWidth: 220}} showSearch optionFilterProp="children"
                placeholder="选择新的所有者账号"
                value={this.state.ownerAccountId}
                onChange={v => this.setState({ownerAccountId: v})}>
                {(store.ownerCandidates || []).map(u => (
                  <Option key={u.id} value={u.id}>{u.name}</Option>
                ))}
              </Select>
            )}
            <Button type="primary" size="small" loading={this.state.settingOwner}
              onClick={this.handleSetOwner}>
              {manual.owner_id ? '移交 / 接管' : '指定所有者'}
            </Button>
          </div>
        )}
        {isOwner && !isAdmin && (
          <p style={{color: '#999', fontSize: 12, marginBottom: 0}}>
            你是本手册所有者；移交所有者须由制度管理员操作。
          </p>
        )}
      </Card>
    );
  }

  renderPasswordCard(manual, canConfig) {
    return (
      <Card title="编辑密码" size="small" style={{marginBottom: 16}}>
        <p>
          {manual.has_password
            ? `已设置（更新时间：${formatDateTime(manual.password_updated_at)}）`
            : <strong style={{color: '#fa8c16'}}>尚未设置，编制者将无法进入编辑</strong>}
        </p>
        {canConfig ? (
          <PasswordForm
            formRef={this.passwordFormRef}
            hasPassword={!!manual.has_password}
            saving={this.state.savingPassword}
            onSave={this.handleSavePassword}/>
        ) : (
          <p style={{color: '#999', fontSize: 12, marginBottom: 0}}>
            密码由持配置权限的账号维护（需要「配置手册权限与密码」权限码）。
          </p>
        )}
        <p style={{marginTop: 8, color: '#999', fontSize: 12}}>
          密码仅用于开启编辑会话；连续输错 5 次将锁定 15 分钟；重置不影响历史版本。
          密码只是附加验证：编辑权仍按 账号编制授权 + 文件负责人 判定。
        </p>
      </Card>
    );
  }

  render() {
    const manual = store.manual || {};
    const isAdmin = !!manual.is_admin;
    const isOwner = !!manual.is_owner;
    const canConfig = hasPermission('institution.manual.config');
    const canManageAuth = isOwner || isAdmin;
    return (
      <div style={{maxWidth: 760}}>
        {this.renderOwnerCard(manual, isAdmin, isOwner)}
        {canManageAuth ? (
          <AuthorizationCard/>
        ) : (
          <Card title="账号授权（查看 / 编制 / 发布）" size="small" style={{marginBottom: 16}}>
            <p style={{marginBottom: 0, color: '#999', fontSize: 12}}>
              手册级账号授权由手册所有者或制度管理员维护；你当前仅持配置权限码，
              不能查看或修改本手册的账号授权。
            </p>
          </Card>
        )}
        {this.renderPasswordCard(manual, canConfig)}
      </div>
    );
  }
}

/** 编辑密码表单（仅持 config 码渲染；PasswordCard 的行数门禁拆分） */
function PasswordForm({formRef, hasPassword, saving, onSave}) {
  return (
    <Form ref={formRef} layout="inline">
      <Form.Item name="password"
        rules={[{required: true, message: '请输入新密码'},
          {min: 4, message: '至少 4 位'}]}>
        <Input.Password placeholder="新编辑密码" style={{width: 220}}
          autoComplete="new-password"/>
      </Form.Item>
      <Button size="small" type="primary" danger={hasPassword}
        loading={saving} onClick={onSave}>
        {hasPassword ? '重置密码' : '设置密码'}
      </Button>
    </Form>
  );
}

/** 重置编辑密码（config 码接口；失败拦截器已提示） */
function httpPutPassword(password) {
  return http.put(`/api/institution/manuals/${store.id}/password/`, {password});
}

export default ConfigTab;
