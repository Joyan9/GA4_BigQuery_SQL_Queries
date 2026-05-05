# GA4 Annotations — Apps Script starter

Steps to run Phase 0–1 tests (Apps Script):

1. Enable APIs in GCP for your project:
   - Google Analytics Data API
   - Google Analytics Admin API

2. Create a new Apps Script project bound to the Google Sheet you will use, or use the standalone editor.

3. In the Apps Script editor, create the files and copy the code from `Code.gs` and `appsscript.json`.
   - If using the editor UI, add the OAuth scopes listed in `appsscript.json` to the project manifest.

4. Replace `PROPERTY_ID` placeholders in `Code.gs`:
   - In `testRunReport()` set `propertyId` to `properties/123456789` (include `properties/`).
   - In `testAdminApiGetProperty()` set `propertyNumericId` to `123456789` (numeric only).

5. Save and run each function once from the Apps Script UI. Authorize the scopes when prompted.

6. Check `View -> Logs` to inspect outputs. For `testRunReport`, confirm returned rows and `triplet_key` values.

Notes:
- `testAdminApiGetProperty` performs a safe GET to validate Admin API permission. If you need to test annotation writes, add a separate function and handle errors: do not mark campaign log rows as annotated unless the write returns success.
- After these checks succeed, I'll help implement the normalization, sheet bulk reads/writes, and the annotation formatting + write logic.
