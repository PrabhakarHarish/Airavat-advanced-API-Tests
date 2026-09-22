# Airavat Platform: Advanced End-to-End (E2E) API Test Suite Specification

**Target Application:** Airavat Financial Modeling & Analytics Platform  
**Target Environment:** `https://10.20.11.244:3000` (Backend: Django / REST API)  
**Document Version:** 1.0  
**Focus:** Stateful Multi-Step E2E Flows, Financial Data Precision, Concurrency, Excel Ingestion Vulnerabilities, IDOR/RBAC Security, and Performance Resilience.

---

## Architecture of Advanced E2E API Testing

Unlike basic unit tests that hit individual endpoints in isolation with simple status code checks (`200 OK`), **Advanced End-to-End API Testing** validates:
1. **Chained Business Workflows**: Sequential dependent transactions where output from Step $N$ serves as input to Step $N+1$.
2. **Financial Logic & Mathematical Reconciliation**: Verifying calculation engine integrity (DCF, P&L, EBITDA, formula dependencies).
3. **Data Integrity & Concurrency**: Handling simultaneous autosaves, race conditions, and optimistic locking.
4. **Security & Boundary Attacks**: Insecure Direct Object References (IDOR), XML/Zip entity expansion in `.xlsx` files, CSRF enforcement, and Session tampering.
5. **Resilience & Fault Injection**: Timeout thresholds, payload exhaustion, and error recovery.

---

## Overview of Advanced Test Suites

| Suite ID | Suite Name | Test Cases | Objective |
| :--- | :--- | :--- | :--- |
| **SUITE-01** | **Chained E2E Business Pipelines** | `TC_E2E_001` - `TC_E2E_004` | Multi-step lifecycle from login, file ingestion, formula recalculation, to export |
| **SUITE-02** | **Financial Engine & Calculation Precision** | `TC_FIN_001` - `TC_FIN_005` | Floating-point precision, circular reference handling, formula cascades, and reconciliation |
| **SUITE-03** | **Concurrency, Race Conditions & State Locks** | `TC_CONC_001` - `TC_CONC_004` | Simultaneous cell autosaves, version collisions, and double-submission locks |
| **SUITE-04** | **Malicious File Ingestion & Parser Hardening** | `TC_FILE_001` - `TC_FILE_005` | Zip bomb, XXE in OpenXML, macro stripping, formula injection (CSV/Excel injection) |
| **SUITE-05** | **Security, Tenant Isolation & IDOR** | `TC_SEC_001` - `TC_SEC_006` | Horizontal privilege escalation (IDOR), CSRF protection, token replay, header hardening |
| **SUITE-06** | **Latency Benchmarks & Rate Limiting** | `TC_PERF_001` - `TC_PERF_003` | Recalculation engine under heavy formula load, brute-force rate limit throttling |

---

## SUITE 01: Chained E2E Business Pipelines

