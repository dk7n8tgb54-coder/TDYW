/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { Component } from 'react';
import {Switch, Route} from 'react-router-dom';
import Login from './pages/login';
import Layout from './layout';

class App extends Component {
  render() {
    return (
      <Switch>
        <Route path="/" exact component={Login} />
        {/* "实验室 / 原生维护台账"全屏样板路由已随原生路线整体下线删除（2026-10-20） */}
        <Route component={Layout} />
      </Switch>
    );
  }
}

export default App;
