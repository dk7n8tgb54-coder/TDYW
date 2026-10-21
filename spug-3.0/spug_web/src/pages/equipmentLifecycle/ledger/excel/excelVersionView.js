/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 历史版本只读查看与复制为新草稿（2026-10-21，自页面/Store 抽出的独立
 * 轻量模块，避免继续扩大 excelTemplateStore 的体量）。
 *
 * 职责边界：
 * - 只对接正式接口：GET versions/<no>/（布局+绑定+打印参数快照）、
 *   POST versions/<no>/preview/pdf/（版本自身打印预览）、
 *   GET versions/<no>/source/（版本源文件下载）、
 *   POST versions/<no>/copy-to-draft/（复制为新草稿）；
 * - 本模块不持有状态、不做乐观更新：请求失败原样向上抛出（公共 http
 *   拦截器已提示业务错误，调用方不得再重复提示、不得当成功）；
 * - 复制只替换当前草稿，历史版本与已发布版本不可变（后端独立校验）；
 * - 输入类型/打印参数展示映射集中在此，版本视图与只读清单共用。
 */
import {http} from 'libs';
import {API} from './excelTemplateStore';
import {
  ORIENTATION_OPTIONS, PAGE_ORDER_OPTIONS, PAPER_SIZE_OPTIONS,
  SCALE_MODE_OPTIONS, normalizePdfParams,
} from './pdfParams';

/** 字段输入类型展示（与 FieldPanel 的选项文案一致）。 */
export const INPUT_TYPE_LABELS = {
  text: '文本', number: '数值', choice: '单选', status: '正常/异常', date: '日期',
};

/**
 * 草稿与发布版本的关系文案（模板详情 draft_state，2026-10-21）：
 * 后端只按内容签名判定（identical/modified/unknown/no_versions/no_draft），
 * 前端不做任何时间推断——无法可靠判断时如实显示"无法确认"。
 */
export function draftRelationText(state) {
  if (!state || !state.relation) return '';
  if (state.relation === 'identical') {
    return `草稿与 v${state.based_on_version_no} 发布版本内容一致`;
  }
  if (state.relation === 'modified') {
    return `草稿基于 v${state.based_on_version_no}，之后有修改`;
  }
  if (state.relation === 'no_versions') return '尚无发布版本';
  if (state.relation === 'no_draft') return '尚无草稿源文件';
  return '草稿与发布版本来源关系无法确认';
}


/** 版本详情接口返回版本内容快照（布局/绑定/打印参数/分页计划）。 */
export async function fetchVersionContent(templateId, versionNo) {
  const res = await http.get(`${API}/${templateId}/versions/${versionNo}/`);
  return res && res.data ? res.data : res;
}

/** 版本自身打印预览（二进制 PDF 响应；响应头携带页数/纸张/预检提示）。 */
export function fetchVersionPreview(templateId, versionNo) {
  return http.post(`${API}/${templateId}/versions/${versionNo}/preview/pdf/`, null,
                   {responseType: 'arraybuffer', timeout: 180000});
}

/** 版本源文件下载地址（原生链接下载，不经 axios）。 */
export function versionSourceUrl(templateId, versionNo) {
  return `${API}/${templateId}/versions/${versionNo}/source/`;
}

/** 复制版本为新草稿：后端返回更新后的模板详情（当前草稿已被替换）。 */
export async function copyVersionToDraft(templateId, versionNo) {
  const res = await http.post(
    `${API}/${templateId}/versions/${versionNo}/copy-to-draft/`);
  return res && res.data ? res.data : res;
}

function optionText(options, value, fallback = '—') {
  const found = options.find(item => item.value === value);
  return found ? found.label : (value || fallback);
}

/**
 * 打印参数只读摘要（版本快照原值，未保存修改不参与）：
 * 返回 [{label, value}]，供版本查看抽屉以只读清单展示。
 */
export function pdfParamsSummary(raw) {
  const params = normalizePdfParams(raw);
  const margins = params.margins || {};
  return [
    {label: '打印模式', value: optionText([
      {value: 'a4_auto', label: 'A4 自动适配'},
      {value: 'original', label: '原始 Excel 打印设置'},
      {value: 'single_page', label: '单页表单'},
      {value: 'custom', label: '自定义'},
    ], params.preset)},
    {label: '纸张', value: optionText(PAPER_SIZE_OPTIONS, params.paper_size)},
    {label: '方向', value: optionText(ORIENTATION_OPTIONS, params.orientation)},
    {label: '缩放', value: params.scale_mode === 'percent'
      ? `按百分比 ${params.scale_percent}%`
      : optionText(SCALE_MODE_OPTIONS, params.scale_mode)},
    {label: '页边距（cm）', value:
      `上 ${margins.top} / 下 ${margins.bottom} / 左 ${margins.left} / 右 ${margins.right}`},
    {label: '重复表头行', value: params.repeat_header_rows || '—'},
    {label: '手动分页行', value: (params.row_breaks || []).join('、') || '—'},
    {label: '页序', value: optionText(PAGE_ORDER_OPTIONS, params.page_order)},
    {label: '打印区域', value: params.print_area || '—'},
    {label: '居中', value: [
      params.horizontal_centered ? '水平' : '', params.vertical_centered ? '垂直' : '',
    ].filter(Boolean).join('、') || '—'},
  ];
}
