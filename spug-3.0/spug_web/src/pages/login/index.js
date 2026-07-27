/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Form, Input, Button, Modal, message } from 'antd';
import { UserOutlined, LockOutlined, CopyrightOutlined, MailOutlined } from '@ant-design/icons';
import styles from './login.module.css';
import history from 'libs/history';
import { http, updatePermissions, hasPermission } from 'libs';
import routes from '../../routes';
import logo from 'layout/logo-spug-txt.png';

// 登录后默认跳转：优先工作台；没权限则递归找第一个有权限的菜单；都没有则回个人中心
function getDefaultRoute() {
  if (hasPermission('dashboard.dashboard.view')) return '/home';
  function findFirst(items) {
    for (let item of items) {
      if (!item.title) continue;
      if (item.path && (!item.auth || hasPermission(item.auth))) return item.path;
      if (item.child) {
        const found = findFirst(item.child);
        if (found) return found;
      }
    }
    return null;
  }
  return findFirst(routes) || '/welcome/info';
}

export default function () {
  const [form] = Form.useForm();
  const [counter, setCounter] = useState(0);
  const [loading, setLoading] = useState(false);
  const [codeVisible, setCodeVisible] = useState(false);
  const [codeLoading, setCodeLoading] = useState(false);
  const loginType = sessionStorage.getItem('login_type') || 'default';

  useEffect(() => {
  }, [])

  useEffect(() => {
    setTimeout(() => {
      if (counter > 0) {
        setCounter(counter - 1)
      }
    }, 1000)
  }, [counter])

  function handleSubmit() {
    const formData = form.getFieldsValue();
    if (codeVisible && !formData.captcha) return message.error('请输入验证码');
    setLoading(true);
    formData['type'] = loginType;
    http.post('/api/account/login/', formData)
      .then(data => {
        if (data['required_mfa']) {
          setCodeVisible(true);
          setCounter(30);
          setLoading(false)
        } else if (!data['has_real_ip']) {
          Modal.warning({
            title: '安全警告',
            className: styles.tips,
            content: <div>
              未能获取到访问者的真实IP，无法提供基于请求来源IP的合法性验证，详细信息请参考
              <a target="_blank"
                 href="https://ops.spug.cc/docs/practice/"
                 rel="noopener noreferrer">官方文档</a>。
            </div>,
            onOk: () => doLogin(data)
          })
        } else {
          doLogin(data)
        }
      }, () => setLoading(false))
  }

  function doLogin(data) {
    sessionStorage.setItem('id', data['id']);
    sessionStorage.setItem('token', data['access_token']);
    sessionStorage.setItem('nickname', data['nickname']);
    sessionStorage.setItem('is_supper', data['is_supper']);
    sessionStorage.setItem('tenant_id', data['tenant_id'] || '');
    sessionStorage.setItem('permissions', JSON.stringify(data['permissions']));
    sessionStorage.setItem('login_type', loginType);
    updatePermissions();
    if (history.location.state && history.location.state['from']) {
      history.push(history.location.state['from'])
    } else {
      history.push(getDefaultRoute())
    }
  }

  function handleCaptcha() {
    setCodeLoading(true);
    const formData = form.getFieldsValue(['username', 'password']);
    formData['type'] = loginType;
    http.post('/api/account/login/', formData)
      .then(() => setCounter(30))
      .finally(() => setCodeLoading(false))
  }

  return (
    <div className={styles.container}>
      <div className={styles.titleContainer}>
        <div className={styles.logo}><img src={logo} alt="logo"/></div>
        <div className={styles.title}>空管综合运维管理平台</div>
      </div>
      <div className={styles.formContainer}>
        <Form form={form}>
          <Form.Item name="username" className={styles.formItem}>
            <Input
              size="large"
              autoComplete="off"
              placeholder="请输入账户"
              prefix={<UserOutlined className={styles.icon}/>}/>
          </Form.Item>
          <Form.Item name="password" className={styles.formItem}>
            <Input
              size="large"
              type="password"
              autoComplete="off"
              placeholder="请输入密码"
              onPressEnter={handleSubmit}
              prefix={<LockOutlined className={styles.icon}/>}/>
          </Form.Item>
          <Form.Item hidden={!codeVisible} name="captcha" className={styles.formItem}>
            <div style={{display: 'flex'}}>
              <Form.Item noStyle name="captcha">
                <Input
                  size="large"
                  autoComplete="off"
                  placeholder="请输入验证码"
                  prefix={<MailOutlined className={styles.icon}/>}/>
              </Form.Item>
              {counter > 0 ? (
                <Button disabled size="large" style={{marginLeft: 8}}>{counter} 秒后重新获取</Button>
              ) : (
                <Button size="large" loading={codeLoading} style={{marginLeft: 8}}
                        onClick={handleCaptcha}>获取验证码</Button>
              )}
            </div>
          </Form.Item>
        </Form>

        <Button
          block
          size="large"
          type="primary"
          className={styles.button}
          loading={loading}
          onClick={handleSubmit}>登录</Button>
      </div>

      <div className={styles.footerZone}>
        <div style={{color: 'rgba(0, 0, 0, .45)'}}>© 2026 YTTD</div>
      </div>
    </div>
  )
}
