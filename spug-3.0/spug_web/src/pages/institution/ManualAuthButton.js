/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Button } from 'antd';
import { AuthButton } from 'components';

/**
 * 手册对象级门控按钮（2026-10-31 二轮权限模型改造）。
 *
 * 页面权限码 或 手册所有者 任一通过：所有者对本人手册的动作不再要求
 * 角色权限（规则 2：所有者权限按对象范围生效，不应要求所有者再额外
 * 获得角色权限或逐本授权；后端 manual_auth 装饰器同口径，后端仍独立
 * 校验）。平台超管经 hasPermission 的 isSuper 短路照常通过 AuthButton
 * 分支。props 与 antd Button 一致（auth 仅在非所有者分支生效）。
 *
 * 使用边界：仅用于"有手册上下文"的写路径与编辑配套按钮（开始编辑/
 * 上传保存/提交编制/文件管理/恢复草稿/回退/废止/长期保留等）；
 * view/download 类模块级读按钮维持 AuthButton（模块入口本身仍按
 * view 码门控，进入模块者已持 view）。
 */
export default function ManualAuthButton({manual, auth, ...rest}) {
  if (manual && manual.is_owner) {
    return <Button {...rest}/>;
  }
  return <AuthButton auth={auth} {...rest}/>;
}
