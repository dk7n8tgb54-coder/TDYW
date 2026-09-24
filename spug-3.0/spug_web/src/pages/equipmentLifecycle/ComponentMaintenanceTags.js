/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 部件维护状态标签：与系统运行健康状态分离展示。
 * 数据来源：后端 systems 列表/详情返回的 component_maintenance 汇总
 * （fault_count=有效且不影响系统运行的故障数；
 *   repairing_count=执行中且不影响系统运行的维修工单数）。
 * 部件故障/离线维修不参与系统健康状态计算，不得显示为系统"维修中"。
 */
import React from 'react';
import { Tag, Tooltip } from 'antd';

export default function ComponentMaintenanceTags({summary}) {
  if (!summary) return null;
  const {fault_count, repairing_count} = summary;
  if (!fault_count && !repairing_count) return null;
  return (
    <span>
      {!!fault_count && (
        <Tooltip title="存在不影响系统运行的部件故障，系统健康状态不受影响">
          <Tag color="orange">部件故障 {fault_count}</Tag>
        </Tooltip>
      )}
      {!!repairing_count && (
        <Tooltip title="存在不影响系统运行的执行中部件维修（离线维修）">
          <Tag color="blue">部件维修中 {repairing_count}</Tag>
        </Tooltip>
      )}
    </span>
  );
}
