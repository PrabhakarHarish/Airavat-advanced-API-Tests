"""
SUITE 02: Financial Engine & Calculation Precision
Tests floating-point rounding precision, circular reference detection,
mathematical edge cases, formula dependency cascades, and multi-currency normalization.
"""
import time
import pytest
import allure
from utils.api_client import AiravatApiClient
from utils.assertions import assert_financial_precision
from test_data.payloads import (
    get_valid_pnl_dataset,
    get_circular_ref_payload,
    get_div_by_zero_payload,
    get_cascade_formula_payload,
    get_multi_currency_payload,
)


@allure.epic("Airavat Financial Engine")
@allure.feature("SUITE-02: Financial Engine & Calculation Precision")
class TestSuite02Finance:

    @allure.story("TC_FIN_001: Floating-Point Precision")
    @allure.title("TC_FIN_001 - Floating-Point Precision & Rounding Consistency in P&L Aggregation")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Guards against binary floating-point rounding errors (e.g. 0.1 + 0.2 != 0.3) in large financial summations. "
        "Validates that line item totals equal exact decimal expectations without IEEE-754 float drift."
    )
    def test_tc_fin_001_floating_point_precision(self, tenant_a_client: AiravatApiClient):
        """
        TC_FIN_001: Floating-Point Precision & Rounding Consistency in P&L Aggregation
        Severity: Critical (P1)
        Objective: Verify that fractional financial values aggregate with 4-decimal precision
        and no binary float artifacts (such as 1000001.2000000001).
        """
        # Step 1: Prepare high-precision test payload containing fractional quarterly figures
        with allure.step("Step 1: Load high-precision P&L dataset"):
            # Line items: [100000.15, 200000.25, 300000.35, 400000.45]
            # Expected Sum: 1,000,001.20 exactly
            pnl_payload = get_valid_pnl_dataset()

        # Step 2: Submit calculation payload to financial recalculation engine
        with allure.step("Step 2: Submit P&L aggregation request to /API/models/pnl_test/recalculate/"):
            response = tenant_a_client.recalculate("pnl_test", payload=pnl_payload)
            # Verify HTTP status is 200 OK
            assert response.status_code == 200, f"Recalculation failed: {response.text}"
            data = response.json()

        # Step 3: Assert mathematical precision down to 4 decimal places
        with allure.step("Step 3: Assert totals match exact expected values without float drift"):
            totals = data.get("totals", {})
            actual_revenue = totals.get("Operating_Revenue")
            expected_revenue = 1000001.20

            # Verify that Operating_Revenue is exact
            assert_financial_precision(actual_revenue, expected_revenue, decimal_places=4)

            # Step 4: Verify raw JSON string does not contain truncated IEEE-754 drift
            raw_text = response.text
            assert "1000001.2000000001" not in raw_text, (
                "Floating-point representation defect: raw float representation leaked in JSON!"
            )

            # Step 5: Verify variance reported by backend engine is 0.0000
            reported_variance = data.get("variance", -1)
            assert_financial_precision(reported_variance, 0.0000, decimal_places=4)

    @allure.story("TC_FIN_002: Circular Reference Detection")
    @allure.title("TC_FIN_002 - Circular Reference Detection & Recursion Cutoff")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Prevents server CPU exhaustion when user formulas contain circular dependencies "
        "(e.g., A1 depends on B1, and B1 depends on A1). Backend must detect cycle within <= 500ms."
    )
    def test_tc_fin_002_circular_reference_detection(self, tenant_a_client: AiravatApiClient, settings):
        """
        TC_FIN_002: Circular Reference Detection & Recursion Cutoff
        Severity: High (P1)
        Objective: Submit circular formula A1 -> B1 -> A1 and verify prompt detection and rejection.
        """
        # Step 1: Craft formula payload containing self-referencing circular loop
        with allure.step("Step 1: Construct circular dependency payload (A1 = B1 * 1.05, B1 = A1 + 100)"):
            circular_payload = {
                "active_cell": "A1",
                "changes": [
                    {"cell": "A1", "value": None, "formula": "=B1 * 1.05"},
                    {"cell": "B1", "value": None, "formula": "=A1 + 100"}
                ]
            }

        # Step 2: Trigger autosave/recalculation and measure execution latency
        with allure.step("Step 2: Dispatch circular formula request and measure latency"):
            start_time = time.perf_counter()
            response = tenant_a_client.post("/API/models/circ_model_002/autosave/", json_data=circular_payload)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # Step 3: Assert response terminates within SLA threshold (<= 500ms)
        with allure.step(f"Step 3: Verify cycle detection cutoff latency ({elapsed_ms:.2f} ms <= {settings.CIRCULAR_REF_CUTOFF_MS} ms)"):
            assert elapsed_ms <= settings.CIRCULAR_REF_CUTOFF_MS, (
                f"Circular reference check took too long: {elapsed_ms:.2f} ms (SLA: {settings.CIRCULAR_REF_CUTOFF_MS} ms)"
            )

        # Step 4: Assert HTTP status 400 Bad Request with CIRCULAR_DEPENDENCY_ERROR
        with allure.step("Step 4: Assert 400 Bad Request with cycle details"):
            assert response.status_code == 400, f"Expected 400 Bad Request, got {response.status_code}"
            data = response.json()
            assert data.get("status") == "CIRCULAR_DEPENDENCY_ERROR", (
                f"Expected status CIRCULAR_DEPENDENCY_ERROR, got: {data.get('status')}"
            )
            # Verify cycle path is reported
            cycle_path = data.get("cycle_path", [])
            assert len(cycle_path) >= 2, f"Expected cycle path in error response, got: {cycle_path}"

    @allure.story("TC_FIN_003: Mathematical Edge Cases")
    @allure.title("TC_FIN_003 - Mathematical Edge Cases (Division by Zero, Negative Discount Rates)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Verifies that financial division by zero (e.g. Margin calculation when Revenue = 0) "
        "returns #DIV/0! representation without throwing an unhandled 500 Internal Server Error."
    )
    def test_tc_fin_003_division_by_zero_handling(self, tenant_a_client: AiravatApiClient):
        """
        TC_FIN_003: Mathematical Edge Cases (Division by Zero)
        Severity: Medium (P2)
        Objective: Gracefully handle division by zero in financial formula evaluation.
        """
        # Step 1: Construct division by zero payload (GrossProfit / Revenue with Revenue = 0)
        with allure.step("Step 1: Construct payload where divisor is zero"):
            div_zero_payload = get_div_by_zero_payload()

        # Step 2: Send formula evaluation request
        with allure.step("Step 2: Submit calculation request to recalculate endpoint"):
            response = tenant_a_client.recalculate("edge_case_model", payload=div_zero_payload)

        # Step 3: Assert server returns 200 OK (with cell error flag) or 422 Unprocessable Entity
        with allure.step("Step 3: Verify server does NOT return 500 Unhandled Exception"):
            assert response.status_code in (200, 422), (
                f"Server crashed with unexpected status {response.status_code}: {response.text}"
            )

        # Step 4: Validate cell error object structure
        with allure.step("Step 4: Validate cell error flag #DIV/0!"):
            data = response.json()
            assert data.get("error") == "#DIV/0!" or data.get("status") == "DIV_BY_ZERO", (
                f"Expected #DIV/0! error representation, got: {data}"
            )

    @allure.story("TC_FIN_004: Formula Cascade Recalculation")
    @allure.title("TC_FIN_004 - Formula Dependency Graph Cascade Recalculation")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Verifies that editing an input cell in assumptions propagates through a 4-tier dependency tree: "
        "Discount Rate (Tier 0) -> Discount Factor (Tier 1) -> PV of FCF (Tier 2) -> "
        "Enterprise Value (Tier 3) -> Target Share Price (Tier 4)."
    )
    def test_tc_fin_004_formula_dependency_cascade(self, tenant_a_client: AiravatApiClient):
        """
        TC_FIN_004: Formula Dependency Graph Cascade Recalculation
        Severity: High (P2)
        Objective: Ensure change in Tier 0 propagates down all 4 tiers in a single atomic response.
        """
        # Step 1: Construct payload patching Discount Rate from 8.0% to 10.0%
        with allure.step("Step 1: Set Discount Rate to 10% (0.10)"):
            cascade_payload = get_cascade_formula_payload(discount_rate=0.10)

        # Step 2: Send update request to model
        with allure.step("Step 2: Dispatch assumptions update to /API/models/cascade_model/"):
            response = tenant_a_client.update_model("cascade_model", cascade_payload)
            assert response.status_code == 200, f"Cascade update failed: {response.text}"
            data = response.json()

        # Step 3: Assert all 4 tiers are present and recalculated atomically
        with allure.step("Step 3: Assert all 4 tiers of the calculation tree updated in the response"):
            # Tier 0: Discount Rate
            assert data.get("tier0_discount_rate") == 0.10, "Tier 0 rate mismatch"
            # Tier 1: Discount Factor
            assert "tier1_discount_factor" in data, "Tier 1 Discount Factor missing"
            # Tier 2: Present Value of FCF
            assert "tier2_present_value_fcf" in data, "Tier 2 PV of FCF missing"
            # Tier 3: Enterprise Value
            assert "tier3_enterprise_value" in data, "Tier 3 Enterprise Value missing"
            # Tier 4: Target Share Price
            assert "tier4_target_share_price" in data, "Tier 4 Target Share Price missing"

    @allure.story("TC_FIN_005: Multi-Currency Normalization")
    @allure.title("TC_FIN_005 - Multi-Currency Normalization & Exchange Rate Conversion")
    @allure.severity(allure.severity_level.MINOR)
    @allure.description(
        "Verifies P&L consolidation when line items use mixed currencies (USD, EUR, INR). "
        "Ensures FX rate lookup is applied correctly to the consolidated summary sheet."
    )
    def test_tc_fin_005_multi_currency_normalization(self, tenant_a_client: AiravatApiClient):
        """
        TC_FIN_005: Multi-Currency Normalization & Exchange Rate Conversion
        Severity: Medium (P3)
        Objective: Consolidate subsidiary revenues into single reporting currency with FX conversion.
        """
        # Step 1: Prepare multi-currency line items with fixed exchange rates
        with allure.step("Step 1: Prepare multi-currency payload (USD, EUR, INR)"):
            multi_curr_payload = get_multi_currency_payload()
            # USD: 1,000,000 * 1.0000 = 1,000,000
            # EUR: 850,000 * 1.0850 = 922,250
            # INR: 45,000,000 * 0.0120 = 540,000
            # Expected Consolidated Total USD = 2,462,250.00
            expected_consolidated = 2462250.00

        # Step 2: Trigger financial recalculation with multi-currency data
        with allure.step("Step 2: Submit consolidation request"):
            response = tenant_a_client.recalculate("multi_curr_model", payload=multi_curr_payload)
            assert response.status_code == 200, f"Multi-currency recalculation failed: {response.text}"
            data = response.json()

        # Step 3: Assert consolidated revenue matches expected FX conversion
        with allure.step("Step 3: Validate consolidated total and reporting currency"):
            assert data.get("reporting_currency") == "USD"
            actual_consolidated = data.get("consolidated_revenue")
            assert_financial_precision(actual_consolidated, expected_consolidated, decimal_places=2)
