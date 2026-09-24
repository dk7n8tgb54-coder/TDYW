/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——值班巡检 Store（今日巡检改造）。
 * 错误提示统一由 http 拦截器弹出；巡检单不关联系统，
 * 转换目标系统由用户在转换弹窗中选择并经后端校验。
 */
import {observable, action} from 'mobx';
import moment from 'moment';
import {http} from 'libs';
import {API_PREFIX} from './constants';

// 巡检单记录页默认值班日期范围：最近 30 个自然日（含今天，即今天往前 29 天 → 今天）
export function defaultDutyRange() {
  return [moment().subtract(29, 'days'), moment()];
}

class InspectionStore {
  @observable templates = [];      // 可用模板树（设备 → 检查内容）
  @observable users = [];          // 本租户有效账号（值班人员候选）
  @observable systems = [];        // 转换弹窗目标系统候选（复用工单候选系统接口）
  @observable records = [];        // 巡检单列表
  @observable total = 0;
  @observable page = 1;
  @observable pageSize = 10;
  @observable isFetching = false;
  @observable detail = null;       // 巡检单详情（含 persons/records/disposition）
  @observable isDetailFetching = false;
  @observable submitting = false;
  @observable converting = false;

  @action fetchTemplates = () => {
    return http.get(`${API_PREFIX}/inspection-templates/available/`)
      .then(action(res => {this.templates = res.data || [];}));
  };

  @action fetchUsers = () => {
    // 复用工单候选账号接口：本租户有效账户（含 nickname）；
    // 值班人员已不选择账号，账号表仅用于历史草稿中账号值的姓名映射与回显
    return http.get(`${API_PREFIX}/work-orders/candidate-users/`)
      .then(action(res => {this.users = res.data || [];}));
  };

  @action fetchSystems = () => {
    // 巡检转单专用候选系统（inspection.view 即可获取，不依赖 fault/work_order 权限）
    return http.get(`${API_PREFIX}/inspection-sheets/candidate-systems/`)
      .then(action(res => {this.systems = res.data || [];}));
  };

  @action fetchSheets = (params = {}) => {
    this.isFetching = true;
    return http.get(`${API_PREFIX}/inspection-sheets/`, {params})
      .then(action(res => {
        this.records = res.data;
        this.total = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {this.isFetching = false;}));
  };

  // 注意：libs/http 拦截器对单对象响应（json_response(obj)）直接 resolve 载荷本体，
  // 只有列表响应（json_response({'data': rows, 'total': N})）才需要取 res.data。
  @action fetchSheet = (id) => {
    this.isDetailFetching = true;
    return http.get(`${API_PREFIX}/inspection-sheets/${id}/`)
      .then(action(res => {this.detail = res;}))
      .catch(action(() => {}))
      .finally(action(() => {this.isDetailFetching = false;}));
  };

  @action createSheet = (payload) => {
    return http.post(`${API_PREFIX}/inspection-sheets/`, payload)
      .then(action(res => {
        this.detail = res;
        return res;
      }));
  };

  @action saveSheet = (id, payload) => {
    return http.put(`${API_PREFIX}/inspection-sheets/${id}/`, payload)
      .then(action(res => {
        this.detail = res;
        return res;
      }));
  };

  @action submitSheet = (id) => {
    this.submitting = true;
    return http.post(`${API_PREFIX}/inspection-sheets/${id}/submit/`, {})
      .then(action(res => {
        this.detail = res;
        return res;
      }))
      .finally(action(() => {this.submitting = false;}));
  };

  @action voidSheet = (id, voidReason) => {
    return http.post(`${API_PREFIX}/inspection-sheets/${id}/void/`,
      {void_reason: voidReason})
      .then(action(res => {
        this.detail = res;
        return res;
      }));
  };

  @action convertToFault = (sheetId, recordId, payload) => {
    this.converting = true;
    return http.post(
      `${API_PREFIX}/inspection-sheets/${sheetId}/records/${recordId}/convert-to-fault/`,
      payload)
      .then(action(res => {return res;}))
      .finally(action(() => {this.converting = false;}));
  };

  @action convertToWorkOrder = (sheetId, recordId, payload) => {
    this.converting = true;
    return http.post(
      `${API_PREFIX}/inspection-sheets/${sheetId}/records/${recordId}/convert-to-work-order/`,
      payload)
      .then(action(res => {return res;}))
      .finally(action(() => {this.converting = false;}));
  };

  @action resetDetail = () => {this.detail = null;};

  // —— 巡检单记录查询（列表页） ——

  @observable browseRecords = [];
  @observable browseTotal = 0;
  @observable browsePage = 1;
  @observable browsePageSize = 10;
  @observable isBrowseFetching = false;
  @observable browseVisible = false;   // 详情抽屉
  @observable f_duty_range = defaultDutyRange();  // 默认最近 30 个自然日（含今天）
  @observable f_status = undefined;
  @observable f_keyword = undefined;

  @action fetchBrowse = (params = {}) => {
    this.isBrowseFetching = true;
    return http.get(`${API_PREFIX}/inspection-sheets/`, {params})
      .then(action(res => {
        this.browseRecords = res.data;
        this.browseTotal = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {this.isBrowseFetching = false;}));
  };

  @action openBrowseDetail = (id) => {
    this.browseVisible = true;
    return this.fetchSheet(id);
  };

  @action closeBrowseDetail = () => {
    this.browseVisible = false;
    this.detail = null;
  };

  // —— 巡检模板管理（模板 → 设备名称 → 检查内容） ——

  @observable templateRecords = [];
  @observable templateTotal = 0;
  @observable isTplFetching = false;
  @observable tplFormVisible = false;
  @observable tplRecord = null;      // 编辑中的模板（null = 新增）

  @action fetchTplList = (params = {}) => {
    this.isTplFetching = true;
    return http.get(`${API_PREFIX}/inspection-templates/`, {params})
      .then(action(res => {
        this.templateRecords = res.data;
        this.templateTotal = res.total;
      }))
      .catch(action(() => {}))
      .finally(action(() => {this.isTplFetching = false;}));
  };

  @action fetchTplDetail = (id) => {
    return http.get(`${API_PREFIX}/inspection-templates/${id}/`)
      .then(res => res);
  };

  @action saveTpl = (payload, id) => {
    const req = id
      ? http.put(`${API_PREFIX}/inspection-templates/${id}/`, payload)
      : http.post(`${API_PREFIX}/inspection-templates/`, payload);
    return req.then(res => res);
  };

  @action toggleTpl = (id, is_active) => {
    return http.put(`${API_PREFIX}/inspection-templates/${id}/active/`, {is_active});
  };

  @action deleteTpl = (id) => {
    return http.delete(`${API_PREFIX}/inspection-templates/${id}/`);
  };
}

const store = new InspectionStore();
export default store;
