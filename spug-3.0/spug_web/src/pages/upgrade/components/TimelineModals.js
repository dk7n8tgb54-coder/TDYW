/**
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 状态时间线的操作菜单与弹窗（从 WorkbenchForm 迁出，2026-10 失败闭环改造拆分）：
 * - PhaseActionMenu："阶段操作"下拉按钮（标记失败/处理失败/重新执行分组）；
 * - TimelineActionModals：标记失败、处理失败、重新执行三个弹窗的集中挂载。
 */
import React from 'react';
import {Button, Dropdown, Menu} from 'antd';
import {DownOutlined} from '@ant-design/icons';
import {renderFlowNode, flowHeadline} from '../shared';
import {FailureCreateModal, FailureHandleModal} from './FailureModals';
import {RedoFromModal} from './RedoFromModal';
import styles from '../Workbench.module.less';

/** 键盘可操作的流程节点包装（Enter/空格触发点击，焦点样式见 nodeClickable:focus-visible） */
function ClickableNode({onClick, children}) {
  return (
    <span className={styles.nodeClickable} tabIndex={0} role="button" onClick={onClick}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') e.target.click(); }}>
      {children}
    </span>
  );
}

/** 流程节点快捷交互：current 下拉标记失败；failed/redoing 点击进处理失败；completed 无直点交互 */
function FlowNodeWithAction({node, idx, canEdit, onMarkFailure, onOpenFailure}) {
  const el = renderFlowNode(node, idx);
  if (!canEdit) return <span key={node.action}>{el}</span>;
  if (node.state === 'current') {
    return (
      <Dropdown key={node.action} trigger={['click']} overlay={(
        <Menu onClick={({key}) => key === 'test_fail' && onMarkFailure(node.label)}>
          <Menu.Item key="test_fail">标记【{node.label}】失败</Menu.Item>
        </Menu>
      )}>
        <ClickableNode>{el}</ClickableNode>
      </Dropdown>
    );
  }
  if (node.state === 'failed' || node.state === 'redoing') {
    return (
      <ClickableNode key={node.action} onClick={() => onOpenFailure(node.label)}>
        {el}
      </ClickableNode>
    );
  }
  return <span key={node.action}>{el}</span>;
}

/** 流程参考区：标题 + 节点行（含快捷交互） */
export function PhaseFlowArea({flowNodes, canEdit, onMarkFailure, onOpenFailure}) {
  return (
    <div className={styles.flowArea}>
      <div className={styles.flowHeadline}>{flowHeadline(flowNodes)}</div>
      <div className={styles.flowNodes}>
        {flowNodes.length > 0
          ? flowNodes.map((node, idx) => (
            <FlowNodeWithAction key={node.action} node={node} idx={idx + 1}
              canEdit={canEdit}
              onMarkFailure={onMarkFailure}
              onOpenFailure={onOpenFailure}/>
          ))
          : <span className={styles.flowEmpty}>暂无阶段（请为步骤设置阶段）</span>}
      </div>
    </div>
  );
}

/** "阶段操作"下拉按钮：actionGroups 由 buildPhaseActionGroups 生成 */
export function PhaseActionMenu({groups, onClick}) {
  return (
    <Dropdown trigger={['click']} overlay={(
      <Menu onClick={onClick}>
        {groups.map(g => (
          <Menu.ItemGroup key={g.key} title={g.title}>
            {g.items.map(item => (
              <Menu.Item key={item.key} danger={item.danger} disabled={item.disabled}>
                {item.label}
              </Menu.Item>
            ))}
          </Menu.ItemGroup>
        ))}
      </Menu>
    )}>
      <Button size="small">阶段操作 <DownOutlined /></Button>
    </Dropdown>
  );
}

/** 标记失败 / 处理失败 / 重新执行弹窗（phase/failure 为空表示关闭） */
export function TimelineActionModals({recordId, createFailurePhase, handleFailure,
                                      redoPhase, failureSteps, onCloseCreate,
                                      onCloseHandle, onCloseRedo}) {
  return (
    <React.Fragment>
      <FailureCreateModal
        visible={!!createFailurePhase}
        recordId={recordId} phase={createFailurePhase || ''}
        onCancel={onCloseCreate}
        onDone={onCloseCreate}/>
      <FailureHandleModal
        visible={!!handleFailure}
        recordId={recordId} failure={handleFailure}
        steps={handleFailure ? failureSteps(handleFailure) : []}
        onCancel={onCloseHandle}
        onDone={onCloseHandle}/>
      <RedoFromModal
        visible={!!redoPhase}
        recordId={recordId} phase={redoPhase || ''}
        onCancel={onCloseRedo}
        onDone={onCloseRedo}/>
    </React.Fragment>
  );
}
