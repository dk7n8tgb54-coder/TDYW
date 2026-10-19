/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 布局预览/填写预览表格（Excel/WPS 维护台账路线共享组件，2026-10-01
 * 自模板导入验证原型迁出为 Excel 专属公共组件）。
 *
 * 由服务端解析的布局 JSON 渲染：合并单元格（colSpan/rowSpan）、行高、
 * 列宽、边框、背景与字体（含下划线/删除线）等基本样式；隐藏行/列以
 * 零宽收起（保持坐标网格与跨行列合并完整）。设计绑定模式下标记已绑定
 * 单元格，填写预览模式下在绑定单元格内渲染 antd 输入控件（选项=Select、
 * 填空=Input，控件风格与巡检中心一致；宽度撑满单元格以保持 Excel 版式）。
 * 文本填写格的纵向空间达到两行默认行高（跨行合并或显式大行高，横向
 * 合并不算高度）时改用多行文本域填满单元格；控件绝对定位，不参与行高
 * 计算，不撑乱表格版式。不做 Excel 完整复刻，以确认合并关系与布局还原
 * 为准；最终打印效果以导出 Excel/PDF 为准。
 *
 * 多选（批量绑定）：传入 selectedCells 渲染选区高亮；onSelectCell 追加
 * event 参数供父级识别 Ctrl/Cmd 加选；onCellMouseDown/onCellMouseEnter
 * 供父级实现拖拽矩形选区（本组件只上报事件，不持有选区状态）。
 * preventTextSelect（2026-10-19）：拖拽矩形选区进行中由父级传入 true，
 * 表格外层容器加 proto-drag-selecting 类并内联 user-select:none，阻止
 * 浏览器把表格文字选中；仅模板编辑模式启用，填写/历史视图与松开后的
 * 正常复制不受影响。
 *
 * 填写工作区扩展（2026-10-19）：
 * - scale：网页显示缩放（乘在列宽/行高/填写区像素上，等比缩放不改变
 *   单元格相对尺寸与合并关系；缺省 1 = 既有原始尺寸，模板工作台不受影响）；
 * - locate：{coordinate, nonce} 变化时把目标单元格滚动到可视区域并短暂
 *   高亮，可编辑（fillMode 且非 readOnly）时聚焦格内输入控件；合并格
 *   传锚点坐标（绑定只允许锚点，锚点即实际填写区域）；
 * - tableRef：父级测量表格自然宽度（显示模式计算）用的转发挂点。
 */
import React from 'react';
import {Input, Select} from 'antd';

import {
  TALL_FILL_THRESHOLD_PT, colLetter, coordName, effectiveFillHeightPt,
  effectiveFillHeightPx, parseCoord,
} from '../utils';

// 坐标解析纯函数下沉到 ../utils（2026-10-14，供几何计算共用）；
// 这里原样再导出，保持既有导入路径（excelTemplateStore 等）不变。
export {colLetter, parseCoord, coordName};

/** 定位高亮时长（ms）：与 proto-cell-locate 动画时长一致。 */
const LOCATE_FLASH_MS = 1800;

/** 解析合并区域：anchors[锚点] = {rowSpan, colSpan}；covered[覆盖格] = 锚点 */
export function buildMergeInfo(ranges) {
  const anchors = {};
  const covered = {};
  (ranges || []).forEach(range => {
    const parts = String(range).split(':');
    const start = parseCoord(parts[0]);
    const end = parseCoord(parts[1] || parts[0]);
    anchors[parts[0].toUpperCase()] = {rowSpan: end.row - start.row + 1, colSpan: end.col - start.col + 1};
    for (let row = start.row; row <= end.row; row++) {
      for (let col = start.col; col <= end.col; col++) {
        if (row === start.row && col === start.col) continue;
        covered[coordName(row, col)] = parts[0].toUpperCase();
      }
    }
  });
  return {anchors, covered};
}

/** 合并/内容规则的前端镜像：返回不可绑定原因，可绑定返回 null */
export function bindBlockReason(sheet, coordinate) {
  if (!sheet || !coordinate) return null;
  const {covered} = buildMergeInfo(sheet.merged_ranges);
  if (covered[coordinate]) {
    return `该单元格在合并区域内部，只能绑定左上角单元格 ${covered[coordinate]}`;
  }
  const cell = sheet.cells && sheet.cells[coordinate];
  if (cell && cell.v !== null && cell.v !== undefined && cell.v !== '') {
    return '单元格已有内容（标题/表头等），不能绑定为填写字段';
  }
  return null;
}

