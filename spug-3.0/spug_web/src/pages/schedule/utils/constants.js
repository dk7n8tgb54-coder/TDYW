/**
 * 排班模块常量
 * Schedule Module Constants
 * 
 * 第一阶段重构：基础设施
 */

// 换班/替班状态
export const SwapStatus = {
  PENDING: 'pending',
  APPROVED: 'approved',
  REJECTED: 'rejected',
  CANCELLED: 'cancelled',
};

// 状态显示文本
export const StatusText = {
  [SwapStatus.PENDING]: '待审批',
  [SwapStatus.APPROVED]: '已通过',
  [SwapStatus.REJECTED]: '已拒绝',
  [SwapStatus.CANCELLED]: '已取消',
};

// 状态标签颜色
export const StatusColor = {
  [SwapStatus.PENDING]: 'orange',
  [SwapStatus.APPROVED]: 'green',
  [SwapStatus.REJECTED]: 'red',
  [SwapStatus.CANCELLED]: 'default',
};

// 排班状态
export const ScheduleStatus = {
  ACTIVE: 'active',
  SWAPPED: 'swapped',
  SUBSTITUTED: 'substituted',
};

// 班次类型
export const ShiftType = {
  WORK_REST: 'work_rest',
  CUSTOM: 'custom',
};

// 班次类型文本
export const ShiftTypeText = {
  [ShiftType.WORK_REST]: '上X休Y',
  [ShiftType.CUSTOM]: '自定义',
};

// 错误消息
export const ErrorMessages = {
  RECORD_NOT_FOUND: '记录不存在或无权操作',
  SCHEDULE_CONFLICT: '该人员在此日期已有排班',
  SWAP_SELF: '不能与自己换班',
  ALREADY_APPROVED: '已审批的记录不能修改',
  INVALID_STATUS_TRANSITION: '不允许的状态流转',
};

// 默认分页配置
export const PaginationConfig = {
  DEFAULT_PAGE_SIZE: 20,
  MAX_PAGE_SIZE: 100,
};

// 批量操作限制
export const BatchLimits = {
  MAX_ITEMS_PER_BATCH: 100,
  MAX_PER_MINUTE: 10,
  MAX_PER_HOUR: 100,
};

// 日历配置
export const CalendarConfig = {
  MIN_DATE: '2000-01-01',
  MAX_DATE: '2100-12-31',
};
