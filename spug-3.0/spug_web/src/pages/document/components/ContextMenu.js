/**
 * 右键菜单组件
 * 使用 React Portal 渲染到 document.body
 */
import React, { useEffect, useRef } from 'react';
import ReactDOM from 'react-dom';

// 常量定义
const Z_INDEX = 9999;

const ContextMenu = ({ visible, position, items, onClose }) => {
  const menuRef = useRef(null);
  
  // 点击外部关闭菜单
  useEffect(() => {
    if (!visible) return;
    
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        onClose();
      }
    };
    
    // 延迟绑定，避免当前点击立即关闭
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('touchstart', handleClickOutside);
    }, 10);
    
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('touchstart', handleClickOutside);
    };
  }, [visible, onClose]);
  
  // ESC 键关闭
  useEffect(() => {
    if (!visible) return;
    
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [visible, onClose]);
  
  if (!visible || !position) return null;

  const handleMenuItemClick = (onClick) => {
    if (onClick) {
      onClick();
    }
    onClose();
  };

  return ReactDOM.createPortal(
    <div
      ref={menuRef}
      style={{
        position: 'fixed',
        left: position.x,
        top: position.y,
        background: 'white',
        border: '1px solid #d9d9d9',
        borderRadius: 4,
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        zIndex: Z_INDEX,
        minWidth: 160,
        padding: '4px 0',
        fontSize: 13
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }}
    >
      {items.map((item, index) => (
        <div
          key={`${item.key}-${index}`}
          style={{
            padding: '6px 12px',
            cursor: item.disabled ? 'not-allowed' : 'pointer',
            transition: 'background 0.2s',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            opacity: item.disabled ? 0.5 : 1
          }}
          onMouseEnter={(e) => {
            if (!item.disabled) {
              e.currentTarget.style.background = '#f5f5f5';
            }
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'white';
          }}
          onClick={() => !item.disabled && handleMenuItemClick(item.onClick)}
        >
          {item.icon && (
            <span style={{ fontSize: 14, display: 'flex', alignItems: 'center' }}>
              {item.icon}
            </span>
          )}
          <span>{item.label}</span>
        </div>
      ))}
    </div>,
    document.body
  );
};

export default ContextMenu;
