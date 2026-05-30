/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Link } from 'react-router-dom';
import { Layout, Dropdown, Menu, Avatar } from 'antd';
import { MenuFoldOutlined, MenuUnfoldOutlined, UserOutlined, LogoutOutlined } from '@ant-design/icons';
import styles from './layout.module.less';
import http from '../libs/http';
import history from '../libs/history';
import avatar from './avatar.png';

export default function (props) {

  function handleLogout() {
    history.push('/');
    http.get('/api/account/logout/')
  }

  const UserMenu = (
    <Menu
      items={[
        {
          key: 'profile',
          label: <Link to="/welcome/info"><UserOutlined style={{marginRight: 10}}/>个人中心</Link>
        },
        { type: 'divider' },
        {
          key: 'logout',
          label: <span onClick={handleLogout}><LogoutOutlined style={{marginRight: 10}}/>退出登录</span>
        }
      ]}
    />
  );

  return (
    <Layout.Header className={styles.header}>
      <div className={styles.trigger} onClick={props.toggle}>
        {props.collapsed ? <MenuUnfoldOutlined/> : <MenuFoldOutlined/>}
      </div>
      <div className={styles.right}>
        <div className={styles.user}>
          <Dropdown overlay={UserMenu} style={{background: '#000'}}>
            <span className={styles.action}>
              <Avatar size="small" src={avatar} style={{marginRight: 8}}/>
              {sessionStorage.getItem('nickname')}
            </span>
          </Dropdown>
        </div>
      </div>
    </Layout.Header>
  )
}