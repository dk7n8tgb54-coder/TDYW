/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable } from "mobx";
import { http } from 'libs';

class Store {
  @observable totalCount = 0;
  @observable monthCount = 0;
  @observable handledCount = 0;
  @observable handleRate = 0;
  @observable frequencyStats = [];
  @observable typeStats = [];
  @observable isFetching = false;
  @observable dateRange = null;

  setDateRange = (dates) => {
    this.dateRange = dates;
    // 如果选择了日期，立即获取数据
    if (dates && dates.length === 2) {
      this.fetchStatistics();
    } else if (!dates) {
      // 清空日期范围时，重新获取数据（使用默认本月）
      this.fetchStatistics();
    }
  };

  fetchStatistics = () => {
    this.isFetching = true;
    const params = {};
    if (this.dateRange && this.dateRange.length === 2 && this.dateRange[0] && this.dateRange[1]) {
      params.start_date = this.dateRange[0].format('YYYY-MM-DD');
      params.end_date = this.dateRange[1].format('YYYY-MM-DD');
    }
    http.get('/api/interference/statistics/', { params })
      .then(data => {
        this.frequencyStats = data.frequency_stats || [];
        this.typeStats = data.type_stats || [];
        this.totalCount = data.total_count || 0;
        this.monthCount = data.month_count || 0;
      })
      .catch(error => {
        console.error('[statisticsStore] 获取统计数据失败:', error);
      })
      .finally(() => this.isFetching = false);
  };
}

export default new Store()