### TC_E2E_001: Complete Financial Model Lifecycle (Ingest -> Recalculate -> Autosave -> Export)
- **Severity**: Critical (P1)
- **Objective**: Verify that a user can upload a raw financial spreadsheet, convert it into an interactive model, adjust economic assumptions, verify auto-calculations, and export a 100% structurally identical Excel file.
- **Preconditions**: Active user account with model creation permissions.
- **Execution Steps**:
  1. **Authenticate**: `POST /API/login/` with valid credentials.
     - *Extract*: `sessionid`, `csrftoken`, and `token` from response headers/body.
  2. **Upload Template**: `POST /API/excel/upload/` with multi-part form data containing a valid 3-statement financial workbook (`Base_Template.xlsx`).
     - *Extract*: `upload_id` or `template_id` from JSON response.
  3. **Validate P&L Reconciliation**: `POST /API/excel/validate-pnl/` with `template_id`.
     - *Verify*: Status `200`, `reconciliation_status: "BALANCED"`, variance is `0.00`.
  4. **Convert to Interactive Model**: `POST /API/excel/convert-to-model/` with `{"template_id": upload_id, "name": "E2E_DCF_Model_2026"}`.
     - *Extract*: `model_id`.
  5. **Update Economic Assumptions**: `PUT /API/models/{model_id}/` with:
     ```json
     {
       "assumptions": {
         "wacc": 0.085,
         "terminal_growth_rate": 0.03,
         "tax_rate": 0.25
       }
     }
     ```
     - *Verify*: Response contains newly recalculated Enterprise Value and Equity Value.
  6. **Autosave Incremental Cell Edit**: `POST /API/models/{model_id}/autosave/` with:
     ```json
     {
       "active_cell": "D18",
       "changes": [{"cell": "D18", "value": 5000000, "formula": "=D16-D17"}]
     }
     ```
     - *Verify*: Status `200`, `updated_at` timestamp refreshed, downstream cells updated.
  7. **Export Model to Excel**: `GET /API/models/{model_id}/export/excel/`.
     - *Verify*: Status `200`, `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
  8. **Binary Validation**: Inspect exported `.xlsx` buffer:
     - Verify cell `D18` contains formula `=D16-D17` and evaluated value `5000000`.
     - Verify embedded chart data remains intact without formatting corruption.
  9. **Teardown**: `DELETE /API/models/{model_id}/` to prevent test artifact pollution.

---

### TC_E2E_002: Model Duplication, Branching, and Independent Mutability
- **Severity**: High (P2)
- **Objective**: Verify that cloning an existing financial model generates an isolated copy where modifications do NOT mutate the origin model.
- **Execution Steps**:
  1. Create base model `Model_A` with initial Revenue = `1,000,000`.
  2. Call `POST /API/models/{Model_A_id}/duplicate/` with `{"new_name": "Model_A_Scenario_Bear"}`.
  3. Extract `Model_B_id`.
  4. Send `PUT /API/models/{Model_B_id}/` adjusting Revenue to `700,000`.
  5. Fetch `GET /API/models/{Model_A_id}/` and `GET /API/models/{Model_B_id}/`.
  6. **Assertions**:
     - `Model_A.revenue` remains `1,000,000`.
     - `Model_B.revenue` reflects `700,000`.
     - Version history and audit trail accurately record the parent lineage without shared pointer defects.

---

### TC_E2E_003: Graceful Failure and Rollback on Corrupted Model Ingestion
- **Severity**: High (P2)
- **Objective**: Verify atomic database transactions during model generation; if parsing fails halfway, ensure no orphan records or phantom model IDs are created.
- **Execution Steps**:
  1. Generate an Excel file where Sheet 1 (Income Statement) is valid, but Sheet 2 (Balance Sheet) contains corrupt binary chunks or missing mandatory header tags.
  2. Send `POST /API/excel/convert-to-model/`.
  3. **Assertions**:
     - Status is `422 Unprocessable Entity` or `400 Bad Request`.
     - Response provides structured error details: `{"error": "PARSE_ERROR", "sheet": "Balance Sheet", "row": 42}`.
     - Execute `GET /API/models/` and assert that no partial or broken model was committed to the database.

---

### TC_E2E_004: Multi-User Session Teardown & Concurrent Session Eviction
- **Severity**: Medium (P2)
- **Objective**: Verify that logging out from one client immediately invalidates subsequent API calls using that bearer token or session cookie across all background workers.
- **Execution Steps**:
  1. Log in and capture `sessionid_1`.
  2. Perform valid read `POST /API/get-preferred-profile` (Assert 200).
  3. Call `GET /API/logout/`.
  4. Immediately replay `POST /API/get-preferred-profile` using `sessionid_1`.
  5. **Assertions**:
     - Status must be `401 Unauthorized` or `403 Forbidden` (validating fix for known TC_USER_002 defect).
     - Response must not leak anonymous user defaults.

---

## SUITE 02: Financial Engine & Calculation Precision

### TC_FIN_001: Floating-Point Precision & Rounding Consistency in P&L Aggregation
- **Severity**: Critical (P1)
- **Objective**: Guard against binary floating-point rounding errors (e.g. `0.1 + 0.2 != 0.3`) in large financial summations.
- **Payload**:
  ```json
  {
    "statement_type": "PNL",
    "periods": ["Q1", "Q2", "Q3", "Q4", "FY"],
    "line_items": {
      "Operating_Revenue": [100000.15, 200000.25, 300000.35, 400000.45],
      "Direct_Cost": [40000.05, 80000.10, 120000.15, 160000.20],
      "Gross_Profit": [60000.10, 120000.15, 180000.20, 240000.25]
    }
  }
  ```
- **Assertions**:
  - `Operating_Revenue` total FY must equal exactly `1000001.20`.
  - Net variances must be zero down to 4 decimal places.
  - JSON response must not return truncated float representations like `1000001.2000000001`.

---

### TC_FIN_002: Circular Reference Detection & Recursion Cutoff
- **Severity**: High (P1)
- **Objective**: Prevent server CPU exhaustion when user formulas contain circular dependencies (e.g. Interest Expense depends on Debt, Debt depends on Net Cash Flow, Net Cash Flow depends on Interest Expense).
- **Execution Steps**:
  1. Submit model formula definition where:
     - `Cell A1 = "=B1 * 1.05"`
     - `Cell B1 = "=A1 + 100"`
  2. Trigger model recalculation via `POST /API/models/{id}/recalculate/` or autosave.
- **Assertions**:
  - Request must NOT hang, timeout, or cause a `504 Gateway Timeout`.
  - Backend must detect cycle within $\le 500\text{ms}$.
  - Returns `400 Bad Request` with payload: `{"status": "CIRCULAR_DEPENDENCY_ERROR", "cycle_path": ["A1", "B1", "A1"]}`.

---

### TC_FIN_003: Mathematical Edge Cases (Division by Zero, Negative Discount Rates)
- **Severity**: Medium (P2)
- **Objective**: Verify that financial division by zero (e.g., Margin calculation when Revenue = 0) returns `#DIV/0!` representation without 500 Unhandled Exception.
- **Payload**:
  - Revenue: `0`
  - Net Profit: `-15000`
  - Formula: `GrossMargin = GrossProfit / Revenue`
