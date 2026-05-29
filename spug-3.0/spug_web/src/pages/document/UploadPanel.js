/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 *
 * 上传面板组件 - 网盘风格版本
 * 仿阿里云盘、百度网盘设计
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Tag, message } from 'antd';
import { CloudUploadOutlined, CloudOutlined } from '@ant-design/icons';
import { uploadCoreStore } from './stores';
import navigationStore from './stores/navigation';
import TransferListContainer from './components/TransferListContainer';

// ============================================================
// 主上传面板组件 - 网盘风格
// ============================================================
@observer
class UploadPanel extends React.Component {
  fileInputRef = React.createRef();
  pendingItemId = null;

  componentDidMount() {
    // 重写 store 的 triggerFileReSelection 方法，使其调用本组件的方法
    uploadCoreStore.triggerFileReSelection = this.handleTriggerFileReSelection;
  }

  /**
   * 【任务3.4】组件卸载时清理资源，防止内存泄漏
   */
  componentWillUnmount() {
    // 清理文件输入框引用
    if (this.fileInputRef.current) {
      this.fileInputRef.current.value = '';
    }
    this.pendingItemId = null;

    // 取消所有进行中的上传任务
    const { currentUploadQueue } = uploadCoreStore;
    const activeItems = currentUploadQueue.filter(
      item => ['waiting', 'calculating', 'uploading', 'merging'].includes(item.status)
    );

    activeItems.forEach(item => {
      // 使用 store 的 pause 方法暂停任务，这会触发 AbortController.abort()
      uploadCoreStore.pauseItem(item.id);
    });

    // 清理 store 中对本组件方法的引用
    if (uploadCoreStore.triggerFileReSelection === this.handleTriggerFileReSelection) {
      uploadCoreStore.triggerFileReSelection = null;
    }
  }

  /**
   * 触发文件重新选择（断点续传使用）
   */
  handleTriggerFileReSelection = (itemId) => {
    this.pendingItemId = itemId;
    // 延迟触发文件选择器，让用户看到提示
    setTimeout(() => {
      if (this.fileInputRef.current) {
        this.fileInputRef.current.click();
      }
    }, 100);
  };

