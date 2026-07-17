/**
 * 文件表格组件
 * 【任务4.2】从Explorer组件拆分出来的子组件
 * 职责：封装Table的渲染逻辑
 *
 * 【修复 2026-07-17】取消整表 loading 灰色遮罩（antd Table loading 固定 false），
 *   改由 Explorer 顶部轻量进度条提示加载；interactionDisabled 时行降低透明度但保留内容可见。
 */
import React, { useMemo } from 'react';
import { Table, Empty } from 'antd';

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

  return (
    <Table
      columns={columns}
      dataSource={dataSource}
      // 【修复 2026-07-17】取消整表 loading 灰色遮罩
      // 加载提示改由 Explorer 顶部轻量进度条承担，避免整张表变灰闪烁
      loading={false}
      rowKey="key"
      // 【2026-07-17 布局优化】
      //   - tableLayout="fixed"：列宽按 width 分配，文件名列未设 width 自动获得剩余空间（弹性）
      //   - sticky：文件较多时表头粘性固定，内容滚动，表头保持可见
      //   - 移除 virtual：fixed 布局下未设 width 的列才能弹性伸缩，virtual 要求所有列设 width
      //   - 不设 scroll.x：避免横向滚动，列宽之和 = 容器宽度，文件名列自适应
      tableLayout="fixed"
      sticky={!isSearching}
      rowClassName={() => interactionDisabled ? 'explorer-row-disabled' : ''}
      rowSelection={{
        selectedRowKeys: safeSelectedRowKeys,
        onChange: onSelectChange,
        type: 'checkbox',
        // 目录切换未命中缓存时禁用选择框，防止对旧目录数据执行批量操作
        getCheckboxProps: () => interactionDisabled ? { disabled: true } : {},
        // 【2026-07-17 列宽修复】固定选择列宽度 48px，避免 antd 默认值漂移
        columnWidth: 48,
      }}
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
  );
};

export default React.memo(FileTable);
