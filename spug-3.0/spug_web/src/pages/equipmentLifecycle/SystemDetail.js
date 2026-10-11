/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统详情窗口（2026-10-02 由侧边抽屉改为居中窗口）。
 * 标题区直接呈现系统名称、运行健康状态、可用性与部件维护提示，副标题展示关键档案摘要。
 * 基本信息展示固定字段；扩展信息展示 呼号 / 安装经纬度 / 工作频率（选填）。
 * （自定义字段机制已下线，原「系统当前配置」页签一并移除。）
 * 步骤 3.1 新增"故障记录"页签（单系统简化：只显示本系统故障）；
 * 步骤 3.3 新增"工单"页签（单系统简化：只显示本系统工单）。
 * 2026-10-11："周月维护台账""季维护台账""系统履历"三个页签移除，
 * 三项业务仍由各自独立菜单页面承载（周月/季维护台账、系统履历）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Tabs, Descriptions, Tag, Spin, Divider, Button } from 'antd';
import store from './store';
import { HEALTH_STATUS_COLOR } from './constants';
import FaultRecordsTab from './FaultRecordsTab';
import UpgradeRecordsTab from './UpgradeRecordsTab';
import ComponentMaintenanceTags from './ComponentMaintenanceTags';
import SystemRuntimeRecordsTab from './SystemRuntimeRecordsTab';
import SystemConfigTab from './systemConfig/SystemConfigTab';

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

  renderTitle() {
    const d = store.detail;
    const facts = [
      d.system_model ? `型号：${d.system_model}` : null,
      d.install_location ? `安装地点：${d.install_location}` : null,
      d.use_unit ? `使用单位：${d.use_unit}` : null,
      d.responsible_user_name ? `负责人：${d.responsible_user_name}` : null,
    ].filter(Boolean);
    return (
      <div>
        <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap'}}>
          <span
            title={d.name}
            style={{
              fontSize: 16, fontWeight: 600, marginRight: 8, maxWidth: 520,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}
          >
            {d.name || '系统详情'}
          </span>
          <Tag color={HEALTH_STATUS_COLOR[d.health_status] || 'default'}>
            {d.health_status_text}
          </Tag>
          {d.is_active ? <Tag color="green">可用</Tag> : <Tag color="default">已停用</Tag>}
          <ComponentMaintenanceTags summary={d.component_maintenance}/>
        </div>
        {facts.length > 0 && (
          <div style={{fontSize: 12, color: 'rgba(0, 0, 0, 0.45)', marginTop: 2, fontWeight: 400}}>
            {facts.join('　')}
          </div>
        )}
      </div>
    );
  }

  render() {
    const d = store.detail;
    return (
      <Modal
        title={this.renderTitle()}
        visible={store.detailVisible}
        width={1100}
        centered
        destroyOnClose
        onCancel={() => store.closeDetail()}
        bodyStyle={{
          height: 'calc(100vh - 180px)',
          minHeight: 460,
          overflow: 'auto',
          paddingTop: 12,
        }}
        footer={<Button onClick={() => store.closeDetail()}>关 闭</Button>}
      >
        <Spin spinning={store.isDetailFetching}>
          <Tabs defaultActiveKey="basic">
            <TabPane tab="基本信息" key="basic">
              {this.renderBasic()}
            </TabPane>
            <TabPane tab="故障记录" key="faults">
              <FaultRecordsTab systemId={d.id}/>
            </TabPane>
            {/* 运行记录（2026-10 第一版）：本系统运行情况统一录入 */}
            <TabPane tab="运行记录" key="runtime_records">
              <SystemRuntimeRecordsTab systemId={d.id}/>
            </TabPane>
            <TabPane tab="升级记录" key="upgrade_records">
              <UpgradeRecordsTab systemId={d.id}/>
            </TabPane>
            {/* 系统配置（2026-10）：当前配置 + 配置变更历史 + 记录配置变更（Modal），
                只在系统详情内展示，不设独立菜单，也不与运行记录/系统升级混淆 */}
            <TabPane tab="配置" key="config">
              <SystemConfigTab systemId={d.id}/>
            </TabPane>
            {/* 周月维护台账/季维护台账/系统履历页签已下线（2026-10-11）：
                三项业务由各自独立菜单页面承载，不再在详情弹窗内嵌展示 */}
          </Tabs>
        </Spin>
      </Modal>
    );
  }
}

export default SystemDetail;
