/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统详情抽屉。
 * 基本信息统一展示固定字段 + 系统类型模板字段值 + 系统自定义字段值；
 * 配置字段页签仅管理字段定义（不录入值）。
 * 步骤 3.1 新增"故障记录"页签（主体故障 + 受影响故障），
 * 不含巡检、维护、工单和统一系统履历页签。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Drawer, Tabs, Descriptions, Tag, Spin, Divider } from 'antd';
import store from './store';
import ConfigArchiveTab from './ConfigArchiveTab';
import ComponentsTab from './ComponentsTab';
import ChangeHistoryTab from './ChangeHistoryTab';
import SnapshotsTab from './SnapshotsTab';
import FaultRecordsTab from './FaultRecordsTab';
import SystemLedgerTab from './ledger/SystemLedgerTab';

const { TabPane } = Tabs;

@observer
class SystemDetail extends React.Component {
  renderConfigGroup(fields, title) {
    if (!fields.length) return null;
    return (
      <div>
        <Divider orientation="left" plain style={{fontSize: 13}}>{title}</Divider>
        <Descriptions bordered size="small" column={2}>
          {fields.map(f => (
            <Descriptions.Item
              key={f.id}
              label={(
                <span>
                  {f.display_name}
                  {!f.is_active && <Tag style={{marginLeft: 6}}>已停用</Tag>}
                  {f.is_sensitive && f.is_active && (
                    <Tag color="orange" style={{marginLeft: 6}}>敏感</Tag>
                  )}
                </span>
              )}
            >
              {f.display || '-'}
            </Descriptions.Item>
          ))}
        </Descriptions>
      </div>
    );
  }

  renderBasic() {
    const d = store.detail;
    const configFields = d.config_fields || [];
    const templateFields = configFields.filter(f => f.scope_type === 'template');
    const customFields = configFields.filter(f => f.scope_type === 'custom');
    return (
      <div>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="系统编号">{d.system_code}</Descriptions.Item>
          <Descriptions.Item label="系统名称">{d.name}</Descriptions.Item>
          <Descriptions.Item label="系统类型">{d.system_type_name}</Descriptions.Item>
          <Descriptions.Item label="系统型号">{d.system_model}</Descriptions.Item>
          <Descriptions.Item label="安装地点">{d.install_location}</Descriptions.Item>
          <Descriptions.Item label="安装经纬度">{d.geo_coordinate || '-'}</Descriptions.Item>
          <Descriptions.Item label="系统用途" span={2}>{d.system_purpose || '-'}</Descriptions.Item>
          <Descriptions.Item label="生产厂家">{d.manufacturer}</Descriptions.Item>
          <Descriptions.Item label="安装单位">{d.install_unit}</Descriptions.Item>
          <Descriptions.Item label="使用单位">{d.use_unit}</Descriptions.Item>
          <Descriptions.Item label="系统负责人">{d.responsible_user_name}</Descriptions.Item>
          <Descriptions.Item label="安装时间">{d.install_time || '-'}</Descriptions.Item>
          <Descriptions.Item label="启用时间">{d.enable_time || '-'}</Descriptions.Item>
          <Descriptions.Item label="当前状态" span={2}>
            <span style={{marginRight: 8}}>{d.health_status_text}</span>
            {d.is_active
              ? <Tag color="green">可用</Tag>
              : <Tag color="default">已停用</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{d.remark || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建人">{d.created_by_name}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{d.created_at}</Descriptions.Item>
        </Descriptions>
        {this.renderConfigGroup(templateFields, '类型扩展字段')}
        {this.renderConfigGroup(customFields, '系统自定义字段')}
      </div>
    );
  }

  render() {
    const d = store.detail;
    return (
      <Drawer
        title={`系统详情 - ${d.name || ''}`}
        visible={store.detailVisible}
        width={1000}
        onClose={() => store.closeDetail()}
        destroyOnClose
      >
        <Spin spinning={store.isDetailFetching}>
          <Tabs defaultActiveKey="basic">
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            <TabPane tab="配置字段" key="config">
              <ConfigArchiveTab/>
            </TabPane>
            <TabPane tab="配置组成项" key="components">
              <ComponentsTab/>
            </TabPane>
            <TabPane tab="配置变更历史" key="changes">
              <ChangeHistoryTab/>
            </TabPane>
            <TabPane tab="配置快照" key="snapshots">
              <SnapshotsTab/>
            </TabPane>
            <TabPane tab="故障记录" key="faults">
              <FaultRecordsTab systemId={d.id}/>
            </TabPane>
            <TabPane tab="巡检台账" key="inspection_ledger">
              <SystemLedgerTab systemId={d.id} ledgerType="inspection"/>
            </TabPane>
            <TabPane tab="周月维护台账" key="week_month_ledger">
              <SystemLedgerTab systemId={d.id} ledgerType="week_month"/>
            </TabPane>
            <TabPane tab="季维护台账" key="seasonal_ledger">
              <SystemLedgerTab systemId={d.id} ledgerType="seasonal"/>
            </TabPane>
          </Tabs>
        </Spin>
      </Drawer>
    );
  }
}

export default SystemDetail;