function toCssColor(rgb) {
  if (!rgb || typeof rgb !== 'string') return null;
  if (/^[0-9A-Fa-f]{8}$/.test(rgb)) return '#' + rgb.slice(2);
  if (/^[0-9A-Fa-f]{6}$/.test(rgb)) return '#' + rgb;
  return null;
}

function cellCss(style) {
  const css = {};
  if (!style) {
    // 无样式单元格同样按 pre 保留空白（样式缺失不代表可以折叠空格）
    css.whiteSpace = 'pre';
    return css;
  }
  if (style.font) {
    if (style.font.bold) css.fontWeight = 'bold';
    if (style.font.italic) css.fontStyle = 'italic';
    if (style.font.size) css.fontSize = `${style.font.size}pt`;
    const decorations = [];
    if (style.font.underline) decorations.push('underline');
    if (style.font.strike) decorations.push('line-through');
    if (decorations.length) css.textDecoration = decorations.join(' ');
    const color = toCssColor(style.font.color);
    if (color) css.color = color;
  }
  const fill = toCssColor(style.fill);
  if (fill) css.background = fill;
  if (style.align) {
    if (style.align.h) css.textAlign = style.align.h;
    if (style.align.v) css.verticalAlign = style.align.v;
    // 空白保真：无论是否开启换行都按 white-space 保留连续空格/首尾空格/
    // 换行（浏览器默认 normal 会折叠，导致「温 度」「年 月 日」类模板
    // 文本的填写留空线在预览中消失）；wrap 单元格自动换行 + 长词断行，
    // 非 wrap 单元格保持单行由 overflow hidden 裁剪（与 Excel 显示一致，
    // 行高稳定不跳动）
    if (style.align.wrap) {
      css.whiteSpace = 'pre-wrap';
      css.wordBreak = 'break-word';
    } else {
      css.whiteSpace = 'pre';
    }
  } else {
    css.whiteSpace = 'pre';
  }
  const border = style.border || {};
  ['top', 'bottom', 'left', 'right'].forEach(side => {
    const borderStyle = border[side];
    if (borderStyle) {
      const color = toCssColor(borderStyle.color) || '#000000';
      css[`border${side[0].toUpperCase()}${side.slice(1)}`] = `1px solid ${color}`;
    }
  });
  return css;
}

/**
 * 绑定单元格填写控件（风格对齐巡检中心 WorksheetCards 的 ValueControl）：
 * 正常/异常与单选用 antd Select（allowClear + 占位提示），文本/数值/日期
 * 用 antd Input；宽度一律撑满单元格，保持 Excel 解析出的列宽版式不被
 * 固定控件宽度撑破（巡检中心列宽充裕用固定宽度，本表为版式回放）。
 * 文本类型且纵向空间足够（tallFill，含 px 高度 fillHeightPx）时改用
 * 多行文本域：绝对定位填满单元格（不含内边距），与模板合并区域/行高
 * 尺寸相符；不参与行高计算，行高稳定的版式不被控件撑乱。
 */
function CellInput({binding, value, onValueChange, tallFill, fillHeightPx}) {
  const raw = value === undefined || value === null ? '' : String(value);
  const handleChange = event => onValueChange(binding.field_id, event.target.value);
  if (binding.input_type === 'status' || binding.input_type === 'choice') {
    const options = binding.input_type === 'status'
      ? ['正常', '异常'] : (binding.options || []);
    return (
      <Select size="small" allowClear style={{width: '100%'}}
              className="proto-cell-select" data-field={binding.field_name}
              placeholder={binding.input_type === 'status' ? '正常 / 异常' : '请选择'}
              value={raw === '' ? undefined : raw}
              onChange={next => onValueChange(binding.field_id, next || '')}>
        {options.map(option => (
          <Select.Option key={option} value={option}>{option}</Select.Option>
        ))}
      </Select>
    );
  }
  if (binding.input_type === 'text' && tallFill) {
    return (
      <Input.TextArea
        className="proto-cell-input proto-cell-textarea"
        data-field={binding.field_name}
        placeholder="请输入"
        value={raw}
        onChange={handleChange}
        style={{position: 'absolute', top: 2, left: 4, right: 4,
                height: Math.max(fillHeightPx - 4, 24), resize: 'none'}}/>
    );
  }
  const type = binding.input_type === 'number' ? 'number'
    : (binding.input_type === 'date' ? 'date' : 'text');
  return (
    <Input size="small" style={{width: '100%'}} type={type}
           className="proto-cell-input" data-field={binding.field_name}
           placeholder="请输入" value={raw} onChange={handleChange}/>
  );
}

export default class LayoutTable extends React.Component {
  wrapRef = React.createRef();
  locateTimer = null;

