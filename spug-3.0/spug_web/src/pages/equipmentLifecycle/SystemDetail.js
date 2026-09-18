/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统详情抽屉。
 * 展示：基本信息 / 当前状态 / 配置档案 / 配置组成项 / 配置变更历史 / 配置快照。
 * 本步骤不含故障、巡检、维护、工单和系统履历页签。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Drawer, Tabs, Descriptions, Tag, Spin } from 'antd';
import store from './store';
import ConfigArchiveTab from './ConfigArchiveTab';
import ComponentsTab from './ComponentsTab';
import ChangeHistoryTab from './ChangeHistoryTab';
import SnapshotsTab from './SnapshotsTab';

const { TabPane } = Tabs;

@observer
class SystemDetail extends React.Component {
  renderBasic() {
    const d = store.detail;
    return (
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
        <Descriptions.Item label="当前状态">
          <span style={{marginRight: 8}}>{d.health_status_text}</span>
          {d.is_active
            ? <Tag color="green">可用</Tag>
            : <Tag color="default">已停用</Tag>}
        </Descriptions.Item>
        <Descriptions.Item label="备注" span={2}>{d.remark || '-'}</Descriptions.Item>
        <Descriptions.Item label="创建人">{d.created_by_name}</Descriptions.Item>
        <Descriptions.Item label="创建时间">{d.created_at}</Descriptions.Item>
      </Descriptions>
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
            <TabPane tab="配置档案" key="config">
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
          </Tabs>
        </Spin>
      </Drawer>
    );
  }
}

export default SystemDetail;
