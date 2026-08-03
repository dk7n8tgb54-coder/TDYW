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

class Store {
  // 当前激活的 Tab
  @observable activeTab = 'overview';

  // 日期范围（默认最近 365 天）
  @observable dateRange = [
    moment().subtract(364, 'days'),
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