  componentDidMount() {
    this._locateTargetCell();
  }

  componentDidUpdate(prevProps) {
    const prev = prevProps.locate;
    const next = this.props.locate;
    if (next && next.coordinate && (!prev || prev.nonce !== next.nonce)) {
      this._locateTargetCell();
    }
  }

  componentWillUnmount() {
    if (this.locateTimer) clearTimeout(this.locateTimer);
  }

  /** 定位目标格：滚动进入可视区域 + 短暂高亮 + 可编辑时聚焦输入控件。
   * 缩放按真实布局尺寸生效（非 transform），滚动与聚焦坐标天然准确；
   * 合并格只可能是锚点（绑定校验保证），即实际填写区域。 */
  _locateTargetCell() {
    const locate = this.props.locate;
    const wrap = this.wrapRef.current;
    if (!locate || !locate.coordinate || !wrap) return;
    const td = wrap.querySelector(`td[data-coord="${locate.coordinate}"]`);
    if (!td) return;
    if (typeof td.scrollIntoView === 'function') {
      try {
        td.scrollIntoView({block: 'center', inline: 'center'});
      } catch (e) {
        td.scrollIntoView();
      }
    }
    // 重复定位同一格也要重新闪一次：先移除再强制重排重启动画
    td.classList.remove('proto-cell-locate');
    void td.offsetWidth;
    td.classList.add('proto-cell-locate');
    if (this.locateTimer) clearTimeout(this.locateTimer);
    this.locateTimer = setTimeout(() => {
      td.classList.remove('proto-cell-locate');
    }, LOCATE_FLASH_MS);
    if (this.props.fillMode && !this.props.readOnly) {
      const input = td.querySelector('input, textarea');
      if (input && typeof input.focus === 'function') {
        try {
          input.focus({preventScroll: true});
        } catch (e) {
          input.focus();
        }
      }
    }
  }

  /** 网页显示缩放（缺省 1；乘在布局像素上，等比不改变相对尺寸）。 */
  _displayScale() {
    const scale = Number(this.props.scale);
    return Number.isFinite(scale) && scale > 0 ? scale : 1;
  }

  render() {
    const {sheet} = this.props;
    if (!sheet) return null;
    const scale = this._displayScale();
    const {anchors, covered} = buildMergeInfo(sheet.merged_ranges);
    const hiddenColumns = sheet.hidden_columns || [];
    const hiddenRows = sheet.hidden_rows || [];
    // 隐藏列/行用零宽渲染而非移除：保持坐标网格完整，rowSpan/colSpan
    // 跨隐藏行列的合并不塌陷（与 Excel 打印行为一致）
    const colHidden = {};
    hiddenColumns.forEach(letter => {
      colHidden[letter] = true;
    });
    const columns = [];
    for (let col = 1; col <= sheet.max_column; col++) {
      const letter = colLetter(col);
      const width = (sheet.column_widths || {})[letter];
      columns.push(
        <col key={letter}
             style={{width: colHidden[letter]
               ? 0 : Math.round((width || 8.43) * 7 + 5) * scale}}/>);
    }
    const rows = [];
    for (let row = 1; row <= sheet.max_row; row++) {
      const height = (sheet.row_heights || {})[String(row)];
      const rowHidden = hiddenRows.indexOf(String(row)) !== -1;
      rows.push(this._renderRow(row, rowHidden ? 0 : height, anchors, covered,
        rowHidden, colHidden, scale));
    }
    // 拖拽矩形选区进行中：阻止浏览器把表格文字选中（内联样式 +
    // proto-drag-selecting 类，仅模板编辑模式由父级传入）
    const preventTextSelect = !!this.props.preventTextSelect;
    const wrapStyle = {overflow: 'auto'};
    if (preventTextSelect) {
      wrapStyle.userSelect = 'none';
      wrapStyle.WebkitUserSelect = 'none';
    }
    return (
      <div ref={this.wrapRef}
           className={preventTextSelect
             ? 'proto-table-wrap proto-drag-selecting' : 'proto-table-wrap'}
           style={wrapStyle}>
        <table ref={this.props.tableRef}
               className="proto-table" style={{borderCollapse: 'collapse', tableLayout: 'fixed'}}>
          <colgroup>{columns}</colgroup>
          <tbody>{rows}</tbody>
        </table>
      </div>
    );
  }