- **Assertions**:
  - Response status: `200 OK` (with cell error object) or `422 Unprocessable Entity`.
  - Cell status flag: `{"cell": "C12", "error": "#DIV/0!", "display": "N/A"}`.

---

### TC_FIN_004: Formula Dependency Graph Cascade Recalculation
- **Severity**: High (P2)
- **Objective**: Verify that editing an input cell in the assumptions tab propagates down a 4-tier dependency tree.
- **Dependency Hierarchy**:
  - `Discount Rate (Tier 0)` -> `Discount Factors (Tier 1)` -> `Present Value of FCF (Tier 2)` -> `Enterprise Value (Tier 3)` -> `Target Share Price (Tier 4)`.
- **Execution Steps**:
  1. Patch `Discount Rate` from `8.0%` to `10.0%`.
  2. Inspect response for all 4 downstream tiers.
- **Assertions**:
  - All 4 levels must update in a single atomic response.
  - No stale cached values in `Target Share Price`.

---

### TC_FIN_005: Multi-Currency Normalization & Exchange Rate Conversion
- **Severity**: Medium (P3)
- **Objective**: Verify P&L consolidation when line items use mixed currencies (USD, EUR, INR).
- **Assertions**:
  - FX rate lookup applied correctly to consolidated summary sheet.
  - Precision maintained across conversion multipliers.

---

## SUITE 03: Concurrency, Race Conditions & State Locks

### TC_CONC_001: Concurrent Autosave Race Condition (Lost Update Problem)
- **Severity**: Critical (P1)
- **Objective**: Verify that two simultaneous autosave requests targeting different cells in the same model do not overwrite each other.
- **Execution Steps**:
  1. Authenticate two worker threads on the same model `Model_100`.
  2. Simultaneously dispatch (using `asyncio.gather`):
     - Request 1: `POST /API/models/100/autosave/` editing cell `C5` to `"1000"`.
     - Request 2: `POST /API/models/100/autosave/` editing cell `D5` to `"2000"`.
  3. Fetch `GET /API/models/100/`.
- **Assertions**:
  - Both requests return `200 OK`.
  - Cell `C5` is `"1000"` AND cell `D5` is `"2000"`.
  - Neither cell value is lost due to unversioned row locking.

---

### TC_CONC_002: Optimistic Locking on Simultaneous Assumption Updates
- **Severity**: High (P2)
- **Objective**: Ensure that conflicting full-model updates reject stale versions (`409 Conflict`).
- **Execution Steps**:
  1. User A and User B fetch Model 1 at `version: 5`.
  2. User A submits update with `version: 5`. (Accepted -> model moves to `version: 6`).
  3. User B submits update with `version: 5`.
- **Assertions**:
  - User B's request receives `409 Conflict`.
  - Response body returns latest `server_version: 6` and the diff.

---

