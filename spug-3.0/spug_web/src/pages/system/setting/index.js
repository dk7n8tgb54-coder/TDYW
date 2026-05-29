/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Menu } from 'antd';
import { observer } from 'mobx-react';
import { autorun } from 'mobx';
import { AuthDiv, Breadcrumb } from 'components';

import OpenService from './OpenService';
import KeySetting from './KeySetting';
import SecuritySetting from './SecuritySetting';
import PushSetting from './PushSetting';
import About from './About';
import styles from './index.module.css';
import store from './store';


@observer
class Index extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      selectedKeys: ['security']
    }
  }

  componentDidMount() {
    this._disposer = autorun(() => {
      if (!store.isFetching && Object.keys(store.settings).length === 0) {
        store.fetchSettings()
      }
    })
  }

  componentWillUnmount() {
    if (this._disposer) {
      this._disposer()
    }
  }

  render() {
    const {selectedKeys} = this.state;
    // 触发 MobX 响应式更新
    void store.settings;
    return (
      <AuthDiv auth="system.setting.view">
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>系统管理</Breadcrumb.Item>
          <Breadcrumb.Item>系统设置</Breadcrumb.Item>
        </Breadcrumb>
        <div className={styles.container}>
          <div className={styles.left}>
            <Menu
              mode="inline"
              selectedKeys={selectedKeys}
              style={{border: 'none'}}
              onSelect={({selectedKeys}) => this.setState({selectedKeys})}
              items={[
                { key: 'security', label: '安全设置' },
                { key: 'key', label: '密钥设置' },
                { key: 'push', label: '推送服务设置' },
                { key: 'service', label: '开放服务设置' },
                { key: 'about', label: '关于' }
              ]}/>
          </div>
          <div className={styles.right}>
            {selectedKeys[0] === 'security' && <SecuritySetting/>}
            {selectedKeys[0] === 'push' && <PushSetting/>}
            {selectedKeys[0] === 'service' && <OpenService/>}
            {selectedKeys[0] === 'key' && <KeySetting/>}
            {selectedKeys[0] === 'about' && <About/>}
          </div>
        </div>
      </AuthDiv>
    )
  }
}

export default Index
