/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统详情抽屉。
 * 基本信息展示固定字段；扩展信息展示 呼号 / 安装经纬度 / 工作频率（选填）。
 * （自定义字段机制已下线，原「系统当前配置」页签一并移除。）
 * 步骤 3.1 新增"故障记录"页签（单系统简化：只显示本系统故障）；
 * 步骤 3.3 新增"工单"页签（单系统简化：只显示本系统工单）；
 * 步骤 3.4 新增"系统履历"页签（统一履历事件，单系统简化：只显示本系统事件）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Drawer, Tabs, Descriptions, Tag, Spin, Divider } from 'antd';
import store from './store';
import FaultRecordsTab from './FaultRecordsTab';
import UpgradeRecordsTab from './UpgradeRecordsTab';
import ComponentMaintenanceTags from './ComponentMaintenanceTags';
import SystemLedgerTab from './ledger/SystemLedgerTab';
import WorkOrdersTab from './workOrder/WorkOrdersTab';
import SystemEventsTab from './systemEvent/SystemEventsTab';

const { TabPane } = Tabs;

@observer
class SystemDetail extends React.Component {
  renderBasic() {
    const d = store.detail;
    return (
      <div>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="系统名称">{d.name}</Descriptions.Item>
          <Descriptions.Item label="系统型号">{d.system_model}</Descriptions.Item>
          <Descriptions.Item label="安装地点" span={2}>{d.install_location}</Descriptions.Item>
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
            {/* 部件维护提示与系统运行状态分离展示 */}
            <ComponentMaintenanceTags summary={d.component_maintenance}/>
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{d.remark || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建人">{d.created_by_name}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{d.created_at}</Descriptions.Item>
        </Descriptions>
        <Divider orientation="left" plain style={{fontSize: 13}}>扩展信息</Divider>
        <Descriptions bordered size="small" column={3}>
          <Descriptions.Item label="呼号">{d.callsign || '-'}</Descriptions.Item>
          <Descriptions.Item label="安装经纬度">{d.geo_coordinate || '-'}</Descriptions.Item>
          <Descriptions.Item label="工作频率">{d.work_frequency || '-'}</Descriptions.Item>
        </Descriptions>
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
            <TabPane tab="故障记录" key="faults">
              <FaultRecordsTab systemId={d.id}/>
            </TabPane>
            <TabPane tab="升级记录" key="upgrade_records">
              <UpgradeRecordsTab systemId={d.id}/>
            </TabPane>
            <TabPane tab="工单" key="work_orders">
              <WorkOrdersTab systemId={d.id}/>
            </TabPane>
            {/* 旧巡检台账只承担历史查看（值班巡检改造后巡检走独立巡检单，不写入本台账） */}
            <TabPane tab="巡检台账（历史）" key="inspection_ledger">
              <SystemLedgerTab systemId={d.id} ledgerType="inspection"/>
            </TabPane>
            <TabPane tab="周月维护台账" key="week_month_ledger">
              <SystemLedgerTab systemId={d.id} ledgerType="week_month"/>
            </TabPane>
            <TabPane tab="季维护台账" key="seasonal_ledger">
              <SystemLedgerTab systemId={d.id} ledgerType="seasonal"/>
            </TabPane>
            <TabPane tab="系统履历" key="system_events">
              <SystemEventsTab systemId={d.id}/>
            </TabPane>
          </Tabs>
        </Spin>
      </Drawer>
    );
  }
}

export default SystemDetail;
