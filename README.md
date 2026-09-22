
# Airavat Platform - Advanced API Test Automation Framework

Production-grade automated test suite implementing all 27 End-to-End (E2E), calculation precision, concurrency, parser security, IDOR, and performance benchmarks for the **Airavat Financial Modeling & Analytics Platform**.

---

## 📁 Project Folder Structure

```
.
├── config/                         # Centralized configuration loader
│   ├── __init__.py
│   └── settings.py                 # Reads .env, provides defaults (URLs, credentials, timeouts)
├── test_data/                      # Test payloads and attack vectors
│   ├── __init__.py
│   └── payloads.py                 # P&L matrices, DCF assumptions, XSS & SQLi payloads
├── utils/                          # Common test automation utilities
│   ├── __init__.py
│   ├── api_client.py               # Synchronous client (requests, session, CSRF, Allure steps)
│   ├── async_client.py             # Asynchronous client (httpx, asyncio for concurrency)
│   ├── assertions.py               # High-precision math, security headers, XSS assertions
│   └── file_generator.py           # In-memory workbooks: valid templates, corrupted sheets, zip bomb, XXE
├── mock_server/                    # High-fidelity local simulation server
│   ├── __init__.py
│   └── airavat_mock_api.py         # Multi-threaded server emulating all 27 platform test scenarios
├── tests/                          # Automated test suites
│   ├── conftest.py                 # Shared pytest fixtures, client setup, mock server lifecycle
│   ├── suite_01_e2e_pipelines/     # TC_E2E_001 - TC_E2E_004 (Chained multi-step E2E pipelines)
│   ├── suite_02_financial_engine/  # TC_FIN_001 - TC_FIN_005 (Calculation precision & formulas)
│   ├── suite_03_concurrency/       # TC_CONC_001 - TC_CONC_004 (Race conditions & locks)
│   ├── suite_04_file_parser/       # TC_FILE_001 - TC_FILE_005 (Parser hardening & exploits)
│   ├── suite_05_security_idor/     # TC_SEC_001 - TC_SEC_006 (Tenant isolation, IDOR, CSRF)
│   └── suite_06_performance/       # TC_PERF_001 - TC_PERF_003 (Recalculation SLA & rate limiting)
├── .env.example                    # Template environment variables
├── pytest.ini                      # Pytest runner configuration & markers
└── requirements.txt                # Python dependencies
```

---

## 🚀 How to Run the Tests Manually

### 1. Activate the Virtual Environment
```bash
source .venv/bin/activate
```

### 2. Run All 27 Test Cases (Default: Mock Mode)
By default, tests run against the integrated multi-threaded mock server without requiring external VPN access:
```bash
pytest
```
To run with detailed test-name verbosity:
```bash
pytest -v
```

### 3. Run Against the Live Backend Server
When connected to the target environment (`https://10.20.11.244:3000`), pass the `--live` flag:
```bash
pytest tests/ --live -v
```
Or set `AIRAVAT_USE_MOCK=false` in your `.env` file and run:
```bash
pytest -v
```

---

## 🎯 Running Specific Test Suites

| Suite ID | Command |
| :--- | :--- |
| **Suite 1: Chained E2E Pipelines** | `pytest tests/suite_01_e2e_pipelines/ -v` |
| **Suite 2: Financial Engine Precision** | `pytest tests/suite_02_financial_engine/ -v` |
| **Suite 3: Concurrency & Race Conditions** | `pytest tests/suite_03_concurrency/ -v` |
| **Suite 4: Malicious File Parser Hardening** | `pytest tests/suite_04_file_parser/ -v` |
| **Suite 5: Security, Tenant Isolation & IDOR** | `pytest tests/suite_05_security_idor/ -v` |
| **Suite 6: Latency Benchmarks & Throttling** | `pytest tests/suite_06_performance/ -v` |

---

## 🔍 Running Individual Test Cases

You can run any single test case directly by specifying its function name:

```bash
# Run TC_E2E_001 (Complete financial model lifecycle)
pytest tests/suite_01_e2e_pipelines/test_suite_01_e2e.py::TestSuite01E2E::test_tc_e2e_001_complete_financial_model_lifecycle -v

# Run TC_FIN_001 (Floating-point precision in P&L aggregation)
pytest tests/suite_02_financial_engine/test_suite_02_finance.py::TestSuite02Finance::test_tc_fin_001_floating_point_precision -v

# Run TC_CONC_001 (Concurrent cell autosave race conditions)
pytest tests/suite_03_concurrency/test_suite_03_concurrency.py::TestSuite03Concurrency::test_tc_conc_001_concurrent_autosave -v

# Run TC_FILE_001 (Zip bomb decompression defense)
pytest tests/suite_04_file_parser/test_suite_04_file_parser.py::TestSuite04FileParser::test_tc_file_001_zip_bomb_mitigation -v

# Run TC_SEC_001 (Horizontal privilege escalation IDOR)
pytest tests/suite_05_security_idor/test_suite_05_security.py::TestSuite05Security::test_tc_sec_001_horizontal_privilege_escalation_idor -v

# Run TC_PERF_002 (Brute-force login rate limiting)
pytest tests/suite_06_performance/test_suite_06_performance.py::TestSuite06Performance::test_tc_perf_002_login_brute_force_rate_limiting -v
```

---

## 🏷️ Running by Category / Pytest Markers

Filter tests dynamically using category markers defined in `pytest.ini`:

```bash
# Run only security, IDOR, and vulnerability tests
pytest -m security -v

# Run only financial math precision and calculation tests
pytest -m financial -v

# Run only concurrency and race condition tests
pytest -m concurrency -v

# Run only performance benchmarks and rate limiting tests
pytest -m performance -v
```

---

## 📊 Generating and Viewing Allure Reports

Allure test results are automatically written to `allure-results/` on each run.

1. **Generate the interactive HTML report**:
   ```bash
   allure generate allure-results -o allure-report --clean
   ```

2. **Open the report in your browser**:
   ```bash
   allure open allure-report
   ```

3. Or serve on a local development port directly:
   ```bash
   allure serve allure-results
   ```
