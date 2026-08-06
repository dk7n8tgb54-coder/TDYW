/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import {Modal, Checkbox, Row, Col, message, Alert} from 'antd';
import http from 'libs/http';
import store from './store';
import codes from './codes';
import styles from './index.module.css';
import lds from 'lodash';

@observer
class PagePerm extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      loading: false,
    }
  }

  handleSubmit = () => {
    this.setState({loading: true});
    http.patch('/api/account/role/', {id: store.record.id, page_perms: store.permissions, is_global_admin: store.record.is_global_admin})
      .then(res => {
        message.success('操作成功');
        store.pagePermVisible = false;
        store.fetchRecords()
      }, err => {
        this.setState({loading: false})
      })
  };

  handleAllCheck = (e, mod, page) => {
    const checked = e.target.checked;
    if (checked) {
      const key = `${mod}.${page}`;
      const allPerms = lds.clone(store.allPerms[key]);
      store.permissions[mod][page] = allPerms
    } else {
      store.permissions[mod][page] = []
    }
  };

  handlePermCheck = (mod, page, perm) => {
    const perms = store.permissions[mod][page];
    if (perms.includes(perm)) {
      perms.splice(perms.indexOf(perm), 1);
    } else {
      perms.push(perm);
    }
  };

  PermBox = observer(({mod, page, perm, children}) => (
    <Checkbox
      value={perm}
      onChange={() => this.handlePermCheck(mod, page, perm)}
      checked={store.permissions[mod][page].includes(perm)}>
      {children}
    </Checkbox>
  ));

  isAllChecked = (mod, page) => {
    const key = `${mod}.${page}`;
    const allPerms = store.allPerms[key] || [];
    const currentPerms = store.permissions[mod]?.[page] || [];
    if (currentPerms.length === 0) return false;
    return allPerms.every(perm => currentPerms.includes(perm));
  };

  render() {
    const PermBox = this.PermBox;
    return (
      <Modal
        visible
        width={1000}
        maskClosable={false}
        title={store.record.name ? `功能权限设置 - ${store.record.name}` : '功能权限设置'}
        className={styles.container}
        onCancel={() => store.pagePermVisible = false}
        confirmLoading={this.state.loading}
        onOk={this.handleSubmit}>
        <Alert
          closable
          showIcon
          type="info"
          style={{marginBottom: 12}}
          message="权限更改成功后会强制属于该角色的账户重新登录。"/>
        <table border="1" bordercolor="#dfdfdf" className={styles.table}>
          <thead>
          <tr>
            <th>模块</th>
            <th>页面</th>
            <th>功能</th>
          </tr>
          </thead>
          <tbody>
          {codes.map(mod => (
            mod.pages.map((page, index) => (
              <tr key={page.key}>
                {index === 0 && <td rowSpan={mod.pages.length}>{mod.label}</td>}
                <td>
                  <Checkbox
                    onChange={e => this.handleAllCheck(e, mod.key, page.key)}
                    checked={this.isAllChecked(mod.key, page.key)}>
                    {page.label}
                  </Checkbox>
                </td>
                <td>
                  <Row>
                    {page.perms.map(perm => (
                      <Col key={perm.key} span={8}>
                        <PermBox mod={mod.key} page={page.key} perm={perm.key}>{perm.label}</PermBox>
                      </Col>
                    ))}
                  </Row>
                </td>
              </tr>
            ))
          ))}

          </tbody>
        </table>
      </Modal>
    )
  }
}

export default PagePerm
