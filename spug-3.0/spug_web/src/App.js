/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { Component } from 'react';
import {Switch, Route} from 'react-router-dom';
import Login from './pages/login';
import NativeLedgerLab from './pages/lab/nativeLedger';
import Layout from './layout';

class App extends Component {
  render() {
    return (
      <Switch>
        <Route path="/" exact component={Login} />
        {/* 实验室：全屏内嵌原生维护台账样板，不套平台 Layout（原型自带侧栏/Header） */}
        <Route path="/lab/native-ledger" component={NativeLedgerLab} />
        <Route component={Layout} />
      </Switch>
    );
  }
}

export default App;
