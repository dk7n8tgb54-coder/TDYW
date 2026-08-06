/**
 * 首页公告面板
 * 展示当前用户可见的最近公告（默认 5 条），含未读红点、新公告/重要标签、附件图标，
 * 右上角显示未读数量与“更多”入口。点击标题打开详情抽屉并自动标记已读。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { Card, List, Tag, Badge, Empty, Button, Spin } from 'antd';
import { PaperClipOutlined, SoundOutlined } from '@ant-design/icons';
import { http, history } from 'libs';
import AnnouncementDetail from './AnnouncementDetail';

export default function AnnouncementPanel() {
  const [loading, setLoading] = useState(false);
  const [list, setList] = useState([]);
  const [unread, setUnread] = useState(0);
  const [detailId, setDetailId] = useState(null);
  const [detailVisible, setDetailVisible] = useState(false);

  const fetchData = useCallback(() => {
    setLoading(true);
    Promise.all([
      http.get('/api/home/announcement/', { params: { page_size: 5 } }),
      http.get('/api/home/announcement/unread-count/'),
    ]).then(([res, cnt]) => {
      setList(res.results || []);
      setUnread(cnt.count || 0);
    }).catch(() => {
      setList([]);
      setUnread(0);
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openDetail = (id) => {
    setDetailId(id);
    setDetailVisible(true);
  };

  return (
    <Card
      size="small"
      title={<><SoundOutlined style={{ marginRight: 6, color: '#000' }} />公告</>}
      extra={[
        unread > 0
          ? <Badge key="b" count={unread} size="small" offset={[-4, 2]} style={{ marginRight: 12 }}>
              <span style={{ color: '#999' }}>未读</span>
            </Badge>
          : null,
        <Button key="more" type="link" size="small" onClick={() => history.push('/announcement')}>更多</Button>,
      ].filter(Boolean)}
      style={{ marginBottom: 12 }}
    >
      {loading && <Spin style={{ display: 'block', margin: '20px auto' }} />}
      {!loading && list.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无公告" />}
      {!loading && list.length > 0 && (
        <List
          size="small"
          dataSource={list}
          renderItem={item => (
            <List.Item
              style={{ cursor: 'pointer', paddingLeft: 4, paddingRight: 4 }}
              onClick={() => openDetail(item.id)}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <span
                  style={{
                    display: 'inline-block',
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    marginRight: 8,
                    background: item.is_read ? 'transparent' : '#ff4d4f',
                    border: item.is_read ? '1px solid #d9d9d9' : 'none',
                  }}
                />
                <span
                  style={{
                    fontWeight: item.is_important ? 600 : 400,
                    color: item.is_read ? '#595959' : '#262626',
                  }}
                  className="ellipsis"
                >
                  {item.title}
                </span>
                {item.is_new && <Tag color="red" style={{ marginLeft: 8 }}>新</Tag>}
                {item.is_important && <Tag color="gold" style={{ marginLeft: 4 }}>重要</Tag>}
                {item.attachment_count > 0 && (
                  <PaperClipOutlined style={{ marginLeft: 6, color: '#8c8c8c' }} />
                )}
                <div style={{ color: '#8c8c8c', fontSize: 12, marginTop: 2, paddingLeft: 16 }}>
                  {item.publish_department_name || '-'} · {item.published_at}
                </div>
              </div>
            </List.Item>
          )}
        />
      )}
      <AnnouncementDetail
        visible={detailVisible}
        announcementId={detailId}
        onClose={() => setDetailVisible(false)}
        onAfterRead={fetchData}
      />
    </Card>
  );
}