### TC_CONC_003: Idempotency of Model Creation on Double-Submit
- **Severity**: Medium (P2)
- **Objective**: Prevent duplicate model creation when network retries send duplicate `POST /API/models/` requests.
- **Execution Steps**:
  1. Dispatch identical creation requests with matching `Idempotency-Key: e2e-uuid-987654`.
- **Assertions**:
  - First request returns `201 Created` with `model_id: X`.
  - Second request returns `200 OK` or `201 Created` referencing identical `model_id: X`.
  - Only one model record is added in the database.

---

### TC_CONC_004: Heavy Concurrent Ingestion Load
- **Severity**: High (P2)
- **Objective**: Stress test backend worker pool by uploading 10 spreadsheets concurrently.
- **Assertions**:
  - All 10 work orders queue and resolve without worker memory exhaustion (`OOMKilled`) or `502 Bad Gateway`.

---

## SUITE 04: Malicious File Ingestion & Parser Hardening

### TC_FILE_001: Decompression Bomb (Zip Bomb / "42.zip" in .xlsx)
- **Severity**: Critical (P1)
- **Objective**: Ensure openxml parser does not expand a tiny 50KB compressed file that inflates into 50GB of raw XML.
- **Execution Steps**:
  1. Craft an `.xlsx` with nested high-ratio compression layers.
  2. Dispatch `POST /API/excel/upload/`.
- **Assertions**:
  - Server must terminate decompression after exceeding memory limit (e.g. 50MB uncompressed limit).
  - Status code: `413 Payload Too Large` or `400 Bad Request`.
  - Server CPU must return to baseline immediately; process must not crash.

---

### TC_FILE_002: XML External Entity (XXE) Injection in workbook.xml
- **Severity**: Critical (P1)
- **Objective**: Verify that OpenXML/lxml parsers disable external entity resolution (`resolve_entities=False`).
- **Payload**:
  - Inject into `xl/workbook.xml`:
    ```xml
    <!DOCTYPE foo [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>
    <workbook><sheet name="&xxe;" sheetId="1"/></workbook>
    ```
  2. Dispatch `POST /API/excel/upload/`.
- **Assertions**:
  - Parser ignores or sanitizes entity.
  - Server does NOT return `/etc/passwd` or system contents in sheet names or error messages.

---

### TC_FILE_003: Formula Injection (CSV / Excel Command Injection)
- **Severity**: High (P1)
- **Objective**: Ensure formula injection payloads stored in cell labels or model names do not execute dynamic DDE commands upon export.
- **Payload**:
  - Model Name: `=cmd|' /C calc'!A0` or `@SUM(1+1)*cmd|' /C calc'!A0`
- **Assertions**:
  - Server prepends an apostrophe `'` or sanitizes leading `=`, `@`, `+`, `-` characters when exporting to Excel/CSV.

---

### TC_FILE_004: Embedded Macro Stripping (.xlsm with malicious VBA)
- **Severity**: High (P2)
- **Objective**: Verify that `.xlsm` files disguised as `.xlsx` have macros rejected or stripped.
- **Assertions**:
  - Reject `application/vnd.ms-excel.sheet.macroEnabled.12`.
  - If accepted, verify `vbaProject.bin` is completely stripped on export.

---

### TC_FILE_005: Zero-Byte & Truncated Header Stream
- **Severity**: Medium (P3)
- **Objective**: Upload files with 0 bytes, or files where stream ends abruptly after the ZIP magic header `PK\x03\x04`.
- **Assertions**:
  - Returns `400 Bad Request` with structured error `"corrupt_file_header"`, no unhandled tracebacks.

---

## SUITE 05: Security, Tenant Isolation & IDOR

### TC_SEC_001: Horizontal Privilege Escalation (IDOR) on Financial Models
- **Severity**: Critical (P1)
- **Objective**: Verify that User B cannot read, modify, or delete financial models belonging to User A.
- **Execution Steps**:
  1. Log in as `Tenant_A` -> Create `Model_A1` (id: 105).
  2. Log in as `Tenant_B` (distinct session token).
  3. Send `GET /API/models/105/` with `Tenant_B`'s token.
  4. Send `PUT /API/models/105/` with `Tenant_B`'s token.
  5. Send `DELETE /API/models/105/` with `Tenant_B`'s token.
- **Assertions**:
  - All requests from `Tenant_B` MUST return `403 Forbidden` or `404 Not Found`.
  - Zero data leakage of `Tenant_A`'s proprietary calculations.

---

