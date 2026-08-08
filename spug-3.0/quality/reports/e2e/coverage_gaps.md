# E2E Coverage Gaps

## Environment Constraints

### Browser Coverage
- **Firefox**: Not tested. Playwright Firefox browser not installed in current environment. Only Chromium was used.
- **WebKit**: Not tested. Playwright WebKit browser not installed.
- **Mobile viewport**: Not tested. Only desktop Chromium (1440x900) was used.

### Test Account Limitations
- **Regular user (non-admin)**: No dedicated regular user account available. All tests use admin (is_supper=True) or e2e_tester (is_supper=True). Permission tests for limited-permission users are API-only (unauthenticated checks).
- **No-permission user**: No dedicated user with specific permissions revoked. Cannot test "menu hidden for unauthorized users" via real browser.
- **Tenant A / Tenant B users**: No multi-tenant test accounts configured. Cross-tenant isolation tests are not covered via UI. (Note: prior tenant isolation audit found NavView and NoticeView vulnerabilities - see MEMORY.md)

### External Services
- **kkFileView**: Service running on port 8012 (tdyw-kkfileview-test container). File preview tests not performed with real preview verification. Only API availability was checked.
- **Celery tasks**: Async tasks (file merge, cleanup, scheduled tasks) not directly tested in E2E suite.

## High-Side-Effect Operations (Not Tested)
- **User create/disable/delete**: Not tested via UI to avoid modifying admin account. Only list view verified.
- **Role modify/delete**: Not tested via UI. Only list view verified.
- **Tenant create/delete**: Not tested via UI. Only list view verified.
- **System settings modify**: Not tested via UI. Only view verified.
- **Alert rule management**: Not tested (rules not created/modified/deleted).

## Business Logic Gaps
- **File upload full flow**: Upload button interaction tested but file chooser may not complete in headless mode. Upload verification relies on API checks.
- **File download**: Not tested with actual file download verification.
- **File preview (kkFileView)**: Not tested with actual preview rendering.
- **Signature/signing flow**: Not tested (requires signature setup and specific business flow).
- **Party building document isolation**: Only page load verified. Upload/download in party building space not tested.
- **Cross-tenant data isolation**: Not tested via UI (requires multi-tenant test accounts).

## Module-Specific Gaps
- **Department Duty Log**: Sign/signature feature not tested (requires configured signature).
- **Runlog**: Status transitions (in_progress -> completed -> closed) only partially tested via API.
- **Upgrade**: No delete endpoint found in store. Created test records may persist (cleanup via fullCleanup helper).
- **Device**: Device history (DeviceHistory) not fully tested with CRUD.
- **Data Analysis**: Only page load verified. Chart interactions and data accuracy not tested.

## Recommendations
1. Create dedicated test users with specific permission sets for comprehensive permission testing.
2. Install Firefox and WebKit browsers for cross-browser testing.
3. Set up multi-tenant test accounts for cross-tenant isolation testing.
4. Add file upload/download tests with real file verification once headless upload is stable.
5. Verify kkFileView integration with actual file preview rendering.
6. Add test data cleanup script execution after each test run.
