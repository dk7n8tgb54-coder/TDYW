/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Button, Breadcrumb as AntdBreadcrumb, Badge, Radio, Dropdown, Menu, message } from 'antd';
import { UploadOutlined, CloudUploadOutlined, FolderAddOutlined, AppstoreOutlined, UnorderedListOutlined, DownOutlined, ReloadOutlined, ArrowLeftOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Breadcrumb as SpugBreadcrumb } from 'components';
import Explorer from './Explorer';
import UploadPanel, { MiniBar } from './UploadPanel';
import FolderTree from './FolderTree';
import SearchBox from './components/SearchBox';
import DiskStatus from './components/DiskStatus';
import KeyboardShortcuts from './components/KeyboardShortcuts';
import DocumentErrorBoundary from './components/DocumentErrorBoundary';
import DocumentDropUploadLayer from './components/DocumentDropUploadLayer';
import { isEmptyFolderBatch, isPlainFilesOnly, MAX_DROP_ENTRIES, MAX_DROP_DEPTH } from './utils/dropUpload';
import navigationStore from './stores/navigation';
import uploadUIStore from './stores/upload/ui';
import { uploadCoreStore } from './stores';
import { hasPermission, http } from 'libs';
import { setSystemFolder, PARTY_BUILDING_DOCUMENTS_CODE } from 'libs/systemFolderContext';
import styles from './DocumentLayout.module.less';
import './Explorer.module.less';

