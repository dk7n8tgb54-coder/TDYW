/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import { observable, runInAction } from 'mobx';
import { http, hasPermission } from 'libs';

const POLL_INTERVAL = 5 * 60 * 1000;

class ContractAgreementBadgeStore {
  @observable count = 0;
  @observable expiringCount = 0;
  @observable expiredCount = 0;
  @observable loaded = false;

  start = () => {
    if (!hasPermission('contract_agreement.agreement.view')) return;
    this.fetch();
    this._timer = setInterval(this.fetch, POLL_INTERVAL);
  };

  stop = () => {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  };

  fetch = () => {
    if (!hasPermission('contract_agreement.agreement.view')) return;
    http.get('/api/contract-agreement/badge/')
      .then(res => {
        const data = res && (res.data || res);
        runInAction(() => {
          this.count = data?.count ?? 0;
          this.expiringCount = data?.expiring_count ?? 0;
          this.expiredCount = data?.expired_count ?? 0;
          this.loaded = true;
        });
      })
      .catch(() => {});
  };
}

export default new ContractAgreementBadgeStore();

