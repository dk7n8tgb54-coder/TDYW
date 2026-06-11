import React from 'react';
import { observer } from 'mobx-react';
import VirtualTransferList from './VirtualTransferList';

const TransferListContainer = (props) => {
  return <VirtualTransferList {...props} />;
};

export default observer(TransferListContainer);
