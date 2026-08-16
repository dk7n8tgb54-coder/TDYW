/**
 * 文件表格组件
 * 【任务4.2】从Explorer组件拆分出来的子组件
 * 职责：封装Table的渲染逻辑
 *
 * 【修复 2026-07-17】取消整表 loading 灰色遮罩（antd Table loading 固定 false），
 *   改由 Explorer 顶部轻量进度条提示加载；interactionDisabled 时行降低透明度但保留内容可见。
 */
import React, { useMemo, useRef, useState, useEffect } from 'react';
import { Table, Empty } from 'antd';
import { resolveVisibleColumns } from './columnVisibility';

/**
 * 文件表格组件
 * @param {Object} props - 组件属性
 * @param {Array} props.columns - 列配置
 * @param {Array} props.dataSource - 数据源
 * @param {boolean} props.interactionDisabled - 是否禁用行交互（目录切换未命中缓存时）
 * @param {Array} props.selectedRowKeys - 选中的行keys
 * @param {Function} props.onSelectChange - 选中变化回调
 * @param {boolean} props.isSearching - 是否搜索模式
 * @param {Object} props.pagination - 分页配置
 * @param {Function} props.onTableChange - 表格变化回调
 * @param {Function} props.onRow - 行事件处理
 * @param {boolean} props.showPagination - 是否显示分页
 * @param {boolean} props.showSelection - 是否显示选择列（多选模式）
 * @param {boolean} props.isPublic - 是否公共空间
 */
const FileTable = ({
  columns,
  dataSource,
  interactionDisabled = false,
  selectedRowKeys,
  onSelectChange,
  isSearching,
  pagination,
  onTableChange,
  onRow,
  showPagination = true,
  showSelection = true,
  isPublic = false,
}) => {
  // 安全的选中keys
  const safeSelectedRowKeys = useMemo(() =>
    Array.isArray(selectedRowKeys) ? selectedRowKeys : []
  , [selectedRowKeys]);

  // 表格分页配置
  const tablePagination = useMemo(() => {
    if (!showPagination) return false;
    
    return {
      current: pagination?.current || 1,
      pageSize: pagination?.pageSize || 20,
      total: pagination?.total || dataSource?.length || 0,
      showSizeChanger: !isSearching,
      showQuickJumper: !isSearching,
      pageSizeOptions: ['10', '20', '50', '100'],
      showTotal: (total, range) => `${range[0]}-${range[1]} 项 / 共 ${total} 项`,
      onChange: pagination?.onChange,
    };
  }, [showPagination, pagination, isSearching, dataSource]);

  // 空状态渲染
  const emptyText = useMemo(() => {
    if (isPublic) {
      return (
        <Empty
          description={
            <div>
              <div style={{ fontSize: 16, marginBottom: 8 }}>暂无公共共享文件</div>
              <div style={{ fontSize: 14, color: '#999' }}>快来上传第一个文件，与全平台用户共享吧</div>
            </div>
          }
        />
      );
    }
    return (
      <Empty
        description={
          <div>
            <div style={{ fontSize: 16, marginBottom: 8 }}>暂无文件</div>
            <div style={{ fontSize: 14, color: '#999' }}>点击上传按钮开始上传你的第一个文件</div>
          </div>
        }
      />
    );
  }, [isPublic]);

  // 【2026-08-16 响应式列显隐】监听容器宽度，窄容器时按次要程度隐藏列（见 columnVisibility.js），
  //   优先保证文件名列可读；容器测量失败（无 ResizeObserver）时保持全列展示
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(null);

  useEffect(() => {
    if (typeof ResizeObserver === 'undefined' || !containerRef.current) return undefined;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry && entry.contentRect) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const visibleColumns = useMemo(
    () => resolveVisibleColumns(columns, containerWidth, showSelection ? 48 : 0),
    [columns, containerWidth, showSelection]
  );

  return (
    <div ref={containerRef}>
      <Table
      columns={visibleColumns}
      dataSource={dataSource}
      // 【修复 2026-07-17】取消整表 loading 灰色遮罩
      // 加载提示改由 Explorer 顶部轻量进度条承担，避免整张表变灰闪烁
      loading={false}
      rowKey="key"
      // 【2026-08-16 列宽调整】
      //   - tableLayout="fixed"：类型/大小/修改时间/创建人列按固定 width 分配，
      //     文件名列不设 width，作为唯一弹性列占满剩余空间，宽屏时文件名展示空间最大化
      //   - sticky：文件较多时表头粘性固定，内容滚动，表头保持可见
      //   - 移除 virtual：fixed 布局下未设 width 的列才能弹性伸缩，virtual 要求所有列设 width
      //   - 响应式列显隐（文件名优先）：容器变窄时按 创建人→大小→类型→路径 顺序隐藏
      //     次要列，保证文件名列始终有约 400px（见 columnVisibility.js），正常窄屏不出滚动条
      //   - scroll.x 为极端窄屏兜底：次要列全部隐藏后仍不足 400px 时（约 <640px 容器），
      //     表格保持最小总宽出横向滚动，避免文件名列被压到不可读
      tableLayout="fixed"
      sticky={!isSearching}
      scroll={{ x: 640 }}
      rowClassName={() => interactionDisabled ? 'explorer-row-disabled' : ''}
      rowSelection={showSelection ? {
        selectedRowKeys: safeSelectedRowKeys,
        onChange: onSelectChange,
        type: 'checkbox',
        // 目录切换未命中缓存时禁用选择框，防止对旧目录数据执行批量操作
        getCheckboxProps: () => interactionDisabled ? { disabled: true } : {},
        // 【2026-07-17 列宽修复】固定选择列宽度 48px，避免 antd 默认值漂移
        columnWidth: 48,
      } : null}
      onRow={onRow}
      pagination={tablePagination}
      onChange={onTableChange}
      onHeaderRow={() => ({
        onContextMenu: (e) => {
          e.preventDefault();
          e.stopPropagation();
        },
      })}
      locale={{ emptyText }}
      />
    </div>
  );
};

export default React.memo(FileTable);
