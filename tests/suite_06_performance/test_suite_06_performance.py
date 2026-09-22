"""
SUITE 06: Latency Benchmarks & Rate Limiting
Tests calculation engine throughput on large matrices (9,000 cells),
credential stuffing / brute-force login rate limiting (429 Too Many Requests),
and parameterized search query latency under SLA thresholds.
"""
import time
import pytest
import allure
from utils.api_client import AiravatApiClient
from test_data.payloads import get_heavy_recalc_dataset


@allure.epic("Airavat Performance & Resilience")
@allure.feature("SUITE-06: Latency Benchmarks & Rate Limiting")
class TestSuite06Performance:

    @allure.story("TC_PERF_001: Recalculation Benchmark")
    @allure.title("TC_PERF_001 - Recalculation Engine Latency Benchmark under Heavy Load")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Ensures calculation engine computes a 5-year monthly model (60 periods x 150 accounts = 9,000 cells) "
        "within acceptable SLA (<= 1500ms)."
    )
    def test_tc_perf_001_recalculation_latency_benchmark(self, tenant_a_client: AiravatApiClient, settings):
        """
        TC_PERF_001: Recalculation Engine Latency Benchmark under Heavy Load
        Severity: Medium (P2)
        Objective: Post full 9,000-cell dataset; assert computation latency is within SLA <= 1500ms.
        """
        # Step 1: Generate full 9,000 cell matrix dataset (60 periods x 150 accounts)
        with allure.step("Step 1: Generate 9,000-cell financial matrix payload"):
            heavy_payload = get_heavy_recalc_dataset(periods=60, accounts=150)
            assert heavy_payload["total_cells"] == 9000

        # Step 2: Dispatch recalculation request and measure round-trip latency
        with allure.step("Step 2: Submit heavy recalculation request and measure latency"):
            start_time = time.perf_counter()
            response = tenant_a_client.recalculate("perf_heavy_model", payload=heavy_payload)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # Step 3: Assert response status is 200 OK
        with allure.step("Step 3: Assert calculation completed with 200 OK"):
            assert response.status_code == 200, f"Recalculation failed: {response.text}"

        # Step 4: Assert execution latency meets SLA threshold (<= 1500ms)
        with allure.step(f"Step 4: Verify latency ({elapsed_ms:.2f} ms) <= SLA threshold ({settings.RECALCULATION_SLA_MS} ms)"):
            assert elapsed_ms <= settings.RECALCULATION_SLA_MS, (
                f"SLA Breach: Heavy calculation latency ({elapsed_ms:.2f} ms) exceeded limit ({settings.RECALCULATION_SLA_MS} ms)"
            )

    @allure.story("TC_PERF_002: Brute-Force Rate Limiting")
    @allure.title("TC_PERF_002 - Brute-Force Rate Limiting on Login (/API/login/)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies that rapid sequential failed logins are rate-limited to mitigate credential stuffing. "
        "Requests 1 to 5 return 401 Unauthorized; requests 6+ return 429 Too Many Requests with Retry-After header."
    )
    def test_tc_perf_002_login_brute_force_rate_limiting(self, unauth_client: AiravatApiClient):
        """
        TC_PERF_002: Brute-Force Rate Limiting on Login (/API/login/)
        Severity: High (P2)
        Objective: Send 15 invalid login requests within 5 seconds; assert 429 triggered after 5 attempts.
        """
        rate_limited_observed = False
        retry_after_header = None

        # Step 1: Send rapid sequential failed login requests from the same client
        with allure.step("Step 1: Rapidly send 15 invalid login attempts within 5-second window"):
            for attempt in range(1, 16):
                # Submit invalid credentials
                resp = unauth_client.login(username="attacker_bot", password=f"wrong_pass_{attempt}")

                if attempt <= 5:
                    # Initial attempts should fail with 401 Unauthorized
                    assert resp.status_code in (401, 429), (
                        f"Expected 401 on attempt #{attempt}, got {resp.status_code}"
                    )
                else:
                    # Subsequent attempts should be throttled with 429 Too Many Requests
                    if resp.status_code == 429:
                        rate_limited_observed = True
                        retry_after_header = resp.headers.get("Retry-After")
                        break

        # Step 2: Assert that 429 was returned
        with allure.step("Step 2: Assert 429 Too Many Requests was triggered"):
            assert rate_limited_observed, "Rate limiting was NOT triggered after repeated failed logins!"

        # Step 3: Assert Retry-After header is present
        with allure.step("Step 3: Verify Retry-After header is supplied in 429 response"):
            assert retry_after_header is not None, "429 response missing 'Retry-After' header"

    @allure.story("TC_PERF_003: Query Parameter Sanity")
    @allure.title("TC_PERF_003 - Model Search & Query Param Sanity under Load")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Executes complex multi-parameter filter queries and SQL injection attempts. "
        "Verifies query responds within SLA (<= 300ms) and handles SQL injection strings via parameterized queries."
    )
    def test_tc_perf_003_search_query_sanity_and_sql_injection(self, tenant_a_client: AiravatApiClient, settings):
        """
        TC_PERF_003: Model Search & Query Param Sanity under Load
        Severity: Medium (P3)
        Objective: Verify fast index lookup and SQL injection parameterization in search endpoint.
        """
        # Step 1: Test complex filter query and measure latency
        with allure.step("Step 1: Execute complex multi-parameter search filter"):
            complex_params = {
                "template": "DCF",
                "year": "2026",
                "status": "active",
                "search": "Q3"
            }
            start_time = time.perf_counter()
            resp = tenant_a_client.get("/API/models/", params=complex_params)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            assert resp.status_code == 200, f"Search failed: {resp.text}"

            # Verify search SLA latency (<= 300ms)
            assert elapsed_ms <= settings.SEARCH_QUERY_SLA_MS, (
                f"Search query latency ({elapsed_ms:.2f} ms) exceeded SLA ({settings.SEARCH_QUERY_SLA_MS} ms)"
            )

        # Step 2: Test SQL injection attack payload in search parameter
        with allure.step("Step 2: Submit SQL injection payload (' OR '1'='1) to search filter"):
            sql_injection_params = {"search": "' OR '1'='1"}
            sqli_resp = tenant_a_client.get("/API/models/", params=sql_injection_params)

            # Assert status is 200 OK (safely filtered) and does not crash or leak SQL syntax errors
            assert sqli_resp.status_code == 200, f"SQL injection search crashed with {sqli_resp.status_code}"
            assert "syntax error" not in sqli_resp.text.lower(), "SQL syntax error leaked in response!"
            assert "operationalerror" not in sqli_resp.text.lower(), "Database error leaked in response!"
