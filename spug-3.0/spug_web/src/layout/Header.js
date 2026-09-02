/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { observer } from 'mobx-react';
import { Layout, Dropdown, Menu, Avatar, Badge, Popover, List, Tag, Button, Empty, Spin } from 'antd';
import { MenuFoldOutlined, MenuUnfoldOutlined, UserOutlined, LogoutOutlined, BellOutlined } from '@ant-design/icons';
import styles from './layout.module.less';
import http from '../libs/http';
import history from '../libs/history';
import avatar from './avatar.png';
import alertStore from './AlertStore';

const LEVEL_CONFIG = {
  error: { color: 'red', text: '严重' },
  warning: { color: 'orange', text: '警告' },
  info: { color: 'blue', text: '提示' },
};

export default observer(function (props) {
  const [bellOpen, setBellOpen] = useState(false);
  const isSupper = sessionStorage.getItem('is_supper') === 'true';

  function handleLogout() {
    history.push('/');
    http.get('/api/account/logout/')
  }

  const handleBellOpen = (visible) => {
    setBellOpen(visible);
    if (visible) {
      alertStore.fetchRecent();
    }
  };

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

  const bellContent = (
    <div style={{ width: 380, maxHeight: 400, overflow: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 500 }}>系统告警</span>
        {alertStore.unreadCount > 0 && (
          <Button type="link" size="small" onClick={() => alertStore.markAllRead()}>全部已读</Button>
        )}
      </div>
      <Spin spinning={alertStore.loading}>
        {alertStore.recentAlerts.length === 0 ? (
          <Empty description="暂无告警" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            size="small"
            dataSource={alertStore.recentAlerts}
            renderItem={item => {
              const cfg = LEVEL_CONFIG[item.level] || LEVEL_CONFIG.info;
              return (
                <List.Item style={{ padding: '8px 0' }}>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Tag color={cfg.color} style={{ marginRight: 0 }}>{cfg.text}</Tag>
                      <span style={{ flex: 1, fontWeight: item.status === 'unread' ? 500 : 400, fontSize: 13 }}>
                        {item.title}
                      </span>
                    </div>
                    <div style={{ color: '#999', fontSize: 12, marginTop: 4, marginLeft: 40 }}>
                      {item.created_at}
                    </div>
                  </div>
                </List.Item>
              );
            }}
          />
        )}
      </Spin>
      <div style={{ textAlign: 'center', marginTop: 8, borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>
        <Link to="/maintenance/alert" onClick={() => setBellOpen(false)}>查看全部告警</Link>
      </div>
    </div>
  );

  return (
    <Layout.Header className={styles.header}>
      <div className={styles.trigger} onClick={props.toggle}>
        {props.collapsed ? <MenuUnfoldOutlined/> : <MenuFoldOutlined/>}
      </div>
      <div className={styles.right}>
        {isSupper && (
          <Popover
            content={bellContent}
            trigger="click"
            placement="bottomRight"
            visible={bellOpen}
            onVisibleChange={handleBellOpen}
          >
            <div className={styles.bell}>
              <Badge count={alertStore.unreadCount} size="small" offset={[-2, 2]}>
                <BellOutlined style={{ fontSize: 18 }} />
              </Badge>
            </div>
          </Popover>
        )}
        <div className={styles.user}>
          <Dropdown overlay={UserMenu} style={{background: '#000'}}>
            <span className={styles.action}>
              <Avatar size="small" src={avatar} style={{marginRight: 8}}/>
              <span className={styles.nickname} title={sessionStorage.getItem('nickname') || ''}>
                {sessionStorage.getItem('nickname')}
              </span>
            </span>
          </Dropdown>
        </div>
      </div>
    </Layout.Header>
  )
})
