/**
 * 台站频率批复 MobX Store。
 *
 * 设计方案第九节：
 * - 列表 / 分页 / 筛选（文件名称、文件编号、状态、截止日期范围）
 * - 责任人懒加载
 * - 表单 / 详情状态切换
 * - 深链 ?id= 加载详情
 */
import { observable } from 'mobx';
import { http, syncAttachmentCount } from 'libs';

class Store {
  // ========== 列表数据 ==========
  @observable records = [];
  @observable isFetching = false;
  @observable total = 0;
  @observable pageNum = 1;
  @observable pageSize = 20;

  // ========== 弹窗状态 ==========
  @observable formVisible = false;
  @observable detailVisible = false;
  @observable record = {};

  // ========== 筛选条件 ==========
  @observable f_name = undefined;
  @observable f_doc_no = undefined;
  @observable f_status = undefined;
  @observable f_valid_to_range = undefined;

  // ========== 状态选项（与后端 StationFrequencyApproval.STATUS_CHOICES 对齐）==========
  statusOptions = [
    { value: 'normal', label: '正常' },
    { value: 'expiring', label: '即将到期' },
    { value: 'expired', label: '已过期' },
  ];

  // ========== 可选责任人 ==========
  @observable responsibleUsers = [];
  @observable responsibleUsersLoaded = false;
  // 拉取责任人列表时使用的登录 token（非响应式，仅作缓存指纹）
  _responsibleUsersToken = null;

  fetchRecords = () => {
    this.isFetching = true;
    const params = {
      page: this.pageNum,
      page_size: this.pageSize,
    };
    if (this.f_name) params.name = this.f_name;
    if (this.f_doc_no) params.doc_no = this.f_doc_no;
    if (this.f_status) params.status = this.f_status;
    if (this.f_valid_to_range && this.f_valid_to_range.length === 2) {
      params.valid_to_start = this.f_valid_to_range[0];
      params.valid_to_end = this.f_valid_to_range[1];
    }

    http.get('/api/radio-license/approvals/', { params })
      .then(({ records, total, page, page_size }) => {
        this.records = records || [];
        this.total = total || 0;
        this.pageNum = page || this.pageNum;
        this.pageSize = page_size || this.pageSize;
      })
      .catch(e => {
        console.error('[台站频率批复] 获取列表失败:', e);
      })
      .finally(() => { this.isFetching = false; });
  };

  /**
   * 拉取可选责任人列表（懒加载，首次进入表单时调用）。
   * 后端只返回当前租户内启用且未删除的用户。
   * 本 store 为模块级单例，同一浏览器切换账号（登出不刷新页面）后仍在内存，
   * 记录拉取时的登录 token，token 变化即强制重拉，避免残留上一账号租户的责任人。
   */
  fetchResponsibleUsers = () => {
    const token = sessionStorage.getItem('token');
    if (this.responsibleUsersLoaded && token === this._responsibleUsersToken) {
      return Promise.resolve(this.responsibleUsers);
    }
    return http.get('/api/radio-license/approvals/responsible-users/')
      .then(res => {
        this.responsibleUsers = res || [];
        this.responsibleUsersLoaded = true;
        this._responsibleUsersToken = token;
        return this.responsibleUsers;
      })
      .catch(e => {
        console.error('[台站频率批复] 获取责任人列表失败:', e);
        return [];
      });
  };

  /**
   * 深链 ?id=xxx 加载详情。
   * 失败时静默，避免阻断列表渲染。
   */
  loadDetail = (id) => {
    return http.get(`/api/radio-license/approvals/${id}/`)
      .then(data => {
        this.record = data || {};
        return this.record;
      });
  };

  // 附件数量变化（上传/删除）时实时回写列表行与当前记录，无需刷新页面
  updateAttachmentCount = (id, count) => syncAttachmentCount(this, id, count);

  showForm = (info = {}) => {
    this.formVisible = true;
    this.record = { ...info };
  };

  showDetail = (info = {}) => {
    this.detailVisible = true;
    this.record = { ...info };
  };
}

export default new Store();
