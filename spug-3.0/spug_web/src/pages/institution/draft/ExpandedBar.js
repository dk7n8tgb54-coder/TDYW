/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 放大态顶部精简条（2026-10-30；2026-10-31 重试入口语境化）。放大编辑区
 * 时文件导航、元数据与次级操作全部收起，顶栏只保留离开工作台与保存主
 * 流程所需的最低信息：返回详情 / 当前文件名 / 修订号 / 独立保存状态 /
 * 提交编制状态 /「保存并结束编辑」；保存确认失败（finishingError）时在
 * 顶栏下方展示重试入口（文案按 finishingErrorKind 语境化：重试保存/
 * 重试切换/重试下载，分发由工作台 onFinishingRetry 提供）与「不保存并
 * 退出」，保证保存确认与未保存保护流程在放大态依然可用。常规（非放大）
 * 顶栏仅渲染返回入口，由工作台直接渲染。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Alert, Button, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { submissionTagFor } from './FileNav';
import SaveStatusTag from './SaveStatusTag';
import { finishingErrorTitleOf, finishingRetryLabelOf } from './finishingShared';
import store from './store';

const ExpandedBar = observer(({file, onBackToDetail, onSaveFinish,
  onDiscardExit, onFinishingRetry}) => {
  const finishing = store.finishingFileId === file.id;
  const showError = store.finishingError && store.finishingErrorFileId === file.id;
  return (
    <div style={{flexShrink: 0}}>
      <div style={{display: 'flex', flexWrap: 'wrap', gap: '4px 12px',
        alignItems: 'center'}}>
        <Button type="link" icon={<ArrowLeftOutlined/>} style={{padding: 0}}
          onClick={onBackToDetail}>
          返回 {store.manual ? store.manual.name : ''}
        </Button>
        <span style={{fontWeight: 600}}>{file.name}</span>
        {file.draft
          ? <Tag color="blue" style={{marginRight: 0}}>r{file.draft.revision}</Tag>
          : <Tag style={{marginRight: 0}}>无草稿</Tag>}
        <SaveStatusTag file={file} hasSession={true}/>
        {submissionTagFor(file.submission)}
        <span style={{flex: 1}}/>
        <Button type="primary" size="small" loading={finishing}
          disabled={finishing} onClick={onSaveFinish}>
          保存并结束编辑
        </Button>
      </div>
      {showError && (
        <Alert type="error" showIcon style={{marginTop: 8}}
          message={finishingErrorTitleOf(store.finishingErrorKind)}
          description={store.finishingError}
          action={
            <span>
              <Button size="small" type="primary"
                onClick={onFinishingRetry}>
                {finishingRetryLabelOf(store.finishingErrorKind)}
              </Button>
              <Button size="small" danger style={{marginLeft: 8}}
                onClick={onDiscardExit}>不保存并退出</Button>
            </span>
          }/>
      )}
    </div>
  );
});

export default ExpandedBar;
