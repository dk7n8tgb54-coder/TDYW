/**
 * 操作日志表格
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Tag, Popover, Descriptions, Space } from 'antd';
import { TableCard } from 'components';
import store from './store';

const ACTION_MAP = {
  create: { text: '创建', color: 'green' },
  update: { text: '更新', color: 'blue' },
  delete: { text: '删除', color: 'red' },
  login: { text: '登录', color: 'cyan' },
  logout: { text: '登出', color: 'default' },
  export: { text: '导出', color: 'purple' },
  import: { text: '导入', color: 'purple' },
  approve: { text: '审批', color: 'orange' },
  other: { text: '其他', color: 'default' },
};

const TARGET_TYPE_MAP = {
  user: '用户',
  tenant: '租户',
  role: '角色',
  auth: '认证',
  device: '设备',
  document: '文档',
  fault: '故障',
  duty: '值班',
  interference: '干扰',
  runlog: '跨日事项跟踪',
  radio_license: '无线电台执照',
  contract_agreement: '合同协议',
  setting: '系统设置',
  upgrade: '升级',
  self: '个人信息',
  home: '首页',
  exec: '执行',
  api: 'API',
  audit: '操作日志',
  unknown: '未知',
};

// 字段名中文映射表（覆盖所有模块常见字段）
const FIELD_LABEL_MAP = {
  // 通用字段
  id: 'ID', name: '名称', title: '标题', username: '用户名', nickname: '昵称',
  desc: '描述', description: '描述', remark: '备注', comment: '备注',
  duty_record: '值班记录', duty_date: '值班日期', weather: '天气',
  duty_person_name: '值班人', record_id: '记录ID', changed_fields: '变更字段',
  signature_usage_id: '签署记录ID', signature_version: '签署版本',
  signature_sha256: '签署哈希', business_snapshot_hash: '业务快照哈希',
  returned_by_name: '退回人', original_signer_name: '原签署人',
  original_signed_at: '原签署时间', original_usage_id: '原签署记录ID',
  type: '类型', status: '状态', state: '状态', enabled: '是否启用',
  sort: '排序', order: '排序', priority: '优先级',
  created_at: '创建时间', updated_at: '更新时间', created_by: '创建人',
  // 用户/角色
  password: '密码', email: '邮箱', phone: '手机号', mobile: '手机号',
  role: '角色', roles: '角色', permissions: '权限', is_admin: '是否管理员',
  last_login: '最后登录', last_ip: '最后IP',
  // 设备
  device_type: '设备类型', device_name: '设备名称', device_no: '设备编号',
  ip: 'IP地址', port: '端口', model: '型号', manufacturer: '厂家',
  location: '位置', area: '区域', department: '部门', system: '所属系统',
  version: '版本', firmware: '固件版本', serial: '序列号',
  // 文档
  parent_id: '父目录ID', file_type: '文件类型', file_size: '文件大小',
  file_hash: '文件哈希', mime_type: 'MIME类型',
  // 值班
  shift: '班次', date: '日期',
  start_time: '开始时间', end_time: '结束时间', user_id: '用户ID',
  // 故障
  fault_type: '故障类型', fault_level: '故障等级', severity: '严重程度',
  occur_time: '发生时间', resolve_time: '解决时间', handler: '处理人',
  solution: '解决方案', cause: '原因',
  // 升级
  upgrade_type: '升级类型', ver: '版本号',
  upgrade_time: '升级时间', upgrade_content: '升级内容',
  // 检查表
  check_item: '检查项', check_result: '检查结果', checker: '检查人',
  check_time: '检查时间',
  // 干扰
  interference_type: '干扰类型', interference_source: '干扰源',
  interference_level: '干扰等级',
  // 其他
  token: '令牌', access_token: '访问令牌', expired: '已过期',
  content: '内容', data: '数据', result: '结果', message: '消息',
  action: '操作', method: '方法', url: 'URL', path: '路径',
};

/**
 * 格式化单个值
 */
