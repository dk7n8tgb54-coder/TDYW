/**
 * 协作任务模块共享常量与纯函数
 */

export const TASK_STATUS_MAP = {
  in_progress: {color: 'blue', text: '进行中'},
  completed: {color: 'green', text: '已完成'},
  voided: {color: 'default', text: '已作废'},
};

export const ASSIGNMENT_STATUS_MAP = {
  pending: {color: 'orange', text: '待交付'},
  partial: {color: 'gold', text: '部分交付'},
  submitted: {color: 'blue', text: '待验收'},
  rejected: {color: 'red', text: '待重新交付'},
  accepted: {color: 'green', text: '已完成'},
};

export const DELIVERY_STATUS_MAP = {
  pending: {color: 'orange', text: '待交付'},
  submitted: {color: 'blue', text: '待验收'},
  accepted: {color: 'green', text: '已验收'},
  rejected: {color: 'red', text: '已退回'},
};

/**
 * 由交付计数聚合分派状态（与后端 compute_assignment_status 保持一致）
 */
export function computeAssignmentStatus(total, accepted, rejected, pending) {
  if (!total || pending === total) return 'pending';
  if (rejected) return 'rejected';
  if (accepted === total) return 'accepted';
  if (pending === 0) return 'submitted';
  return 'partial';
}

/**
 * 构造创建任务的请求体
 * values: 表单值 {title, description, deadline(moment), items: [{name, remark}]}
 * selectedAccounts: [3, 5] 选中的交付科室账号ID（后端映射回租户并快照人名）
 */
export function buildTaskPayload(values, selectedAccounts) {
  return {
    title: values.title,
    description: values.description || '',
    deadline: values.deadline ? values.deadline.format('YYYY-MM-DD HH:mm:ss') : '',
    items: (values.items || []).map(x => ({name: (x.name || '').trim(), remark: (x.remark || '').trim()})),
    targets: (selectedAccounts || []).map(id => ({user_id: id})),
  };
}
