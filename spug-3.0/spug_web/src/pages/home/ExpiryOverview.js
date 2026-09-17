/**
 * 首页到期提醒概览。
 *
 * 2026-09 第一轮改造：台站频率批复取消主动提醒，
 * 不再请求 /api/radio-license/approvals/badge/，统计只含执照与合同协议。
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Tag } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { http, history, hasPermission } from 'libs';

function ExpiryOverview() {
  const [fetching, setFetching] = useState(true);
  const [licenseData, setLicenseData] = useState(null);
  const [contractData, setContractData] = useState(null);
  const [licenseError, setLicenseError] = useState(false);
  const [contractError, setContractError] = useState(false);

  const canViewLicense = hasPermission('radio_license.license.view');
  const canViewContract = hasPermission('contract_agreement.agreement.view');
  const hasAnyPermission = canViewLicense || canViewContract;

  useEffect(() => {
    if (!hasAnyPermission) {
      setFetching(false);
      return;
    }

    let cancelled = false;
    let pending = 0;
    const onDone = () => {
      pending--;
      if (pending <= 0 && !cancelled) setFetching(false);
    };

    if (canViewLicense) {
      pending++;
      http.get('/api/radio-license/badge/')
        .then(res => { if (!cancelled) setLicenseData(res || {}); })
        .catch(() => { if (!cancelled) setLicenseError(true); })
        .finally(() => { if (!cancelled) onDone(); });
    }

    if (canViewContract) {
      pending++;
      http.get('/api/contract-agreement/badge/')
        .then(res => { if (!cancelled) setContractData(res || {}); })
        .catch(() => { if (!cancelled) setContractError(true); })
        .finally(() => { if (!cancelled) onDone(); });
    }

    return () => { cancelled = true; };
  }, []);

  // 无任何权限
  if (!hasAnyPermission) {
    return (
      <Card
        title={<span><BellOutlined style={{ marginRight: 8 }} />到期提醒</span>}
        style={{ height: '100%' }}
      >
        <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>
          暂无可查看的到期信息
        </div>
      </Card>
    );
  }

  const licenseExpiring = licenseData?.expiring_count ?? 0;
  const licenseExpired = licenseData?.expired_count ?? 0;
  const contractExpiring = contractData?.expiring_count ?? 0;
  const contractExpired = contractData?.expired_count ?? 0;
  const totalExpiring = licenseExpiring + contractExpiring;

  // 全部请求失败
  const requestedCount = (canViewLicense ? 1 : 0) + (canViewContract ? 1 : 0);
  const failedCount = (canViewLicense && licenseError ? 1 : 0)
    + (canViewContract && contractError ? 1 : 0);
  const allFailed = failedCount === requestedCount && requestedCount > 0;

  // 空状态：所有请求均成功且数据全为 0
  const allSucceeded = (canViewLicense ? !licenseError : true)
    && (canViewContract ? !contractError : true);
  const allZero = (canViewLicense ? (licenseExpiring === 0 && licenseExpired === 0) : true)
    && (canViewContract ? (contractExpiring === 0 && contractExpired === 0) : true);
  const showEmpty = allSucceeded && allZero && !allFailed;

  return (
    <Card
      title={<span><BellOutlined style={{ marginRight: 8 }} />到期提醒</span>}
      loading={fetching}
      hoverable
      style={{ height: '100%' }}
    >
      {!fetching && allFailed ? (
        <div style={{ color: '#999', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>
          到期数据暂时无法获取
        </div>
      ) : (
        <div>
          <Statistic
            title="60天内即将到期"
            value={totalExpiring}
            suffix="项"
            valueStyle={{ color: '#faad14', fontSize: 28 }}
          />

          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {canViewLicense && (
              <div
                style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}
                onClick={() => history.push('/radio-license')}
              >
                <span style={{ fontSize: 13, color: '#595959' }}>无线电台执照</span>
                <span style={{ fontSize: 16, fontWeight: 500, color: '#faad14' }}>
                  {licenseError ? '-' : `${licenseExpiring} 项`}
                </span>
              </div>
            )}
            {canViewContract && (
              <div
                style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}
                onClick={() => history.push('/contract-agreement')}
              >
                <span style={{ fontSize: 13, color: '#595959' }}>合同协议</span>
                <span style={{ fontSize: 16, fontWeight: 500, color: '#faad14' }}>
                  {contractError ? '-' : `${contractExpiring} 项`}
                </span>
              </div>
            )}
          </div>

          {(licenseExpired > 0 || contractExpired > 0) && (
            <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {licenseExpired > 0 && <Tag color="red">执照已过期 {licenseExpired}</Tag>}
              {contractExpired > 0 && <Tag color="red">合同已过期 {contractExpired}</Tag>}
            </div>
          )}

          {!fetching && showEmpty && (
            <div style={{ marginTop: 8, color: '#999', fontSize: 13 }}>暂无即将到期的执照和合同</div>
          )}
        </div>
      )}
    </Card>
  );
}

export default ExpiryOverview;
