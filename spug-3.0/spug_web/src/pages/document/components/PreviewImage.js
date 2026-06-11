/**
 * 【H-2修复】安全预览图片组件
 *
 * 替代将长期 x-token 暴露在 URL 中的做法，
 * 先异步获取短时效 preview_token，再用它构造预览 URL。
 * 加载期间显示占位符。
 */
import React, { useState, useEffect } from 'react';
import http from 'libs/http';

const PreviewImage = React.memo(({ fileId, isPublic, thumbnail, alt, style, className, imgLoading, onError }) => {
  const [previewToken, setPreviewToken] = useState('');

  useEffect(() => {
    if (!fileId) return;
    let cancelled = false;
    http.get(`/api/document/preview_token/?id=${fileId}&is_public=${isPublic}`)
      .then((data) => {
        if (!cancelled) setPreviewToken(data.preview_token);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [fileId, isPublic]);

  if (!previewToken) {
    return <div style={{ ...style, background: '#f0f0f0', flexShrink: 0 }} />;
  }

  const src = `/api/document/preview/?id=${fileId}&is_public=${isPublic}&preview_token=${previewToken}${thumbnail ? '&thumbnail=true' : ''}`;

  return (
    <img
      src={src}
      alt={alt || ''}
      style={style}
      className={className}
      loading={imgLoading || 'lazy'}
      onError={onError}
    />
  );
});

export default PreviewImage;
