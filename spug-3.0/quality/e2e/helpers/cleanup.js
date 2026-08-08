/**
 * Cleanup helper - removes test data created during E2E tests.
 * Only removes records with E2E_ prefix to avoid deleting existing data.
 */
const { loginAndCreateContext, apiGet, apiDelete, apiPatch } = require('./api');

/**
 * Clean up E2E test records from a given API endpoint.
 * Fetches all records, filters by E2E_ prefix, and deletes them.
 */
async function cleanupByPrefix(ctx, listPath, deletePath, field = 'title', idField = 'id') {
  try {
    const result = await apiGet(ctx, listPath);
    if (!result.data || !Array.isArray(result.data)) return;

    const testRecords = result.data.filter(item =>
      item[field] && String(item[field]).startsWith('E2E_')
    );

    for (const record of testRecords) {
      try {
        await apiDelete(ctx, `${deletePath}${record[idField]}/`);
      } catch (e) {
        // Continue even if individual delete fails
        console.log(`Cleanup: failed to delete ${record[idField]}: ${e.message}`);
      }
    }
  } catch (e) {
    console.log(`Cleanup: failed for ${listPath}: ${e.message}`);
  }
}

/**
 * Clean up E2E test folders in document library.
 */
async function cleanupDocumentFolders(ctx) {
  try {
    const result = await apiGet(ctx, '/api/document/folder/');
    if (!result.data || !Array.isArray(result.data)) return;

    const testFolders = result.data.filter(f =>
      f.name && f.name.startsWith('E2E_')
    );

    // Delete in reverse order (children first)
    for (const folder of testFolders.reverse()) {
      try {
        await apiDelete(ctx, `/api/document/folder/${folder.id}/`);
      } catch (e) {
        console.log(`Cleanup: failed to delete folder ${folder.id}: ${e.message}`);
      }
    }
  } catch (e) {
    console.log(`Cleanup: document folders: ${e.message}`);
  }
}

/**
 * Run full cleanup for all E2E test data.
 */
async function fullCleanup() {
  try {
    const { context } = await loginAndCreateContext('admin');

    // Clean up each module
    await cleanupByPrefix(context, '/api/department-duty-log/records/', '/api/department-duty-log/records/', 'title');
    await cleanupByPrefix(context, '/api/duty/duty/', '/api/duty/duty/', 'title');
    await cleanupByPrefix(context, '/api/runlog/runlogs/', '/api/runlog/runlogs/', 'title');
    await cleanupByPrefix(context, '/api/reminder/', '/api/reminder/', 'title');
    await cleanupByPrefix(context, '/api/radio-license/', '/api/radio-license/', 'license_no', 'id');
    await cleanupByPrefix(context, '/api/radio-license/approvals/', '/api/radio-license/approvals/', 'approval_no', 'id');
    await cleanupByPrefix(context, '/api/contract-agreement/', '/api/contract-agreement/', 'title');
    await cleanupByPrefix(context, '/api/regulation/regulations/', '/api/regulation/regulations/', 'title');
    await cleanupByPrefix(context, '/api/device/device-resume/', '/api/device/device-resume/', 'device_name', 'id');
    await cleanupByPrefix(context, '/api/fault/records/', '/api/fault/records/', 'title');
    await cleanupByPrefix(context, '/api/upgrade/records/', '/api/upgrade/records/', 'title');
    await cleanupByPrefix(context, '/api/interference/records/', '/api/interference/records/', 'title');

    // Document folders
    await cleanupDocumentFolders(context);

    await context.dispose();
    console.log('E2E cleanup completed');
  } catch (e) {
    console.log(`E2E cleanup error: ${e.message}`);
  }
}

module.exports = {
  cleanupByPrefix,
  cleanupDocumentFolders,
  fullCleanup,
};