function formatVal(value) {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (Array.isArray(value)) return value.join(', ') || '-';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

/**
 * 格式化 detail JSON 为易读的键值对
 * 支持 before/after 变更对比：detail.before 存在时，变更字段显示 "旧值 -> 新值"
 */
function formatDetail(detail) {
  if (!detail) return null;
  try {
    const obj = typeof detail === 'string' ? JSON.parse(detail) : detail;
    if (typeof obj !== 'object' || obj === null) return [{ label: '详情', value: String(obj) }];

    const items = [];
    const before = obj.before;
    const hasBefore = before && typeof before === 'object';

    // 1. 变更对比：before 中有记录的字段，显示 "旧值 -> 新值"
    //    新值优先从顶层取，找不到则从 after 嵌套对象取
    if (hasBefore) {
      const afterObj = (obj.after && typeof obj.after === 'object') ? obj.after : obj;
      for (const [key, oldVal] of Object.entries(before)) {
        const label = FIELD_LABEL_MAP[key] || key;
        const newVal = obj[key] !== undefined ? obj[key] : afterObj[key];
        items.push({ label, value: `${formatVal(oldVal)} -> ${formatVal(newVal)}` });
      }
    }

    // 2. 其他字段（跳过 before/after key 本身和已在 diff 中显示的字段）
    for (const [key, value] of Object.entries(obj)) {
      if (key === 'before' || key === 'after') continue;
      if (hasBefore && before.hasOwnProperty(key)) continue;
      const label = FIELD_LABEL_MAP[key] || key;
      items.push({ label, value: formatVal(value) });
    }

    return items.length > 0 ? items : null;
  } catch {
    return [{ label: '详情', value: String(detail) }];
  }
}

/**
 * 生成操作摘要：action 标签 + 可读句子
 * 如: [删除] 文档「测试报告.pdf」
 *     [登录] 系统（失败）
 */
function getSummary(record) {
  const actionInfo = ACTION_MAP[record.action] || ACTION_MAP.other;
  const targetType = TARGET_TYPE_MAP[record.target_type] || record.target_type || '';
  const targetName = record.target_name || '';
  const failed = record.is_success === 0 || record.is_success === false;

  // 登录/登出：不显示对象类型
  if (record.action === 'login' || record.action === 'logout') {
    return { tag: <Tag color={actionInfo.color}>{actionInfo.text}</Tag>, text: '系统' + (failed ? '（失败）' : '') };
  }

  // 其他操作：对象类型「对象名称」
  let text = '';
  if (targetType && targetName) {
    text = `${targetType}「${targetName}」`;
  } else if (targetName) {
    text = targetName;
  } else if (targetType) {
    text = targetType;
  }
  if (failed) text += '（失败）';

  return { tag: <Tag color={actionInfo.color}>{actionInfo.text}</Tag>, text };
}

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
    store.fetchOptions();
  }

  columns = [{
    title: '时间',
    width: 170,
    dataIndex: 'created_at',
  }, {
    title: '操作人',
    width: 100,
    dataIndex: 'username',
  }, {
    title: '操作摘要',
    width: 320,
    render: (_, record) => {
      const { tag, text } = getSummary(record);
      return <Space>{tag}<span>{text}</span></Space>;
    }
  }, {
    title: '操作结果',
    width: 80,
    render: text => (
      text['is_success']
        ? <Tag color="success">成功</Tag>
        : <Tag color="error">失败</Tag>
    ),
  }, {
    title: '来源IP',
    width: 140,
    dataIndex: 'ip',
  }, {
    title: '操作详情',
    width: 260,
    dataIndex: 'detail',
    render: text => {
      if (!text) return '-';
      const items = formatDetail(text);
      if (!items || items.length === 0) return '-';
      const preview = items.slice(0, 2).map(({ label, value }) => `${label}: ${value}`).join('；')
        + (items.length > 2 ? ` ...等${items.length}项` : '');
      const content = (
        <Descriptions column={1} size="small" bordered
          contentStyle={{ maxWidth: 350, wordBreak: 'break-all', fontSize: 12 }}
          labelStyle={{ width: 100, whiteSpace: 'nowrap', fontSize: 12 }}
        >
          {items.map(({ label, value }, idx) => (
            <Descriptions.Item key={idx} label={label}>{value}</Descriptions.Item>
          ))}
        </Descriptions>
      );
      return (
        <Popover content={content} title="操作详情" trigger="click" placement="left">
          <span style={{ cursor: 'pointer', color: '#1890ff' }}>{preview}</span>
        </Popover>
      );
    }
  }];

  render() {
    return (
      <TableCard
        tKey="audit"
        rowKey="id"
        title="操作日志"
        loading={store.isFetching}
        dataSource={store.dataSource}
        onReload={store.fetchRecords}
        actions={[]}
        pagination={{
          current: store.page,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100'],
          onChange: store.changePage,
          onShowSizeChange: store.changePage,
        }}
        columns={this.columns}
      />
    )
  }
}

export default ComTable
