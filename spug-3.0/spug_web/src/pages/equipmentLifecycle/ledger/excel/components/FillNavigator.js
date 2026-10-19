/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * Excel 台账填写导航（2026-10-19）。
 *
 * 填写表格旁的可收起导航面板：
 * - 进度汇总：已填/总字段、必填已填/必填总数 + 必填完成度进度条——口径
 *   与「完成填写」校验同源（store.fillProgress / missingRequiredBindings，
 *   必填缺失字段名即 requiredMissing()），导航显示完成时提交不会提示缺项；
 * - 按工作表组织的字段清单（store.bindingsBySheet，保持布局工作表顺序，
 *   只含有绑定的工作表）：每行区分已填（绿勾）/未填必填（红星）/
 *   未填选填（灰圈），点击行经 onLocate 定位到该字段（跨工作表时由
 *   父级切换工作表后滚动定位）；
 * - 「下一个未填必填项」：按缺失清单循环定位（记住上次定位字段，
 *   从下一项开始、到尾回卷），无缺失时禁用。
 *
 * observer：逐行读取 store.values 推导已填状态，填写值变化即时更新。
 */
import React, {useRef} from 'react';
import {observer} from 'mobx-react';
import {Button, Progress} from 'antd';
import {DoubleLeftOutlined} from '@ant-design/icons';

function isUnfilled(value) {
  return value === undefined || value === null || value === '';
}

/** 单个字段行：状态标记 + 字段名 + 坐标，点击定位。 */
function NavigatorField({binding, filled, onLocate}) {
  const missingRequired = binding.is_required && !filled;
  const classNames = ['el-fill-nav-field'];
  if (filled) classNames.push('el-fill-nav-field-filled');
  if (missingRequired) classNames.push('el-fill-nav-field-missing');
  const state = filled ? '✓' : (binding.is_required ? '＊' : '○');
  return (
    <div className={classNames.join(' ')} data-testid="fill-nav-field"
         data-field-id={binding.field_id}
         title={`点击定位：${binding.sheet_name}!${binding.cell_coordinate}`}
         onClick={() => onLocate(binding)}>
      <span className="el-fill-nav-field-state">{state}</span>
      <span className="el-fill-nav-field-name">{binding.field_name}</span>
      <span className="el-fill-nav-field-coord">{binding.cell_coordinate}</span>
    </div>
  );
}

function FillNavigator({store, onLocate, onCollapse}) {
  const cursorRef = useRef(null);
  const progress = store.fillProgress;
  const missing = store.missingRequiredBindings;
  const groups = store.bindingsBySheet;

  /** 下一个未填必填项：从上次定位项的下一项开始循环（含回卷）。 */
  function locateNextRequired() {
    if (!missing.length) return;
    const cursorIndex = missing.findIndex(b => b.field_id === cursorRef.current);
    const next = missing[(cursorIndex + 1) % missing.length];
    cursorRef.current = next.field_id;
    onLocate(next);
  }

  /** 定位任意字段后重置必填游标，避免「下一个」从陈旧位置起算。 */
  function handleLocate(binding) {
    cursorRef.current = binding.field_id;
    onLocate(binding);
  }

  const requiredPercent = progress.requiredTotal > 0
    ? Math.round(progress.requiredFilled / progress.requiredTotal * 100)
    : (progress.total > 0 ? Math.round(progress.filled / progress.total * 100) : 0);

  return (
    <div className="el-fill-nav" data-testid="fill-navigator">
      <div className="el-fill-nav-head">
        <span className="el-fill-nav-title">填写导航</span>
        <Button type="text" size="small" icon={<DoubleLeftOutlined/>}
                data-testid="fill-nav-collapse" title="收起填写导航"
                onClick={onCollapse}/>
      </div>
      <div className="el-fill-nav-progress" data-testid="fill-nav-progress">
        <div className="el-fill-nav-progress-text" data-testid="fill-nav-progress-text">
          已填 {progress.filled}/{progress.total} · 必填 {progress.requiredFilled}/{progress.requiredTotal}
        </div>
        <Progress percent={requiredPercent} size="small" status="normal"
                  showInfo={false}/>
        <Button size="small" type="primary" ghost block
                data-testid="fill-nav-next-required"
                disabled={!missing.length}
                onClick={locateNextRequired}>
          下一个未填必填项
        </Button>
      </div>
      {groups.length ? groups.map(group => (
        <div key={group.name} className="el-fill-nav-sheet">
          <div className="el-fill-nav-sheet-name">{group.name}</div>
          {group.bindings.map(binding => (
            <NavigatorField key={binding.field_id} binding={binding}
                            filled={!isUnfilled(store.values[binding.field_id])}
                            onLocate={handleLocate}/>
          ))}
        </div>
      )) : (
        <div className="el-fill-nav-empty">该模板未绑定填写字段</div>
      )}
    </div>
  );
}

export default observer(FillNavigator);
