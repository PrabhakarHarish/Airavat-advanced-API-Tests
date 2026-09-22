"""
SUITE 05: Security, Tenant Isolation & IDOR
Tests Horizontal Privilege Escalation (IDOR), object-level export permissions,
CSRF enforcement on mutating endpoints, Stored/Reflected XSS sanitization,
HTTP security headers, and post-logout replay protection.
"""
import pytest
import allure
from utils.api_client import AiravatApiClient
from utils.assertions import (
    assert_security_headers,
    assert_no_server_leakage,
    assert_no_stacktrace_in_error,
    assert_xss_sanitized,
)
from test_data.payloads import XSS_PAYLOADS


@allure.epic("Airavat Security & Hardening")
@allure.feature("SUITE-05: Security, Tenant Isolation & IDOR")
class TestSuite05Security:

    @allure.story("TC_SEC_001: Horizontal Privilege Escalation (IDOR)")
    @allure.title("TC_SEC_001 - Horizontal Privilege Escalation (IDOR) on Financial Models")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies that Tenant B cannot read (GET), mutate (PUT), or delete (DELETE) "
        "financial models belonging to Tenant A."
    )
    def test_tc_sec_001_horizontal_privilege_escalation_idor(
        self,
        tenant_a_client: AiravatApiClient,
        tenant_b_client: AiravatApiClient,
        tenant_a_model: str
    ):
        """
        TC_SEC_001: Horizontal Privilege Escalation (IDOR) on Financial Models
        Severity: Critical (P1)
        Preconditions: Tenant A creates a proprietary model (tenant_a_model).
        Objective: Tenant B attempts unauthorized access and must be blocked with 403 Forbidden or 404 Not Found.
        """
        model_id = tenant_a_model

        # Step 1: Tenant B attempts to read Tenant A's model (GET)
        with allure.step("Step 1: Tenant B attempts GET on Tenant A's model"):
            get_resp = tenant_b_client.get_model(model_id)
            # Assert Tenant B receives 403 Forbidden or 404 Not Found
            assert get_resp.status_code in (403, 404), (
                f"IDOR READ Vulnerability: Tenant B accessed Tenant A's model with status {get_resp.status_code}"
            )

        # Step 2: Tenant B attempts to modify Tenant A's model (PUT)
        with allure.step("Step 2: Tenant B attempts PUT on Tenant A's model"):
            put_resp = tenant_b_client.update_model(model_id, payload={"revenue": 0})
            # Assert Tenant B is blocked from modifying
            assert put_resp.status_code in (403, 404), (
                f"IDOR WRITE Vulnerability: Tenant B modified Tenant A's model with status {put_resp.status_code}"
            )

        # Step 3: Tenant B attempts to delete Tenant A's model (DELETE)
        with allure.step("Step 3: Tenant B attempts DELETE on Tenant A's model"):
            del_resp = tenant_b_client.delete_model(model_id)
            # Assert Tenant B is blocked from deleting
            assert del_resp.status_code in (403, 404), (
                f"IDOR DELETE Vulnerability: Tenant B deleted Tenant A's model with status {del_resp.status_code}"
            )

    @allure.story("TC_SEC_002: IDOR on Model Export")
    @allure.title("TC_SEC_002 - IDOR on Model Export Endpoint")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies that direct download endpoints (/API/models/{id}/export/excel/) "
        "enforce object-level ownership checks before streaming the file."
    )
    def test_tc_sec_002_idor_on_model_export(self, tenant_b_client: AiravatApiClient, tenant_a_model: str):
        """
        TC_SEC_002: IDOR on Model Export Endpoint
        Severity: Critical (P1)
        Objective: Verify Tenant B cannot download Tenant A's exported spreadsheet.
        """
        model_id = tenant_a_model

        # Step 1: Tenant B requests the Excel download for Tenant A's model
        with allure.step("Step 1: Tenant B requests Excel download of Tenant A's model"):
            export_resp = tenant_b_client.export_excel(model_id)

        # Step 2: Assert download is rejected with 403 Forbidden
        with allure.step("Step 2: Assert export download blocked with 403 Forbidden"):
            assert export_resp.status_code in (403, 404), (
                f"IDOR EXPORT Vulnerability: Unauthorized tenant downloaded financial model with status {export_resp.status_code}"
            )

    @allure.story("TC_SEC_003: CSRF Protection")
    @allure.title("TC_SEC_003 - CSRF Protection on Mutating Financial Endpoints")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies Django CSRF protection on POST, PUT, DELETE operations using session cookies. "
        "When session cookie is sent without X-CSRFToken header, request must be rejected with 403 Forbidden."
    )
    def test_tc_sec_003_csrf_protection_on_mutations(self, settings, tenant_a_client: AiravatApiClient):
        """
        TC_SEC_003: CSRF Protection on Mutating Financial Endpoints
        Severity: High (P1)
        Objective: Send mutating request with sessionid cookie but strip CSRF token; expect 403 Forbidden.
        """
        # Step 1: Extract authenticated sessionid cookie
        session_id = tenant_a_client.session.cookies.get("sessionid")
        assert session_id, "Active sessionid cookie required for CSRF test"

        # Step 2: Build client with sessionid cookie but strictly WITHOUT X-CSRFToken header or csrftoken cookie
        with allure.step("Step 2: Build mutating request with sessionid cookie but stripped CSRF token"):
            csrf_test_client = AiravatApiClient(base_url=settings.effective_base_url, verify_ssl=settings.VERIFY_SSL)
            # Inject only sessionid
            csrf_test_client.session.cookies.set("sessionid", session_id)
            # Ensure no CSRF headers
            csrf_test_client.session.headers.pop("X-CSRFToken", None)
            csrf_test_client.session.headers.pop("Authorization", None)

        # Step 3: Dispatch mutating POST request
        with allure.step("Step 3: Dispatch POST /API/models/ without CSRF token"):
            response = csrf_test_client.post("/API/models/", json_data={"name": "CSRF_Attack_Model"})

        # Step 4: Assert response is 403 Forbidden due to CSRF failure
        with allure.step("Step 4: Assert 403 Forbidden returned by CSRF middleware"):
            assert response.status_code == 403, (
                f"CSRF Vulnerability: Mutating POST accepted without CSRF token! Status: {response.status_code}"
            )
            assert "csrf" in response.text.lower(), "CSRF error message missing from 403 response"

    @allure.story("TC_SEC_004: XSS Sanitization")
    @allure.title("TC_SEC_004 - XSS in Model Metadata & Financial Cell Comments")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Injects JavaScript payloads (<script>alert(1)</script>, <img src=x onerror=alert(1)>) "
        "into model names, descriptions, and comments. Verifies that response returns sanitized HTML entities."
    )
    def test_tc_sec_004_xss_sanitization(self, tenant_a_client: AiravatApiClient):
        """
        TC_SEC_004: XSS in Model Metadata & Financial Cell Comments
        Severity: Medium (P2)
        Objective: Submit multiple XSS payloads; verify that dangerous tags are sanitized/escaped.
        """
        for xss_payload in XSS_PAYLOADS:
            with allure.step(f"Inject XSS payload: {xss_payload[:30]}..."):
                # Step 1: Submit model creation with XSS string in name
                resp = tenant_a_client.post("/API/models/", json_data={"name": xss_payload})
                assert resp.status_code in (200, 201), f"Model creation failed: {resp.text}"

                # Step 2: Validate returned model name has no raw unescaped script tags
                data = resp.json()
                returned_name = data.get("name", "")
                assert_xss_sanitized(returned_name)

                # Cleanup
                model_id = data.get("model_id")
                if model_id:
                    tenant_a_client.delete_model(model_id)

    @allure.story("TC_SEC_005: Security Headers & Information Leakage")
    @allure.title("TC_SEC_005 - Security Header & Information Leakage Audit")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Verifies that API responses include mandatory security headers (X-Content-Type-Options: nosniff, "
        "X-Frame-Options, HSTS, Cache-Control: no-store) and do NOT leak Django debug info or exact server versions."
    )
    def test_tc_sec_005_security_headers_and_leakage_audit(self, tenant_a_client: AiravatApiClient):
        """
        TC_SEC_005: Security Header & Information Leakage Audit
        Severity: Medium (P2)
        Objective: Verify presence of enterprise security headers and absence of framework version leakage.
        """
        # Step 1: Make request to financial calculation endpoint
        with allure.step("Step 1: Fetch financial endpoint response"):
            response = tenant_a_client.recalculate("sec_headers_check", payload={})

        # Step 2: Validate mandatory security headers
        with allure.step("Step 2: Assert presence of security headers (nosniff, X-Frame-Options, HSTS, no-store)"):
            assert_security_headers(dict(response.headers), is_financial_endpoint=True)

        # Step 3: Verify Server header does not leak exact CPython or WSGIServer versions
        with allure.step("Step 3: Assert Server header does not leak runtime details"):
            assert_no_server_leakage(dict(response.headers))

    @allure.story("TC_SEC_006: Replay Attack Defense")
    @allure.title("TC_SEC_006 - Replay Attack after Session Invalidation")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Captures a valid bearer token, performs logout, and immediately attempts replay. "
        "Verifies that the token is rejected with 401 Unauthorized."
    )
    def test_tc_sec_006_replay_attack_after_session_invalidation(self, unauth_client: AiravatApiClient, settings):
        """
        TC_SEC_006: Replay Attack after Session Invalidation
        Severity: High (P2)
        Objective: Confirm token revocation on server side prevents post-logout replay.
        """
        # Step 1: Authenticate and capture bearer token
        with allure.step("Step 1: Authenticate and capture token"):
            login_resp = unauth_client.login(settings.TENANT_A_USERNAME, settings.TENANT_A_PASSWORD)
            assert login_resp.status_code == 200
            token = unauth_client.auth_token
            assert token, "Bearer token required for replay test"

        # Step 2: Log out to invalidate token
        with allure.step("Step 2: Log out user session"):
            logout_resp = unauth_client.logout()
            assert logout_resp.status_code == 200

        # Step 3: Replay the captured token in a new client
        with allure.step("Step 3: Replay captured token against /API/get-preferred-profile"):
            replay_client = AiravatApiClient(base_url=settings.effective_base_url, verify_ssl=settings.VERIFY_SSL)
            replay_client.session.headers.update({"Authorization": f"Bearer {token}"})
            replay_resp = replay_client.get_preferred_profile()

        # Step 4: Assert token replay fails with 401 Unauthorized
        with allure.step("Step 4: Assert 401 Unauthorized returned on replayed token"):
            assert replay_resp.status_code == 401, (
                f"Replay Vulnerability: Invalidated token was accepted with status {replay_resp.status_code}"
            )
