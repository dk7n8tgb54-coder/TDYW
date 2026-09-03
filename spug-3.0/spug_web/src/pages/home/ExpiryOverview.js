/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { Card, Statistic, Tag } from 'antd';
import { BellOutlined } from '@ant-design/icons';
import { http, history, hasPermission } from 'libs';

function ExpiryOverview() {
  const [fetching, setFetching] = useState(true);
  const [licenseData, setLicenseData] = useState(null);
  const [contractData, setContractData] = useState(null);
  const [approvalData, setApprovalData] = useState(null);
  const [licenseError, setLicenseError] = useState(false);
  const [contractError, setContractError] = useState(false);
  const [approvalError, setApprovalError] = useState(false);

  const canViewLicense = hasPermission('radio_license.license.view');
  const canViewContract = hasPermission('contract_agreement.agreement.view');
  const canViewApproval = hasPermission('radio_license.approval.view');
  const hasAnyPermission = canViewLicense || canViewContract || canViewApproval;

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

    if (canViewApproval) {
      pending++;
      http.get('/api/radio-license/approvals/badge/')
        .then(res => { if (!cancelled) setApprovalData(res || {}); })
        .catch(() => { if (!cancelled) setApprovalError(true); })
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
  const approvalExpiring = approvalData?.expiring_count ?? 0;
  const approvalExpired = approvalData?.expired_count ?? 0;
  const totalExpiring = licenseExpiring + contractExpiring + approvalExpiring;

  // 全部请求失败
  const requestedCount = (canViewLicense ? 1 : 0) + (canViewContract ? 1 : 0) + (canViewApproval ? 1 : 0);
  const failedCount = (canViewLicense && licenseError ? 1 : 0)
    + (canViewContract && contractError ? 1 : 0)
    + (canViewApproval && approvalError ? 1 : 0);
  const allFailed = failedCount === requestedCount && requestedCount > 0;

  // 空状态：所有请求均成功且数据全为 0
  const allSucceeded = (canViewLicense ? !licenseError : true)
    && (canViewContract ? !contractError : true)
    && (canViewApproval ? !approvalError : true);
  const allZero = (canViewLicense ? (licenseExpiring === 0 && licenseExpired === 0) : true)
    && (canViewContract ? (contractExpiring === 0 && contractExpired === 0) : true)
    && (canViewApproval ? (approvalExpiring === 0 && approvalExpired === 0) : true);
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
            {canViewApproval && (
              <div
                style={{ cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0' }}
                onClick={() => history.push('/station-frequency-approval')}
              >
                <span style={{ fontSize: 13, color: '#595959' }}>频率批复</span>
                <span style={{ fontSize: 16, fontWeight: 500, color: '#faad14' }}>
                  {approvalError ? '-' : `${approvalExpiring} 项`}
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

          {(licenseExpired > 0 || approvalExpired > 0) && (
            <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {licenseExpired > 0 && <Tag color="red">执照已过期 {licenseExpired}</Tag>}
              {approvalExpired > 0 && <Tag color="red">批复已过期 {approvalExpired}</Tag>}
            </div>
          )}

          {!fetching && showEmpty && (
            <div style={{ marginTop: 8, color: '#999', fontSize: 13 }}>暂无即将到期的执照、批复和合同</div>
          )}
        </div>
      )}
    </Card>
  );
}

export default ExpiryOverview;
