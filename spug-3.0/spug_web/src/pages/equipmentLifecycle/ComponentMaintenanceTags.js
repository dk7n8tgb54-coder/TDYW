/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 部件维护状态标签：与系统运行健康状态分离展示。
 * 数据来源：后端 systems 列表/详情返回的 component_maintenance 汇总
 * （fault_count=有效且不影响系统运行的故障数；repairing_count 已随
 * 故障维修工单功能整体删除，2026-09-30）。
 * 部件故障不参与系统健康状态计算，不得显示为系统"维修中"。
 */
import React from 'react';
import { Tag, Tooltip } from 'antd';

export default function ComponentMaintenanceTags({summary}) {
  if (!summary) return null;
  const {fault_count} = summary;
  if (!fault_count) return null;
  return (
    <span>
      {!!fault_count && (
        <Tooltip title="存在不影响系统运行的部件故障，系统健康状态不受影响">
          <Tag color="orange">部件故障 {fault_count}</Tag>
        </Tooltip>
      )}
    </span>
  );
}
