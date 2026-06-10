/**
 * 资料库模块 Error Boundary
 *
 * 替代 index.js 中不规范的 try/catch 包裹渲染方式。
 * React Error Boundary 能正确捕获子组件渲染期间、生命周期方法中的错误，
 * 而 try/catch 在函数组件体中无法捕获子组件的渲染错误。
 *
 * 参考：https://react.dev/reference/react/Component#catching-rendering-errors-with-an-error-boundary
 */
import React from 'react';
import { Button, Result } from 'antd';

class DocumentErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[DocumentErrorBoundary] 渲染错误:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面渲染错误"
          subTitle="抱歉，页面遇到了问题。请尝试刷新页面，如果问题持续请联系管理员。"
          extra={
            <Button type="primary" onClick={this.handleReset}>
              重试
            </Button>
          }
        />
      );
    }
    return this.props.children;
  }
}

export default DocumentErrorBoundary;