  _renderRow(row, height, anchors, covered, rowHidden, colHidden, scale) {
    const cells = [];
    for (let col = 1; col <= this.props.sheet.max_column; col++) {
      const coordinate = coordName(row, col);
      if (covered[coordinate]) continue;
      cells.push(this._renderCell(row, col, coordinate, anchors,
        rowHidden || colHidden[colLetter(col)], scale));
    }
    return (
      <tr key={row} style={{height: Math.round((height || 14.25) * 4 / 3) * scale,
        lineHeight: rowHidden ? 0 : undefined}}>
        {cells}
      </tr>
    );
  }

  _renderCell(row, col, coordinate, anchors, collapsed, scale) {
    const {sheet, bindingByCell, fillMode, selectedCell, selectedCells, values, readOnly} = this.props;
    const cell = (sheet.cells || {})[coordinate];
    const text = cell && cell.v !== null && cell.v !== undefined ? String(cell.v) : '';
    const binding = bindingByCell[`${sheet.name}!${coordinate}`] || null;
    const merge = anchors[coordinate];
    const css = cellCss(cell && cell.s);
    css.position = 'relative';
    css.padding = '2px 4px';
    css.overflow = 'hidden';
    // 隐藏行/列内格子随行列一起收起（保留边框所占的极小宽度）
    if (collapsed) {
      css.padding = 0;
      css.fontSize = 0;
    }
    const classNames = ['proto-cell'];
    if (binding) classNames.push(fillMode ? 'proto-cell-filling' : 'proto-cell-bound');
    // 单击选中（selectedCell）与拖拽/Ctrl 批量选区（selectedCells）显示
    // 同样的蓝框：selectedCell 此前只加无样式的 class，单击没有任何
    // 视觉反馈
    const singleSelected = selectedCell === coordinate;
    if (singleSelected) classNames.push('proto-cell-selected');
    const inSelection = (selectedCells || []).indexOf(coordinate) !== -1;
    if (inSelection || singleSelected) {
      classNames.push('proto-cell-in-selection');
      css.boxShadow = 'inset 0 0 0 2px #1890ff';
    }
    if (fillMode && !readOnly && binding && binding.is_required && (values[binding.field_id] === undefined
      || values[binding.field_id] === null || values[binding.field_id] === '')) {
      classNames.push('proto-cell-missing-required');
    }
    // onSelectCell 为可选回调：填写/历史视图不需要选格行为，缺省时点击无副作用；
    // event 透传给父级识别 Ctrl/Cmd 加选
    const handleSelect = event => {
      if (this.props.onSelectCell) this.props.onSelectCell(coordinate, event);
    };
    // 拖拽矩形选区：mousedown 记录起点、mouseenter 扩展选区，由父级实现
    const handleMouseDown = event => {
      if (this.props.onCellMouseDown) this.props.onCellMouseDown(coordinate, event);
    };
    const handleMouseEnter = () => {
      if (this.props.onCellMouseEnter) this.props.onCellMouseEnter(coordinate);
    };
    // 填写模式下绑定格渲染输入控件；readOnly（历史回放）只读展示填写值
    const fillValue = fillMode && binding ? values[binding.field_id] : undefined;
    const displayText = fillMode && binding
      ? (fillValue === undefined || fillValue === null ? '' : String(fillValue))
      : text;
    // 文本填写格纵向空间足够（跨行合并或显式大行高；横向合并不算高度）
    // 时改用多行文本域填满单元格，与模板中的填写区域尺寸相符
    const tallFill = !!(fillMode && binding && !readOnly
      && binding.input_type === 'text'
      && effectiveFillHeightPt(sheet, coordinate) >= TALL_FILL_THRESHOLD_PT);
    // 文本域按缩放后的填写区高度绝对定位（保持填满单元格）
    const fillHeightPx = tallFill ? effectiveFillHeightPx(sheet, coordinate) * scale : 0;
    return (
      <td key={coordinate}
          className={classNames.join(' ')}
          style={css}
          colSpan={merge ? merge.colSpan : undefined}
          rowSpan={merge ? merge.rowSpan : undefined}
          onClick={handleSelect}
          onMouseDown={handleMouseDown}
          onMouseEnter={handleMouseEnter}
          data-coord={coordinate}>
        {fillMode && binding && !readOnly
          ? <CellInput binding={binding} value={fillValue}
                       tallFill={tallFill} fillHeightPx={fillHeightPx}
                       onValueChange={this.props.onValueChange}/>
          : displayText}
        {!fillMode && binding && (
          <span className="proto-binding-mark"
                title={`已绑定：${binding.field_name}（${coordinate}）`}/>
        )}
        {fillMode && binding && binding.is_required && !readOnly && (
          <span className="proto-required-mark"
                style={tallFill ? {position: 'absolute', top: 2, right: 6, zIndex: 1} : undefined}>
            *
          </span>
        )}
      </td>
    );
  }
}
