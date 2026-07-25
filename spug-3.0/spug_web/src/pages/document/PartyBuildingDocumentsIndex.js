/**
 * Party-building document library entry.
 *
 * First-stage implementation:
 * - The page is a protected document-library view, not a ledger/table view.
 * - Files are still stored by the existing document module under the public
 *   system folder bound to party_building_documents.
 */
import React from 'react';
import DocumentIndex from './index';
import { PARTY_BUILDING_DOCUMENTS_CODE } from 'libs/systemFolderContext';

export default function PartyBuildingDocumentsIndex() {
  return (
    <DocumentIndex
      mode="partyBuildingDocuments"
      systemFolderCode={PARTY_BUILDING_DOCUMENTS_CODE}
      title="党建工作"
    />
  );
}