  /**
   * 处理文件选择（断点续传）
   */
  handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file || !this.pendingItemId) return;

    const itemId = this.pendingItemId;
    const item = uploadCoreStore.queueStore.findUploadItemInCurrentTenant(itemId);

    if (!item) {
      message.error('上传项不存在');
      this.pendingItemId = null;
      e.target.value = '';
      return;
    }

    // 校验文件信息是否匹配
    if (file.name !== item.name) {
      message.error(`文件名不匹配，请选择正确的文件: ${item.name}`);
      e.target.value = '';
      return;
    }

    if (file.size !== item.fileSize) {
      message.error('文件大小不匹配，请选择正确的文件');
      e.target.value = '';
      return;
    }

    // 清空 input 以便下次选择同一文件
    e.target.value = '';
    this.pendingItemId = null;

    // 调用 store 方法替换文件并恢复上传
    try {
      await uploadCoreStore.replaceFileAndResume(itemId, file);
    } catch (error) {
      console.error('[UploadPanel] 重新选择文件后恢复上传失败:', error);
      message.error('恢复上传失败: ' + (error.message || '未知错误'));
    }
  };

  /**
   * 暂停单个任务
   */
  handlePauseItem = (itemId) => {
    uploadCoreStore.pauseItem(itemId);
  };

  /**
   * 继续/重试单个任务
   */
  handleResumeItem = async (itemId) => {
    try {
      await uploadCoreStore.resumeItem(itemId);
    } catch (error) {
      console.error('[UploadPanel] 继续上传失败:', error);
      message.error('继续上传失败: ' + (error.message || '未知错误'));
    }
  };

  /**
   * 取消单个任务
   */
  handleCancelItem = (itemId) => {
    uploadCoreStore.cancelItem(itemId);
  };

  /**
   * 删除单个任务
   */
  handleRemoveItem = (itemId) => {
    // 【修复】删除error状态任务时，主动释放file对象避免内存泄漏
    const item = uploadCoreStore.queueStore.findUploadItemInCurrentTenant(itemId);
    if (item?.status === 'error' && item?.file) {
      item.file = null;
    }
    uploadCoreStore.removeItem(itemId);
  };

  /**
   * 全部暂停
   */
  handlePauseAll = () => {
    uploadCoreStore.pauseAll();
  };

  /**
   * 全部开始
   */
  handleResumeAll = () => {
    uploadCoreStore.resumeAll();
  };

  /**
   * 清空已完成
   */
  handleClearCompleted = async () => {
    const { currentUploadQueue } = uploadCoreStore;
    const completedItems = currentUploadQueue.filter(item => item.status === 'completed');
    
    // 【新增】同步删除后端传输记录
    const transferIds = completedItems
      .map(item => item.transferId)
      .filter(id => id); // 过滤掉 null/undefined
    
    console.log('[UploadPanel] 清空已完成任务:', {
      completedCount: completedItems.length,
      transferIds: transferIds,
      itemsWithNullTransferId: completedItems.filter(item => !item.transferId).length
    });
    
    if (transferIds.length > 0) {
      try {
        console.log('[UploadPanel] 调用 batchDeleteTransfers, IDs:', transferIds);
        await uploadCoreStore.transferStore.batchDeleteTransfers(transferIds);
        console.log('[UploadPanel] batchDeleteTransfers 调用成功');
      } catch (error) {
        console.error('[UploadPanel] 批量删除后端传输记录失败:', error);
        console.error('[UploadPanel] 错误详情:', error?.response?.data || error?.message || error);
        // 不显示警告，因为 Celery 任务是异步的，即使任务提交成功也可能返回错误
      }
    }
    
    // 【修复】批量删除后直接清理前端队列，不调用 removeItem（避免重复删除后端记录）
    // 【关键修复】使用 uploadCoreStore.getCurrentTenantId() 获取正确的租户ID
    const tenantId = uploadCoreStore.getCurrentTenantId?.() || 'default';
    completedItems.forEach(item => {
      uploadCoreStore.queueStore.removeFromQueue(item.id, tenantId);
    });
    // 【新增】批量删除后，尝试从等待队列补充新任务
    setTimeout(() => {
      uploadCoreStore.replenishDisplayQueue();
    }, 0);
    message.success(`已清空 ${completedItems.length} 个已完成任务`);
  };

  /**
   * 清空失败任务（包括已取消的）
   */
  handleClearErrors = async () => {
    const { currentUploadQueue } = uploadCoreStore;
    const errorItems = currentUploadQueue.filter(item => ['error', 'cancelled'].includes(item.status));
    
    // 【新增】同步删除后端传输记录
    const transferIds = errorItems
      .map(item => item.transferId)
      .filter(id => id); // 过滤掉 null/undefined
    
    if (transferIds.length > 0) {
      try {
        await uploadCoreStore.transferStore.batchDeleteTransfers(transferIds);
      } catch (error) {
        console.error('[UploadPanel] 批量删除后端传输记录失败:', error);
        // 后端删除失败不影响前端清理
      }
    }
    
    // 【修复】批量删除后直接清理前端队列，不调用 removeItem（避免重复删除后端记录）
    // 【关键修复】使用 uploadCoreStore.getCurrentTenantId() 获取正确的租户ID
    const tenantId = uploadCoreStore.getCurrentTenantId?.() || 'default';
    errorItems.forEach(item => {
      uploadCoreStore.queueStore.removeFromQueue(item.id, tenantId);
    });
    message.success(`已清空 ${errorItems.length} 个失败/取消任务`);
  };

  render() {
    // 【P2优化】使用 store 中的 computed 属性，避免每次 render 重复 filter
    const {
      uploadingItems,
      completedItems,
      errorItems,
      waitingCount,
      activeCount,
      pausedCount,
      currentUploadQueue
    } = uploadCoreStore;
    
    // 访问触发器以确保响应式更新
    void uploadCoreStore.uploadRefreshTrigger;
    void uploadCoreStore.folderUploadProgress;
    
    // 空间信息
    const spaceType = navigationStore.isPublic ? '公共共享库' : '我的文件';
    const spaceColor = navigationStore.isPublic ? 'gold' : 'blue';
    const spaceIcon = navigationStore.isPublic ? <CloudOutlined /> : <CloudUploadOutlined />;
    
    // 计算总任务数
    const totalTaskCount = currentUploadQueue.length;
    
    return (
      <Card
        size="small"
        style={{ 
          width: 520,
          height: 600, 
          display: 'flex', 
          flexDirection: 'column',
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        }}
        bodyStyle={{ 
          padding: 0, 
          flex: 1, 
          display: 'flex', 
          flexDirection: 'column', 
          overflow: 'hidden',
        }}
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Tag 
              icon={spaceIcon}
              color={spaceColor} 
              style={{ margin: 0, fontSize: 12, borderRadius: 4 }}
            >
              {spaceType}
            </Tag>
            <span style={{ fontSize: 12, color: '#8c8c8c' }}>
              共 {totalTaskCount} 个 | 等待中: {waitingCount} | 上传中: {activeCount} | 已暂停: {pausedCount} | 已完成: {completedItems.length} | 失败: {errorItems.length}
            </span>
          </div>
        }
      >
        {/* 隐藏的文件选择输入框（用于断点续传重新选择文件） */}
        <input
          ref={this.fileInputRef}
          type="file"
          style={{ display: 'none' }}
          onChange={this.handleFileSelect}
          accept="*/*"
        />
        <TransferListContainer
          uploadingItems={uploadingItems}
          completedItems={completedItems}
          errorItems={errorItems}
          uploadSpeed={uploadCoreStore.fileUploadStore?.uploadSpeed || {}}
          onPause={this.handlePauseItem}
          onResume={this.handleResumeItem}
          onCancel={this.handleCancelItem}
          onRemove={this.handleRemoveItem}
          onPauseAll={this.handlePauseAll}
          onResumeAll={this.handleResumeAll}
          onClearCompleted={this.handleClearCompleted}
          onClearErrors={this.handleClearErrors}
        />
      </Card>
    );
  }
}

export default UploadPanel;
