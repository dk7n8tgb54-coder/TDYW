/**
 * Industry rules document library entry.
 *
 * First-stage implementation:
 * - The page is a protected document-library view, not a ledger/table view.
 * - Files are still stored by the existing document module under the public
 *   system folder bound to industry_rules.
 */
import React from 'react';
import DocumentIndex from './index';
import { INDUSTRY_RULES_CODE } from 'libs/systemFolderContext';

export default function IndustryRulesIndex() {
  return (
    <DocumentIndex
      mode="industryRules"
      systemFolderCode={INDUSTRY_RULES_CODE}
      title="行业规章"
    />
  );
}
