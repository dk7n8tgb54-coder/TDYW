/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 权限配置页签（2026-10-31 授权模型改造重做；同日二轮权限模型改造）：
 * - 页签对 持 config 权限码 / 手册所有者 / 平台超级管理员 可见（详情页
 *   控制），页签内各卡片再按身份收窄：
 *   · 手册所有者卡：显示所有者或「未指定」；所有者可移交手册给启用账号
 *     （候选=owner-candidates，全部启用账号；确认窗明确提示原所有者将
 *     失去所有者权限），平台超级管理员可指定/接管——原所有者移交后失权；
 *   · 账号授权卡（AuthorizationCard）：仅所有者/平台超级管理员可读写
 *     （逐本账号授权，替代旧角色关联）；仅持 config 码的账号不渲染
 *     授权卡，显示说明文案；
 *   · 编辑密码卡：仅 所有者/平台超级管理员 渲染表单（config 码不再
 *     足够）；其余账号显示说明「编辑密码仅手册所有者或平台超级管理员
 *     可设置/重置」。
 * - 各操作成功提示只在实际成功响应之后；失败由 HTTP 拦截器提示一次，
 *   这里不重复弹错。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Select, Button, Input, Form, Modal, Tag, Alert, message } from 'antd';
import { http } from 'libs';
import { formatDateTime } from '../utils';
import store from './store';
import AuthorizationCard from './AuthorizationCard';

const {Option} = Select;

@observer
class ConfigTab extends React.Component {
  passwordFormRef = React.createRef();
  state = {savingPassword: false, ownerAccountId: undefined, settingOwner: false};

  componentDidMount() {
    // 所有者候选：所有者移交与超管接管都需要（后端同口径放行），非
    // 所有者且非管理员不请求
    if (store.manual && (store.manual.is_owner || store.manual.is_admin)) {
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

  /**
   * 所有者移交（所有者操作）/ 指定/接管（平台超管操作）：确认窗按操作
   * 主体区分语义——移交明确提示原所有者将失去所有者权限
   */
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
    // 所有者本人操作=移交（失去自己的所有者权限）；超管（非所有者）
    // 操作=指定/接管。两者兼有时按所有者语义呈现（移交即失权方为本人）
    const isOwnerActing = !!manual.is_owner;
    const title = isOwnerActing ? '移交手册所有者'
      : (hasOwner ? '接管 / 移交手册所有者' : '指定手册所有者');
    Modal.confirm({
      title,
      content: (
        <div>
          <p>
            {isOwnerActing
              ? `将把手册「${manual.name}」的所有者移交给「${newName}」。`
              : `将把手册「${manual.name}」的所有者${hasOwner ? `（当前：${manual.owner_name || '未指定'}）` : ''}设为「${newName}」。`}
          </p>
          <p style={{color: '#888'}}>
            {isOwnerActing
              ? '移交后你将失去本手册所有者权限（账号授权与文件分工管理、' +
                '密码设置/重置、编辑任意文件、提交编制与发布入口），且不' +
                '自动保留：是否可继续访问仍按你的账号授权判定。'
              : '所有者自动拥有本手册全部权限（账号授权与文件分工管理、' +
                '密码设置/重置、编辑任意文件、提交编制与发布）；' +
                (hasOwner
                  ? `原所有者「${manual.owner_name || '未指定'}」将失去所有者权限，`
                  : '') +
                '是否可继续访问仍按其账号授权判定。'}
          </p>
        </div>
      ),
      okText: isOwnerActing ? '确认移交' : '确认设置',
      onOk: () => {
        this.setState({settingOwner: true});
        return store.setManualOwner(store.id, accountId)
          .then(() => {
            message.success(isOwnerActing ? '手册所有者已移交' : '手册所有者已更新');
            this.setState({ownerAccountId: undefined});
          })
          .catch(() => {})
          .finally(() => this.setState({settingOwner: false}));
      },
    });
  };

  renderOwnerCard(manual, isAdmin, isOwner) {
    // 所有者可移交、超管可指定/接管（候选同源 owner-candidates）
    const canTransfer = isAdmin || isOwner;
    const isOwnerActing = !!isOwner;
    return (
      <Card title="手册所有者" size="small" style={{marginBottom: 16}}>
        <p style={{marginTop: 0}}>
          {manual.owner_name
            ? <Tag color="purple">{manual.owner_name}</Tag>
            : <Tag color="orange">未指定</Tag>}
          <span style={{color: '#999', fontSize: 12}}>
            所有者自动拥有本手册全部权限（账号授权、密码、编辑、发布）
          </span>
        </p>
        {canTransfer && (
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
              {isOwnerActing ? '移交所有者'
                : (manual.owner_id ? '移交 / 接管' : '指定所有者')}
            </Button>
          </div>
        )}
        {!canTransfer && (
          <p style={{color: '#999', fontSize: 12, marginBottom: 0}}>
            所有者移交由手册所有者本人或平台超级管理员操作。
          </p>
        )}
      </Card>
    );
  }

  renderPasswordCard(manual, canSetPassword) {
    return (
      <Card title="编辑密码" size="small" style={{marginBottom: 16}}>
        <p>
          {manual.has_password
            ? `已设置（更新时间：${formatDateTime(manual.password_updated_at)}）`
            : <strong style={{color: '#fa8c16'}}>尚未设置，编制者将无法进入编辑</strong>}
        </p>
        {canSetPassword ? (
          <PasswordForm
            formRef={this.passwordFormRef}
            hasPassword={!!manual.has_password}
            saving={this.state.savingPassword}
            onSave={this.handleSavePassword}/>
        ) : (
          <p style={{color: '#999', fontSize: 12, marginBottom: 0}}>
            编辑密码仅手册所有者或平台超级管理员可设置/重置。
          </p>
        )}
        <p style={{marginTop: 8, color: '#999', fontSize: 12}}>
          密码仅用于开启编辑会话；连续输错 5 次将锁定 15 分钟；重置不影响历史版本。
          密码只是附加验证：编辑权仍按 账号编制授权 + 文件负责人 判定，
          手册所有者可编辑任意文件。
        </p>
      </Card>
    );
  }

  render() {
    const manual = store.manual || {};
    const isAdmin = !!manual.is_admin;
    const isOwner = !!manual.is_owner;
    const canManageAuth = isOwner || isAdmin;
    return (
      <div style={{maxWidth: 760}}>
        {this.renderOwnerCard(manual, isAdmin, isOwner)}
        {canManageAuth ? (
          <AuthorizationCard/>
        ) : (
          <Card title="账号授权（查看 / 编制 / 发布）" size="small" style={{marginBottom: 16}}>
            <p style={{marginBottom: 0, color: '#999', fontSize: 12}}>
              手册级账号授权由手册所有者或平台超级管理员维护；你当前仅持配置
              权限码，不能查看或修改本手册的账号授权。
            </p>
          </Card>
        )}
        {this.renderPasswordCard(manual, canManageAuth)}
      </div>
    );
  }
}

/** 编辑密码表单（仅所有者/平台超管渲染；PasswordCard 的行数门禁拆分） */
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

/** 重置编辑密码（仅所有者/平台超管可调；失败拦截器已提示） */
function httpPutPassword(password) {
  return http.put(`/api/institution/manuals/${store.id}/password/`, {password});
}

export default ConfigTab;
