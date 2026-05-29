/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 * 
 * 分组传输列表组件 - 网盘风格
 * 支持按状态分组：上传中、已完成、失败
 */
import React from 'react';
import { Empty, Button, Tooltip, Collapse, Badge } from 'antd';
import {
  ClearOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined,
} from '@ant-design/icons';
import TransferItem from './TransferItem';

const { Panel } = Collapse;

/**
 * 分组传输列表组件
 * @param {Object} props
 * @param {Array} props.uploadingItems - 上传中/暂停中的项目
 * @param {Array} props.completedItems - 已完成的项目
 * @param {Array} props.errorItems - 失败的项目
 * @param {Object} props.uploadSpeed - 上传速度映射 {itemId: speed}
 * @param {Function} props.onPause - 暂停回调
 * @param {Function} props.onResume - 继续回调
 * @param {Function} props.onCancel - 取消回调
 * @param {Function} props.onRemove - 删除回调
 * @param {Function} props.onPauseAll - 全部暂停回调
 * @param {Function} props.onResumeAll - 全部开始回调
 * @param {Function} props.onClearCompleted - 清空已完成回调
 * @param {Function} props.onClearErrors - 清空失败回调
 */
const TransferList = ({
  uploadingItems = [],
  completedItems = [],
  errorItems = [],
  uploadSpeed = {},
  onPause,
  onResume,
  onCancel,
  onRemove,
  onPauseAll,
  onResumeAll,
  onClearCompleted,
  onClearErrors,
}) => {
  // 进一步分组：正在上传 vs 已暂停
  const activeItems = uploadingItems.filter(
    item => ['waiting', 'calculating', 'uploading', 'merging'].includes(item.status)
  );
  const pausedItems = uploadingItems.filter(
    item => item.status === 'paused'
  );
  
  // 全部为空时的空状态
  if (uploadingItems.length === 0 && completedItems.length === 0 && errorItems.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无传输任务"
        style={{ padding: '60px 0' }}
      />
    );
  }
  
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflowY: 'auto',
      overflowX: 'hidden',
      padding: 12,
      gap: 12,
    }}>
      {/* 正在上传区域 - 可折叠 */}
      {activeItems.length > 0 && (
        <div style={{
          background: 'linear-gradient(135deg, #e6f7ff 0%, #f0f9ff 100%)',
          borderRadius: 8,
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)',
          overflow: 'hidden',
        }}>
          <Collapse
            defaultActiveKey={['active']}
            ghost
            bordered={false}
            style={{ backgroundColor: 'transparent' }}
          >
            <Panel
              header={
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center',
                  width: '100%',
                  paddingRight: 8,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <LoadingOutlined style={{ color: '#1890ff', fontSize: 16 }} />
                    <span style={{ fontSize: 14, color: '#262626', fontWeight: 600 }}>
                      正在传输
                    </span>
                    <Badge 
                      count={activeItems.length} 
                      style={{ backgroundColor: '#1890ff', fontSize: 11 }}
                    />
                  </div>
                </div>
              }
              key="active"
              extra={
                <Tooltip title="全部暂停">
                  <Button
                    type="primary"
                    ghost
                    size="small"
                    icon={<PauseCircleOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      onPauseAll();
                    }}
                    style={{ fontSize: 12, borderRadius: 4 }}
                  >
                    全部暂停
                  </Button>
                </Tooltip>
              }
              style={{ 
                border: 'none',
              }}
            >
              <div style={{ maxHeight: 400, overflowY: 'auto', overflowX: 'hidden' }}>
              {activeItems.map((item, index) => (
                <div 
                  key={item.id}
                  style={{
                    borderBottom: index < activeItems.length - 1 ? '1px solid #f5f5f5' : 'none',
                  }}
                >
                  <TransferItem
                    item={item}
                    speed={uploadSpeed[item.id]}
                    onPause={onPause}
                    onResume={onResume}
                    onCancel={onCancel}
                    onRemove={onRemove}
                  />
                </div>
              ))}
              </div>
            </Panel>
          </Collapse>
        </div>
      )}
      
      {/* 已暂停区域 - 可折叠 */}
      {pausedItems.length > 0 && (
        <div style={{
          background: 'linear-gradient(135deg, #fffbe6 0%, #fff7e6 100%)',
          borderRadius: 8,
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)',
          overflow: 'hidden',
        }}>
          <Collapse
            defaultActiveKey={['paused']}
            ghost
            bordered={false}
            style={{ backgroundColor: 'transparent' }}
          >
            <Panel
              header={
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center',
                  width: '100%',
                  paddingRight: 8,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <PauseCircleOutlined style={{ color: '#faad14', fontSize: 16 }} />
                    <span style={{ fontSize: 14, color: '#262626', fontWeight: 600 }}>
                      已暂停
                    </span>
                    <Badge 
                      count={pausedItems.length} 
                      style={{ backgroundColor: '#faad14', fontSize: 11 }}
                    />
                  </div>
                </div>
              }
              key="paused"
              extra={
                <Button
                  type="primary"
                  ghost
                  size="small"
                  icon={<PlayCircleOutlined />}
                  onClick={(e) => {
                    e.stopPropagation();
                    onResumeAll();
                  }}
                  style={{ fontSize: 12, borderRadius: 4, borderColor: '#faad14', color: '#faad14' }}
                >
                  全部开始
                </Button>
              }
              style={{ 
                border: 'none',
              }}
            >
              <div style={{ maxHeight: 300, overflowY: 'auto', overflowX: 'hidden' }}>
              {pausedItems.map((item, index) => (
                <div 
                  key={item.id}
                  style={{
                    borderBottom: index < pausedItems.length - 1 ? '1px solid #f5f5f5' : 'none',
                  }}
                >
                  <TransferItem
                    item={item}
                    speed={uploadSpeed[item.id]}
                    onPause={onPause}
                    onResume={onResume}
                    onCancel={onCancel}
                    onRemove={onRemove}
                  />
                </div>
              ))}
              </div>
            </Panel>
          </Collapse>
        </div>
      )}
      
      {/* 传输失败区域 - 可折叠 */}
      {errorItems.length > 0 && (
        <div style={{
          background: 'linear-gradient(135deg, #fff2f0 0%, #fff5f5 100%)',
          borderRadius: 8,
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)',
          overflow: 'hidden',
        }}>
          <Collapse
            defaultActiveKey={['error']}
            ghost
            bordered={false}
            style={{ backgroundColor: 'transparent' }}
          >
            <Panel
              header={
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  width: '100%',
                  paddingRight: 8,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <CloseCircleFilled style={{ color: '#ff4d4f', fontSize: 16 }} />
                    <span style={{ fontSize: 14, color: '#ff4d4f', fontWeight: 600 }}>
                      传输失败
                    </span>
                    <Badge 
                      count={errorItems.length} 
                      style={{ backgroundColor: '#ff4d4f', fontSize: 11 }}
                    />
                  </div>
                </div>
              }
              key="error"
              extra={
                <Tooltip title="清空失败任务">
                  <Button
                    type="text"
                    size="small"
                    icon={<ClearOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      onClearErrors();
                    }}
                    style={{ fontSize: 12, color: '#8c8c8c' }}
                  >
                    清空
                  </Button>
                </Tooltip>
              }
              style={{ 
                border: 'none',
              }}
            >
              <div style={{ maxHeight: 300, overflowY: 'auto', overflowX: 'hidden' }}>
              {errorItems.map((item, index) => (
                <div 
                  key={item.id}
                  style={{
                    borderBottom: index < errorItems.length - 1 ? '1px solid #f5f5f5' : 'none',
                  }}
                >
                  <TransferItem
                    item={item}
                    speed={uploadSpeed[item.id]}
                    onPause={onPause}
                    onResume={onResume}
                    onCancel={onCancel}
                    onRemove={onRemove}
                  />
                </div>
              ))}
              </div>
            </Panel>
          </Collapse>
        </div>
      )}
      
      {/* 已完成区域 - 可折叠 */}
      {completedItems.length > 0 && (
        <div style={{
          background: 'linear-gradient(135deg, #f6ffed 0%, #f0f9ff 100%)',
          borderRadius: 8,
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.06)',
          overflow: 'hidden',
        }}>
          <Collapse
            defaultActiveKey={[]}
            ghost
            bordered={false}
            style={{ backgroundColor: 'transparent' }}
          >
            <Panel
              header={
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between', 
                  alignItems: 'center',
                  width: '100%',
                  paddingRight: 8,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <CheckCircleFilled style={{ color: '#52c41a', fontSize: 16 }} />
                    <span style={{ fontSize: 14, color: '#262626', fontWeight: 600 }}>
                      已完成
                    </span>
                    <Badge 
                      count={completedItems.length} 
                      style={{ backgroundColor: '#52c41a', fontSize: 11 }}
                    />
                  </div>
                </div>
              }
              key="completed"
              extra={
                <Tooltip title="清空已完成">
                  <Button
                    type="text"
                    size="small"
                    icon={<ClearOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      onClearCompleted();
                    }}
                    style={{ fontSize: 12, color: '#8c8c8c' }}
                  >
                    清空
                  </Button>
                </Tooltip>
              }
              style={{ 
                border: 'none',
              }}
            >
              <div style={{ maxHeight: 300, overflowY: 'auto', overflowX: 'hidden' }}>
              {completedItems.map((item, index) => (
                <div 
                  key={item.id}
                  style={{
                    borderBottom: index < completedItems.length - 1 ? '1px solid #f5f5f5' : 'none',
                  }}
                >
                  <TransferItem
                    item={item}
                    speed={uploadSpeed[item.id]}
                    onPause={onPause}
                    onResume={onResume}
                    onCancel={onCancel}
                    onRemove={onRemove}
                  />
                </div>
              ))}
              </div>
            </Panel>
          </Collapse>
        </div>
      )}
    </div>
  );
};

export default TransferList;
