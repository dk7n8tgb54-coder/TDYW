/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Breadcrumb, AuthDiv } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';

export default observer(function () {
  return (
    <AuthDiv auth="system.tenant.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统管理</Breadcrumb.Item>
        <Breadcrumb.Item>租户管理</Breadcrumb.Item>
      </Breadcrumb>
      <ComTable/>
      {store.formVisible && <ComForm/>}
    </AuthDiv>
  )
})
