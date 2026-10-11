/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运行与故障记录详情模块共享小工具（区块标题内联样式，不新增全局样式）。
 */
import React from 'react';

// 区块标题（基本信息区块与进展工作区共用，与系统档案详情同款内联样式）
export function sectionTitle(text, style) {
  return <div style={{fontWeight: 600, marginBottom: 8, ...style}}>{text}</div>;
}
