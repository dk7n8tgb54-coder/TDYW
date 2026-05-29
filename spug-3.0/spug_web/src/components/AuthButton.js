/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Button } from 'antd';
import { hasPermission, Permission } from 'libs';


export default function AuthButton(props) {
  const {isSuper} = Permission;
  const hasAuth = !props.auth || isSuper || hasPermission(props.auth);

  // 过滤掉 auth 属性，避免传递给 Button 组件
  const { auth, children, ...buttonProps } = props;
  return hasAuth ? <Button {...buttonProps}>{children}</Button> : null
}
