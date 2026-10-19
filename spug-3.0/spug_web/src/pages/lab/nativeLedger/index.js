/**
 * 实验室：原生维护台账样板（Univer 独立样板内嵌页）。
 *
 * 该页面是平台侧的全屏壳：路由在 App.js 中挂载于 Layout 之前，
 * 不套平台侧栏/Header，直接用 iframe 内嵌独立样板，样板 UI 不做任何改动。
 * 样板数据仍保存在浏览器 localStorage，不调用平台后端接口。
 *
 * 静态包由 quality/prototypes/native_ledger 的 `npm run build:lab` 生成到
 * spug_web/public/lab/native-ledger；本地联调也可用环境变量
 * REACT_APP_NATIVE_LEDGER_URL 指向样板 dev server（如 http://127.0.0.1:4173/）。
 */
import React from 'react';
import {Button, Result} from 'antd';
import {hasPermission, history} from 'libs';

const LAB_URL = process.env.REACT_APP_NATIVE_LEDGER_URL
  || `${process.env.PUBLIC_URL || ''}/lab/native-ledger/index.html`;

export default function NativeLedgerLab() {
  if (!hasPermission('lab.native_ledger.view')) {
    return (
      <Result
        status="403"
        title="403"
        subTitle="没有实验室页面的访问权限，请联系管理员分配“实验室 / 原生维护台账 / 查看”权限。"
        extra={<Button type="primary" onClick={() => history.push('/home')}>返回工作台</Button>}/>
    );
  }
  return (
    <div style={{position: 'relative', width: '100vw', height: '100vh', overflow: 'hidden'}}>
      <iframe
        title="原生维护台账样板"
        src={LAB_URL}
        style={{display: 'block', width: '100%', height: '100%', border: 0}}/>
      <Button
        size="small"
        style={{position: 'fixed', right: 16, bottom: 16, zIndex: 10}}
        onClick={() => history.push('/home')}>
        返回平台
      </Button>
    </div>
  );
}
