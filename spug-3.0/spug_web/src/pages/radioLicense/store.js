/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http, syncAttachmentCount } from 'libs';

class Store {
  // ========== 数据列表 ==========
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable pageNum = 1;
  @observable pageSize = 20;

  // ========== 表单弹窗 ==========
  @observable formVisible = false;
  @observable detailVisible = false;
  @observable record = {};

  // ========== 筛选条件 ==========
  @observable f_station_name = undefined;
  @observable f_purpose = undefined;
  @observable f_status = undefined;
  @observable f_valid_to_range = undefined;

  // ========== 状态选项 ==========
  statusOptions = [
    {value: 'normal', label: '正常'},
    {value: 'expiring', label: '即将到期'},
    {value: 'expired', label: '已过期'},
  ];

  // ========== 频率单位选项 ==========
  frequencyUnitOptions = [
    {value: 'MHz', label: 'MHz'},
    {value: 'kHz', label: 'kHz'},
    {value: 'GHz', label: 'GHz'},
  ];

  // ========== 可选责任人列表 ==========
  @observable responsibleUsers = [];
  @observable responsibleUsersLoaded = false;
  // 拉取责任人列表时使用的登录 token（非响应式，仅作缓存指纹）
  _responsibleUsersToken = null;

  // ========== 请求生命周期守卫 ==========
  // 请求序列号：每次 fetchRecords 单调递增，只有最新请求可写入列表状态，
  // 防止用户快速切换筛选/分页时旧请求响应覆盖新请求结果
  _fetchSeq = 0;
  // 页面组件挂载标记：组件卸载后异步回调不得继续写入页面状态
  // （store 为模块级单例，由 Table 组件挂载/卸载时调用 setActive 切换）
  _active = true;

  setActive = (active) => {
    this._active = active;
  };

  fetchRecords = () => {
    const seq = ++this._fetchSeq;
    const requestedPage = this.pageNum;
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize,
    };
    if (this.f_station_name) params.station_name = this.f_station_name;
    if (this.f_purpose) params.purpose = this.f_purpose;
    if (this.f_status) params.status = this.f_status;
    if (this.f_valid_to_range && this.f_valid_to_range.length === 2) {
      params.valid_to_start = this.f_valid_to_range[0];
      params.valid_to_end = this.f_valid_to_range[1];
    }

    return http.get('/api/radio-license/', { params })
      .then(({records, total, page, page_size}) => {
        // 旧请求响应或组件已卸载：不得写入页面状态
        if (seq !== this._fetchSeq || !this._active) return undefined;
        const rows = records || [];
        // 空页回退：删除最后一页最后一条记录后当前页为空，
        // 回退到上一页重新拉取（真实后端此时会返回有数据的页）
        if (rows.length === 0 && requestedPage > 1) {
          this.pageNum = requestedPage - 1;
          return this.fetchRecords();
        }
        this.records = rows;
        this.total = total || 0;
        this.pageNum = page || requestedPage;
        this.pageSize = page_size || this.pageSize;
        return {records: rows, total, page, page_size};
      })
      .catch(e => {
        console.error('[电台执照] 获取列表失败:', e);
      })
      .finally(() => {
        // 仅最新请求有权复位 loading，避免旧请求提前关闭新请求的加载态
        if (seq === this._fetchSeq && this._active) this.isFetching = false;
      })
  };

  // 拉取可选责任人列表（懒加载，首次进入表单时调用）。
  // 本 store 为模块级单例，同一浏览器切换账号（登出不刷新页面）后仍在内存，
  // 记录拉取时的登录 token，token 变化即强制重拉，避免残留上一账号租户的责任人。
  fetchResponsibleUsers = () => {
    const token = sessionStorage.getItem('token');
    if (this.responsibleUsersLoaded && token === this._responsibleUsersToken) {
      return Promise.resolve(this.responsibleUsers);
    }
    return http.get('/api/radio-license/responsible-users/')
      .then(res => {
        this.responsibleUsers = res || [];
        this.responsibleUsersLoaded = true;
        this._responsibleUsersToken = token;
        return this.responsibleUsers;
      })
      .catch(e => {
        console.error('[电台执照] 获取责任人列表失败:', e);
        return [];
      });
  };

  // 附件数量变化（上传/删除）时实时回写列表行与当前记录，无需刷新页面
  updateAttachmentCount = (id, count) => syncAttachmentCount(this, id, count);

  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = {...info};
  };

  showDetail = (info = {}) => {
    this.detailVisible = true;
    this.record = {...info};
  };
}

export default new Store()