### TC_SEC_002: IDOR on Model Export Endpoint
- **Severity**: Critical (P1)
- **Objective**: Verify that direct download endpoints (`/API/models/{id}/export/excel/`) enforce object-level ownership checks before streaming the file.
- **Assertions**:
  - Unauthenticated or unauthorized user receives `403 Forbidden` rather than receiving file stream.

---

### TC_SEC_003: CSRF Protection on Mutating Financial Endpoints
- **Severity**: High (P1)
- **Objective**: Verify Django CSRF protection on `POST`, `PUT`, `DELETE` operations using session cookies.
- **Execution Steps**:
  1. Authenticate with valid `sessionid` cookie.
  2. Strip `X-CSRFToken` header and `csrftoken` cookie.
  3. Send `POST /API/models/`.
- **Assertions**:
  - Status `403 Forbidden`.
  - Body contains CSRF validation failure reason.

---

### TC_SEC_004: XSS in Model Metadata & Financial Cell Comments
- **Severity**: Medium (P2)
- **Objective**: Inject JavaScript payloads (`<script>alert(document.cookie)</script>`, `<img src=x onerror=alert(1)>`) into model names, descriptions, and cell comments.
- **Assertions**:
  - Returned JSON contains properly escaped or sanitized HTML entities.

---

### TC_SEC_005: Security Header & Information Leakage Audit
- **Severity**: Medium (P2)
- **Objective**: Verify that API responses do not expose sensitive infrastructure details.
- **Assertions**:
  - Headers must include:
    - `X-Content-Type-Options: nosniff`
    - `X-Frame-Options: DENY` or `SAMEORIGIN`
    - `Strict-Transport-Security: max-age=31536000`
    - `Cache-Control: no-store` (for financial reports and P&L endpoints)
  - `Server` header must not expose exact Django/Python versions (e.g. `Server: WSGIServer/0.2 CPython/3.12`).
  - Error responses (4xx/5xx) must NOT leak stack traces, SQL strings, or local paths (mitigating DEBUG=True finding).

---

### TC_SEC_006: Replay Attack after Session Invalidation
- **Severity**: High (P2)
- **Objective**: Capture valid bearer token, perform logout, and attempt replay of token.
- **Assertions**:
  - Token is rejected immediately with `401 Unauthorized`.

---

## SUITE 06: Latency Benchmarks & Rate Limiting

### TC_PERF_001: Recalculation Engine Latency Benchmark under Heavy Load
- **Severity**: Medium (P2)
- **Objective**: Ensure calculation engine can compute a 5-year monthly model (60 periods $\times$ 150 accounts = 9,000 cells) within acceptable SLA.
- **Execution Steps**:
  1. Post model recalculation request with full 9,000-cell dataset.
  2. Measure time-to-first-byte (TTFB) and total response time.
- **Assertions**:
  - Total latency $\le 1500\text{ms}$.
  - Memory consumption returns to baseline post-execution.

---

### TC_PERF_002: Brute-Force Rate Limiting on Login (`/API/login/`)
- **Severity**: High (P2)
- **Objective**: Verify that rapid sequential failed logins are rate-limited to mitigate credential stuffing.
- **Execution Steps**:
  1. Send 15 invalid login requests within a 5-second window from the same IP.
- **Assertions**:
  - Requests 1 to 5 return `401 Unauthorized`.
  - Requests 6+ return `429 Too Many Requests`.
  - Response includes `Retry-After` header.

---

### TC_PERF_003: Model Search & Query Param Sanity under Load
- **Severity**: Medium (P3)
- **Objective**: Execute complex multi-parameter filter queries (`GET /API/models/?template=DCF&year=2026&status=active&search=Q3`).
- **Assertions**:
  - Query executed via database index, responds within $\le 300\text{ms}$.
  - SQL injection payloads (`' OR '1'='1`) are strictly parameterized.

---

## Summary of Priority Implementation Roadmap

```
Phase 1: Security & IDOR Hardening (TC_SEC_001, TC_SEC_002, TC_SEC_003)
Phase 2: Core E2E Flow with Financial Precision (TC_E2E_001, TC_FIN_001, TC_FIN_002)
Phase 3: Concurrency & Autosave Integrity (TC_CONC_001, TC_CONC_002)
Phase 4: Parser Hardening & File Exploits (TC_FILE_001, TC_FILE_002)
Phase 5: Performance Benchmarking & Throttling (TC_PERF_001, TC_PERF_002)
```
