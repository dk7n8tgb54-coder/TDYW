/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 日历视图组件（重构后）
 * 
 * 第4阶段重构：使用拆分后的组件
 * 
 * 原文件 CalendarView.js.bak (883行) 已拆分为：
 * - components/Calendar/index.js
 * - components/Calendar/DateCell.js
 * - components/ScheduleModal/
 * - components/BatchDeleteModal/
 * - hooks/useSchedule.js
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Calendar } from './components';
import store from './stores';

function CalendarView(props) {
  return <Calendar {...props} />;
}

export default observer(CalendarView);
