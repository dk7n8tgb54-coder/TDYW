/**
 * 历史版本更新日志抽屉
 *
 * - 左侧按版本列出历史版本，右侧展示所选版本的更新内容
 * - 顶部展示当前系统版本（来源：/api/system/version/）
 * - 顶部提供「每次更新后自动弹出更新日志」开关（与更新弹窗内勾选框为同一用户偏好）：
 *   关闭自动弹窗后，用户仍可从这里随时查看更新日志并重新开启
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Drawer, List, Tag, Spin, Empty, Typography, Switch, Tooltip} from 'antd';
import store from './store';

export default observer(function ReleaseNoteDrawer() {
  const items = store.detailItems;

  function handlePrefChange(checked) {
    // 失败时由 http 拦截器统一提示，开关保持原值
    store.savePopupSetting(checked).catch(() => {});
  }

  return (
    <Drawer
      title={<span>更新日志
        {store.currentVersion && (
          <Tag color="blue" style={{marginLeft: 8}}>当前版本 {store.currentVersion}</Tag>
        )}</span>}
      placement="right"
      width={780}
      visible={store.drawerVisible}
      onClose={store.closeDrawer}>
      <div style={{height: '100%', display: 'flex', flexDirection: 'column'}}>
        <div style={{
          display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
          marginBottom: 8, paddingBottom: 8, borderBottom: '1px solid #f0f0f0',
        }}>
          <Tooltip title="勾选后，系统每次更新会自动弹出更新日志；取消后不再自动弹窗，可随时从这里查看历史更新日志。">
            <span style={{marginRight: 8, color: '#595959'}}>每次更新后自动弹出更新日志</span>
          </Tooltip>
          <Switch
            checked={store.showAfterUpdate}
            onChange={handlePrefChange}
            size="small"
          />
        </div>
        <div style={{display: 'flex', flex: 1, minHeight: 0}}>
          <div style={{width: 180, borderRight: '1px solid #f0f0f0', overflow: 'auto'}}>
            <List
              size="small"
              dataSource={store.versions}
              renderItem={item => (
                <List.Item
                  onClick={() => store.selectVersion(item.version)}
                  style={{
                    cursor: 'pointer',
                    background: item.version === store.selectedVersion ? '#e6f7ff' : 'transparent',
                  }}>
                  <span>{item.version}</span>
                  <span style={{color: '#8c8c8c'}}>{item.count} 条</span>
                </List.Item>
              )}
            />
            {!store.versions.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无版本"/>}
          </div>
          <div style={{flex: 1, paddingLeft: 16, overflow: 'auto'}}>
            <Spin spinning={store.listLoading}>
              {!items.length && !store.listLoading && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该版本暂无更新内容"/>
              )}
              <ul style={{paddingLeft: 20, marginTop: 8}}>
                {items.map(item => (
                  <li key={item.id} style={{marginBottom: 12}}>
                    <Typography.Text strong>{item.title}</Typography.Text>
                    {item.is_required && (
                      <Tag color="red" style={{marginLeft: 8}}>需确认</Tag>
                    )}
                    <div style={{whiteSpace: 'pre-wrap', color: '#595959'}}>{item.content}</div>
                    <div style={{color: '#bfbfbf', fontSize: 12}}>{item.publish_at}</div>
                  </li>
                ))}
              </ul>
            </Spin>
          </div>
        </div>
      </div>
    </Drawer>
  );
});
