/**
 * 文件名文本组件（2026-08-16 交互收敛）
 *
 * 仅当名称真实被截断（scrollWidth > clientWidth）时才显示悬停 Tooltip：
 * 完整可见的名字悬停不弹任何提示，避免扫视列表时提示到处闪烁；
 * Tooltip 内为完整名称 + 一键复制。mouseEnterDelay 抑制鼠标划过时的误触发。
 */
import React, { useRef, useState } from 'react';
import { Tooltip, message } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { copyToClipboard } from '@/utils/common';

const FileNameText = ({ name }) => {
  const spanRef = useRef(null);
  // 截断检测在鼠标进入时进行：jsdom/无布局环境下恒为 false，即不弹提示
  const [truncated, setTruncated] = useState(false);

  return (
    <Tooltip
      placement="top"
      mouseEnterDelay={0.3}
      title={
        truncated ? (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, maxWidth: 440 }}>
            <span style={{ flex: 1, minWidth: 0, wordBreak: 'break-all' }}>{name}</span>
            <CopyOutlined
              style={{ color: '#fff', cursor: 'pointer', marginTop: 2, flexShrink: 0 }}
              onClick={(e) => {
                // 阻止冒泡触发行点击（打开文件夹/预览）
                e.stopPropagation();
                copyToClipboard(name).then((ok) => {
                  if (ok) {
                    message.success('文件名已复制');
                  } else {
                    message.error('复制失败，请手动复制');
                  }
                });
              }}
            />
          </div>
        ) : null
      }
    >
      <span
        ref={spanRef}
        onMouseEnter={() => {
          const el = spanRef.current;
          if (el) {
            setTruncated(el.scrollWidth > el.clientWidth);
          }
        }}
        style={{
          marginLeft: 8,
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {name}
      </span>
    </Tooltip>
  );
};

export default React.memo(FileNameText);