const DocumentIndex = observer(function ({ mode = 'normal', systemFolderCode = null, title = '资料库' }) {
  const isPartyBuildingDocuments = mode === 'partyBuildingDocuments' && systemFolderCode === PARTY_BUILDING_DOCUMENTS_CODE;
  const fileInputRef = React.useRef(null);
  const folderInputRef = React.useRef(null);
  const explorerRef = React.useRef(null);
  const folderTreeRef = React.useRef(null);
  const [detailPanelExpanded, setDetailPanelExpanded] = React.useState(false);
  const [viewMode, setViewMode] = React.useState('list');
  const [searchState, setSearchState] = React.useState({
    isSearching: false,
    keyword: '',
    scope: 'current',
    results: []
  });
  const [initError, setInitError] = React.useState(null);

  // 【2026-07-02 动态降级】资料库页面挂载时首次拉取服务器压力 + 启动轮询；
  //   卸载时停止轮询，避免离开页面后继续请求
  React.useEffect(() => {
    uploadCoreStore.initUploadPressure();
    uploadCoreStore.startPressurePolling();
    return () => {
      uploadCoreStore.stopPressurePolling();
    };
  }, []);

  // 【党建文档】进入页面时初始化系统目录上下文，离开时清理
  React.useLayoutEffect(() => {
    let cancelled = false;
    if (isPartyBuildingDocuments) {
      setSystemFolder(systemFolderCode);
      // 拉取系统目录绑定，初始化导航到党建文档根目录
      (async () => {
        try {
          const res = await http.get('/api/document/system-folder/', {
            params: { code: systemFolderCode },
          });
          if (cancelled) return;
          navigationStore.initSystemFolder({
            code: systemFolderCode,
            folderId: res.folder_id,
            name: res.folder_name || title,
          });
        } catch (e) {
          if (!cancelled) {
            setInitError(e?.message || '党建文档初始化失败');
          }
        }
      })();
    } else {
      setSystemFolder(null);
      if (navigationStore.lockedRootFolderId || navigationStore.systemFolderCode) {
        navigationStore.clearSystemFolder();
      }
    }
    return () => {
      cancelled = true;
      if (isPartyBuildingDocuments) {
        setSystemFolder(null);
        navigationStore.clearSystemFolder();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPartyBuildingDocuments, systemFolderCode, title]);

  const currentPath = navigationStore.getCurrentPath();
  const rootFolderId = navigationStore.lockedRootFolderId;
  const rootFolderName = navigationStore.lockedRootFolderName || title;
  const breadcrumbPath = isPartyBuildingDocuments && rootFolderId && currentPath[0]?.id === rootFolderId
    ? currentPath.slice(1)
    : currentPath;
  const breadcrumbPathIndexOffset = breadcrumbPath.length === currentPath.length ? 0 : 1;
  const canGoBack = isPartyBuildingDocuments ? breadcrumbPath.length > 0 : currentPath.length > 0;
  // 党建文档锁定模式：面包屑根节点显示锁定根名称，否则显示空间前缀
  const spacePrefix = isPartyBuildingDocuments
    ? rootFolderName
    : (navigationStore.isPublic ? '公共共享库' : '我的文件');

  // 党建文档模式下的权限前缀
  const permPrefix = isPartyBuildingDocuments ? 'document.party_building_document' : 'document.document';
  const canUpload = hasPermission(`${permPrefix}.upload`);
  const canCreateFolder = hasPermission(`${permPrefix}.create_folder`);
  const isPartyBuildingDocumentsReady = !isPartyBuildingDocuments || !!navigationStore.lockedRootFolderId;
  const hasStaleSystemFolderState = !isPartyBuildingDocuments
    && (navigationStore.lockedRootFolderId || navigationStore.systemFolderCode);
  const effectiveCurrentFolderId = hasStaleSystemFolderState ? null : navigationStore.currentFolderId;

  // 【2026-06-11 优化】智能面包屑省略
  // 路径 ≤ 3 级：完整显示
  // 路径 > 3 级：根 + 第 1 级 + "..." + 最后 1 级（省略中间）
  // hover "..." 显示被省略的完整路径（行业惯例：VSCode 资源管理器、macOS Finder）
  // 关键：避免路径过长时把"上传/新建文件夹/刷新"3 个按钮挤到右侧
  const renderBreadcrumbItems = () => {
    if (breadcrumbPath.length <= 2) {
      // 短路径（≤ 2 级子目录）：完整渲染
      return (
        <>
          <AntdBreadcrumb.Item
            onClick={() => navigationStore.navigateTo(-1)}
            style={{ cursor: 'pointer', color: breadcrumbPath.length > 0 ? '#1890ff' : '#666', fontWeight: 500 }}
          >
            {spacePrefix}
          </AntdBreadcrumb.Item>
          {breadcrumbPath.map((item, index) => (
            <AntdBreadcrumb.Item
              key={item.id}
              onClick={() => navigationStore.navigateTo(index + breadcrumbPathIndexOffset)}
              style={{ cursor: 'pointer', color: index === breadcrumbPath.length - 1 ? '#666' : '#1890ff' }}
            >
              {item.name}
            </AntdBreadcrumb.Item>
          ))}
        </>
      );
    }
    // 长路径（> 2 级子目录）：根 + 第 1 级 + "..." + 最后 1 级
    const first = breadcrumbPath[0];
    const last = breadcrumbPath[breadcrumbPath.length - 1];
    const omittedNames = breadcrumbPath.slice(1, -1).map((i) => i.name).join(' / ');
    return (
      <>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(-1)}
          style={{ cursor: 'pointer', color: '#1890ff', fontWeight: 500 }}
        >
          {spacePrefix}
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(breadcrumbPathIndexOffset)}
          style={{ cursor: 'pointer', color: '#1890ff' }}
        >
          {first.name}
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          style={{ cursor: 'default', color: '#8c8c8c' }}
          title={`已省略 ${breadcrumbPath.length - 2} 级：${omittedNames}`}
        >
          ...
        </AntdBreadcrumb.Item>
        <AntdBreadcrumb.Item
          onClick={() => navigationStore.navigateTo(breadcrumbPath.length - 1 + breadcrumbPathIndexOffset)}
          style={{ cursor: 'pointer', color: '#666' }}
        >
          {last.name}
        </AntdBreadcrumb.Item>
      </>
    );
  };

  const handleUploadMenu = ({ key }) => {
    if (key === 'file' && fileInputRef.current) {
      fileInputRef.current.click();
    } else if (key === 'folder' && folderInputRef.current) {
      folderInputRef.current.click();
    }
  };

  // 上传下拉菜单
  const uploadMenu = (
    <Menu
      onClick={handleUploadMenu}
      items={[
        { key: 'file', icon: <UploadOutlined />, label: '上传文件' },
        { key: 'folder', icon: <CloudUploadOutlined />, label: '上传文件夹' },
      ]}
    />
  );

  const handleFileSelect = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      if (isPartyBuildingDocuments) {
        message.info('文件将上传到党建文档，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件将上传到公共共享库，所有用户均可查看下载');
      }
      // 【2026-07-02】开始上传前刷新一次服务器压力，确保按最新等级调度
      uploadCoreStore.refreshPressure();
      uploadCoreStore.handleFileSelect(files);
    }
    e.target.value = '';
  };

  const handleFolderSelect = (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) {
      if (isPartyBuildingDocuments) {
        message.info('文件夹将上传到党建文档，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件夹将上传到公共共享库，所有用户均可查看下载');
      }
      // 【2026-07-02】开始上传前刷新一次服务器压力
      uploadCoreStore.refreshPressure();
      uploadCoreStore.handleFolderSelect(files);
    }
    e.target.value = '';
  };

  const handleRefresh = () => {
    if (folderTreeRef.current && folderTreeRef.current.refresh) {
      folderTreeRef.current.refresh();
    }
    if (explorerRef.current && explorerRef.current.fetchItems) {
      explorerRef.current.fetchItems();
    }
  };

  const handleSearchStart = () => {
    setSearchState(prev => ({ ...prev, isSearching: true }));
  };

  const handleSearchResult = (result) => {
    setSearchState({
      isSearching: true,
      keyword: result.keyword,
      scope: result.scope,
      results: result.items
    });
  };

  const handleSearchError = (errorMsg) => {
    message.error(errorMsg);
    setSearchState(prev => ({ ...prev, isSearching: false }));
  };

  const handleClearSearch = () => {
    setSearchState({ isSearching: false, keyword: '', scope: 'current', results: [] });
  };

  // 【拖拽上传】目标目录显示文本（用于遮罩提示 + captureTargetContext）
  // 普通模式：'我的文件 / 子目录' 或 '公共共享库 / 子目录'
  // 党建模式：'党建文档 / 子目录'
  const targetPathLabel = [
    spacePrefix,
    ...breadcrumbPath.map(p => p.name),
  ].filter(Boolean).join(' / ');

  // 【拖拽上传】捕获不可变目标上下文（drop 时立即调用，固化为快照）
  // 党建模式显式传 systemFolderCode，避免离开党建路由后丢失
  const captureDropTargetContext = () => {
    return uploadCoreStore.captureUploadTargetContext({
      systemFolderCode: isPartyBuildingDocuments ? PARTY_BUILDING_DOCUMENTS_CODE : null,
      targetPathLabel,
    });
  };

  // 【拖拽上传】drop 回调：收集结果 → 区分普通文件/文件夹 → 进入现有 uploadCoreStore
  const handleDropUpload = (collected, targetContext) => {
    // 空文件夹
    if (isEmptyFolderBatch(collected)) {
      message.info('空文件夹无需上传');
      return;
    }
    // 截断/深度超限警告
    if (collected.truncated) {
      message.warning(`文件数量超过上限（${MAX_DROP_ENTRIES}），已截断，请分批上传`);
    }
    if (collected.depthExceeded) {
      message.warning(`目录深度超过上限（${MAX_DROP_DEPTH}层），部分文件未上传`);
    }
    // 解析错误提示
    if (collected.errors && collected.errors.length > 0) {
      message.warning(collected.errors[0]);
    }
    if (collected.files.length === 0) return;

    // 刷新服务器压力，确保按最新等级调度
    uploadCoreStore.refreshPressure();

    // 区分普通文件 vs 文件夹：
    //   - 全是普通文件（无文件夹）→ handleFileSelect（走普通/分片上传）
    //   - 包含文件夹 → handleFolderEntries（走 FolderStructureBuilder + 普通上传）
    // 两条路径都进入同一套 uploadCoreStore，不新增队列
    if (isPlainFilesOnly(collected)) {
      if (isPartyBuildingDocuments) {
        message.info('文件将上传到党建文档，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFileSelect(collected.files, targetContext);
    } else {
      if (isPartyBuildingDocuments) {
        message.info('文件夹将上传到党建文档，所有用户均可查看下载');
      } else if (navigationStore.isPublic) {
        message.info('文件夹将上传到公共共享库，所有用户均可查看下载');
      }
      uploadCoreStore.handleFolderEntries(collected.entries, targetContext);
    }
  };

  return (
    <div className={styles.pageWrapper}>
      {/* 面包屑 + 磁盘状态 + 搜索 */}
      <SpugBreadcrumb extra={
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
          <DiskStatus isPublic={navigationStore.isPublic} />
          <SearchBox
            isPublic={navigationStore.isPublic}
            placeholder={isPartyBuildingDocuments ? '搜索党建文档' : undefined}
            folderId={isPartyBuildingDocuments ? navigationStore.lockedRootFolderId : undefined}
            onSearchStart={handleSearchStart}
            onSearchResult={handleSearchResult}
            onSearchError={handleSearchError}
            onClearSearch={handleClearSearch}
          />
        </div>
      }>
        <SpugBreadcrumb.Item>首页</SpugBreadcrumb.Item>
        <SpugBreadcrumb.Item>{title}</SpugBreadcrumb.Item>
      </SpugBreadcrumb>

      {initError && (
        <div style={{ padding: '12px 16px', color: '#ff4d4f' }}>{initError}</div>
      )}

      {!initError && !isPartyBuildingDocumentsReady && (
        <div style={{ padding: '24px 16px', color: '#666' }}>党建文档初始化中...</div>
      )}

      {!initError && isPartyBuildingDocumentsReady && <div className={styles.documentPage}>
        {/* 统一工具栏：左侧路径+操作，右侧视图切换+详情+上传 */}
        <div className={styles.toolBar}>
          <div className={styles.toolBarLeft}>
            {canGoBack && (
              <Button
                type="text"
                icon={<ArrowLeftOutlined />}
                onClick={navigationStore.goUp}
                className={styles.backButton}
                size="small"
              />
            )}
            <AntdBreadcrumb separator=">" className={styles.breadcrumb}>
              {renderBreadcrumbItems()}
            </AntdBreadcrumb>
            <span className={styles.toolbarDivider} />
            <input type="file" multiple style={{ display: 'none' }} ref={fileInputRef} onChange={handleFileSelect} />
            <input type="file" webkitdirectory="true" directory="true" multiple style={{ display: 'none' }} ref={folderInputRef} onChange={handleFolderSelect} />
            {canUpload && (
              <Dropdown overlay={uploadMenu} placement="bottomLeft">
                <Button type="primary" icon={<CloudUploadOutlined />} size="small">
                  上传 <DownOutlined style={{ fontSize: 10, marginLeft: 2 }} />
                </Button>
              </Dropdown>
            )}
            {canCreateFolder && (
              <Button icon={<FolderAddOutlined />} onClick={() => {
                if (explorerRef.current && explorerRef.current.handleAddFolder) {
                  explorerRef.current.handleAddFolder();
                }
              }} size="small">
                新建文件夹
              </Button>
            )}
            <Button icon={<ReloadOutlined />} onClick={handleRefresh} size="small">
              刷新
            </Button>
          </div>
          <div className={styles.toolBarRight}>
            <Badge count={uploadCoreStore.currentUploadQueue.length} offset={[-5, 5]}>
              <Button
                icon={<CloudUploadOutlined />}
                onClick={() => uploadUIStore.panel.toggle()}
                title="查看传输任务"
                size="small"
              />
            </Badge>
            <Radio.Group
              value={viewMode}
              onChange={(e) => setViewMode(e.target.value)}
              size="small"
            >
              <Radio.Button value="list" title="列表视图">
                <UnorderedListOutlined />
              </Radio.Button>
              <Radio.Button value="grid" title="缩略图视图">
                <AppstoreOutlined />
              </Radio.Button>
            </Radio.Group>
            <Button
              type="text"
              icon={detailPanelExpanded ? <RightOutlined /> : <LeftOutlined />}
              onClick={() => {
                if (explorerRef.current && explorerRef.current.toggleDetailPanel) {
                  explorerRef.current.toggleDetailPanel((newState) => {
                    setDetailPanelExpanded(newState);
                  });
                }
              }}
              size="small"
              title={detailPanelExpanded ? '收起详情' : '展开详情'}
            />
          </div>
        </div>

        {/* 主内容区 */}
        <div className={styles.mainContent}>
          <div className={styles.sidebarTree}>
            <FolderTree
              ref={folderTreeRef}
              isPublic={navigationStore.isPublic}
              onFolderChange={() => {}}
              lockedRoot={isPartyBuildingDocuments}
              rootFolderId={isPartyBuildingDocuments ? navigationStore.lockedRootFolderId : null}
              rootFolderName={isPartyBuildingDocuments ? rootFolderName : undefined}
              autoExpandAll={isPartyBuildingDocuments}
            />
          </div>
          <div className={styles.explorerArea}>
            <DocumentDropUploadLayer
              canUpload={canUpload}
              isPartyBuildingDocuments={isPartyBuildingDocuments}
              isPartyBuildingDocumentsReady={isPartyBuildingDocumentsReady}
              isSearching={searchState.isSearching}
              targetPathLabel={targetPathLabel}
              captureTargetContext={captureDropTargetContext}
              onDrop={handleDropUpload}
            >
              <Explorer
                folderId={effectiveCurrentFolderId}
                onFolderChange={() => {}}
                ref={explorerRef}
                viewMode={viewMode}
                isPublic={navigationStore.isPublic}
                searchState={searchState}
                isPartyBuildingDocuments={isPartyBuildingDocuments}
                permPrefix={permPrefix}
              />
            </DocumentDropUploadLayer>
          </div>
        </div>
      </div>}

      {isPartyBuildingDocumentsReady && uploadCoreStore.currentUploadQueue.length > 0 && !uploadUIStore.panel.expanded && (
        <MiniBar />
      )}
      {isPartyBuildingDocumentsReady && <UploadPanel />}
      {isPartyBuildingDocumentsReady && <KeyboardShortcuts />}
    </div>
  );
});

export default function DocumentIndexWrapper(props) {
  return (
    <DocumentErrorBoundary>
      <DocumentIndex {...props} />
    </DocumentErrorBoundary>
  );
}
