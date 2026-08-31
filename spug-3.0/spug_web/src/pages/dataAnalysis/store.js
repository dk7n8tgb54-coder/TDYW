/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import moment from 'moment';

// Tab 配置：key -> { label, perm, endpoint }
export const TABS = [
  { key: 'overview', label: '总览分析', perm: 'data_analysis.overview.view', endpoint: '/api/data-analysis/overview/' },
  { key: 'fault', label: '故障分析', perm: 'data_analysis.fault.view', endpoint: '/api/data-analysis/fault/' },
  { key: 'interference', label: '干扰分析', perm: 'data_analysis.interference.view', endpoint: '/api/data-analysis/interference/' },
  { key: 'device', label: '设备分析', perm: 'data_analysis.device.view', endpoint: '/api/data-analysis/device/' },
  { key: 'upgrade', label: '升级分析', perm: 'data_analysis.upgrade.view', endpoint: '/api/data-analysis/upgrade/' },
];

// 日期范围常量（与后端 apps/data_analysis/services/common.py 保持一致）
export const DEFAULT_RANGE_DAYS = 365;
export const MAX_RANGE_DAYS = 1826; // 约 5 年，含起止日

// 快捷区间选项，每次调用重新计算，避免页面长期打开后日期不更新
export const getDatePresets = () => ({
  '近半年': [moment().subtract(182, 'days'), moment()],
  '近一年': [moment().subtract(DEFAULT_RANGE_DAYS - 1, 'days'), moment()],
  '近两年': [moment().subtract(730, 'days'), moment()],
  '近三年': [moment().subtract(1095, 'days'), moment()],
  '近五年': [moment().subtract(MAX_RANGE_DAYS - 1, 'days'), moment()],
});

class Store {
  // 当前激活的 Tab
  @observable activeTab = 'overview';

  // 日期范围（默认最近 365 天）
  @observable dateRange = [
    moment().subtract(DEFAULT_RANGE_DAYS - 1, 'days'),
    moment(),
  ];

  // 每个 Tab 的独立状态
  @observable tabData = {};
  @observable tabFetching = {};
  @observable tabError = {};

  @action setActiveTab = (key) => {
    this.activeTab = key;
  };

  @action setDateRange = (range) => {
    this.dateRange = range;
  };

  @action fetchTab = (tabKey) => {
    const tab = TABS.find(t => t.key === tabKey);
    if (!tab) return;

    this.tabFetching[tabKey] = true;
    this.tabError[tabKey] = null;

    const params = {};
    if (this.dateRange && this.dateRange.length === 2) {
      params.start_date = this.dateRange[0].format('YYYY-MM-DD');
      params.end_date = this.dateRange[1].format('YYYY-MM-DD');
    }

    return http.get(tab.endpoint, { params })
      .then(res => {
        this.tabData[tabKey] = res;
        this.tabError[tabKey] = null;
      })
      .catch(err => {
        this.tabError[tabKey] = err.message || '数据加载失败';
      })
      .finally(() => {
        this.tabFetching[tabKey] = false;
      });
  };

  // 获取某个 Tab 的数据
  getData = (tabKey) => this.tabData[tabKey];
  isFetching = (tabKey) => !!this.tabFetching[tabKey];
  getError = (tabKey) => this.tabError[tabKey] || null;
}

export default new Store();
