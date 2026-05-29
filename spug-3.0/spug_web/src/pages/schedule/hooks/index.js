/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 排班模块Hooks
 * 
 * 第4阶段重构：前端组件拆分
 */

// 排班数据Hook
export {
  useSchedulesForDate,
  useGroupedByShift,
  useIsInSwap,
  useIsInSubstitute,
  useScheduleInit,
  useFetchExtendedSchedules,
} from './useSchedule';

// 审批流程Hook
export {
  useApproval,
} from './useApproval';

export { default } from './useSchedule';
