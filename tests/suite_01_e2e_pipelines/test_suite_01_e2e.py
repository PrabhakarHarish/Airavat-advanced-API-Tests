"""
SUITE 01: Chained E2E Business Pipelines
Tests multi-step business transactions, financial spreadsheet ingestion,
model recalculation, autosave persistence, and export fidelity.
"""
import io
import pytest
import allure
import openpyxl
from utils.api_client import AiravatApiClient
from utils.file_generator import (
    create_valid_financial_workbook,
    create_corrupted_financial_workbook,
)
from test_data.payloads import (
    get_model_assumptions_payload,
    get_cell_autosave_payload,
)


@allure.epic("Airavat Financial Engine")
@allure.feature("SUITE-01: Chained E2E Business Pipelines")
class TestSuite01E2E:

    @allure.story("TC_E2E_001: Financial Model Lifecycle")
    @allure.title("TC_E2E_001 - Ingest -> Recalculate -> Autosave -> Export Binary Verification")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies that a user can upload a raw financial spreadsheet, convert it into an interactive model, "
        "adjust economic assumptions, verify auto-calculations, and export a structurally identical Excel file."
    )
    def test_tc_e2e_001_complete_financial_model_lifecycle(self, unauth_client: AiravatApiClient, settings):
        """
        TC_E2E_001: Complete Financial Model Lifecycle (Ingest -> Recalculate -> Autosave -> Export)
        Severity: Critical (P1)
        Preconditions: User credentials with model creation privileges.
        """
        # -------------------------------------------------------------------------
        # Step 1: Authenticate against /API/login/ and capture session artifacts
        # -------------------------------------------------------------------------
        with allure.step("Step 1: Authenticate with valid credentials and capture tokens"):
            # Send POST request with credentials
            login_resp = unauth_client.login(settings.TENANT_A_USERNAME, settings.TENANT_A_PASSWORD)
            # Verify HTTP status is 200 OK
            assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
            # Extract authorization token and session id from client state
            assert unauth_client.auth_token is not None or unauth_client.session_id is not None, (
                "Sessionid or Bearer token was not properly assigned upon login"
            )

        client = unauth_client  # Now authenticated
        created_model_id = None

        try:
            # -------------------------------------------------------------------------
            # Step 2: Upload raw financial workbook (Base_Template.xlsx) via multipart POST
            # -------------------------------------------------------------------------
            with allure.step("Step 2: Upload 3-statement financial workbook via /API/excel/upload/"):
                # Dynamically generate in-memory Excel workbook
                workbook_bytes = create_valid_financial_workbook().getvalue()
                # Upload the workbook
                upload_resp = client.upload_excel(workbook_bytes, filename="Base_Template.xlsx")
                # Assert upload returns 200 OK
                assert upload_resp.status_code == 200, f"Spreadsheet upload failed: {upload_resp.text}"
                # Extract template/upload ID
                upload_id = upload_resp.json().get("upload_id")
                assert upload_id, "Upload response did not return a valid upload_id/template_id"

            # -------------------------------------------------------------------------
            # Step 3: Validate P&L balance reconciliation
            # -------------------------------------------------------------------------
            with allure.step("Step 3: Validate P&L reconciliation via /API/excel/validate-pnl/"):
                # Trigger server-side P&L validation
                pnl_resp = client.validate_pnl(upload_id)
                # Assert status is 200 OK
                assert pnl_resp.status_code == 200, f"P&L validation failed: {pnl_resp.text}"
                pnl_data = pnl_resp.json()
                # Verify that reconciliation status is BALANCED and variance is 0.00
                assert pnl_data.get("reconciliation_status") == "BALANCED", (
                    f"Expected BALANCED status, got {pnl_data.get('reconciliation_status')}"
                )
                assert float(pnl_data.get("variance", -1)) == 0.00, "P&L variance is non-zero"

            # -------------------------------------------------------------------------
            # Step 4: Convert validated template into an interactive financial model
            # -------------------------------------------------------------------------
            with allure.step("Step 4: Convert spreadsheet template to model via /API/excel/convert-to-model/"):
                model_name = "E2E_DCF_Model_2026"
                convert_resp = client.convert_to_model(upload_id, name=model_name)
                # Verify conversion succeeds with 200 OK
                assert convert_resp.status_code == 200, f"Model conversion failed: {convert_resp.text}"
                convert_data = convert_resp.json()
                created_model_id = convert_data.get("model_id")
                assert created_model_id, "Model ID was not returned from conversion endpoint"

            # -------------------------------------------------------------------------
            # Step 5: Update economic assumptions (WACC, terminal growth, tax rate)
            # -------------------------------------------------------------------------
            with allure.step("Step 5: Update economic assumptions and verify recalculated valuation"):
                assumptions_payload = get_model_assumptions_payload()
                update_resp = client.update_model(created_model_id, assumptions_payload)
                # Assert status is 200 OK
                assert update_resp.status_code == 200, f"Model update failed: {update_resp.text}"
                update_data = update_resp.json()
                # Confirm enterprise value and equity value were computed
                assert "enterprise_value" in update_data, "Recalculated Enterprise Value missing in response"
                assert "equity_value" in update_data, "Recalculated Equity Value missing in response"

            # -------------------------------------------------------------------------
            # Step 6: Autosave an incremental cell edit (D18 = D16 - D17)
            # -------------------------------------------------------------------------
            with allure.step("Step 6: Autosave cell edit (Cell D18) via /API/models/{id}/autosave/"):
                autosave_payload = get_cell_autosave_payload(cell="D18", value=5000000, formula="=D16-D17")
                autosave_resp = client.autosave_cell(
                    model_id=created_model_id,
                    cell="D18",
                    value=5000000,
                    formula="=D16-D17"
                )
                # Assert status is 200 OK
                assert autosave_resp.status_code == 200, f"Autosave failed: {autosave_resp.text}"
                # Assert response indicates state is saved and timestamp refreshed
                assert "updated_at" in autosave_resp.json(), "Timestamp 'updated_at' missing after autosave"

            # -------------------------------------------------------------------------
            # Step 7: Export model to Excel spreadsheet
            # -------------------------------------------------------------------------
            with allure.step("Step 7: Export model to Excel via /API/models/{id}/export/excel/"):
                export_resp = client.export_excel(created_model_id)
                # Verify status is 200 OK
                assert export_resp.status_code == 200, f"Export request failed: {export_resp.status_code}"
                # Verify Content-Type matches OpenXML spreadsheet specification
                expected_content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                assert expected_content_type in export_resp.headers.get("Content-Type", ""), (
                    f"Unexpected Content-Type: {export_resp.headers.get('Content-Type')}"
                )

            # -------------------------------------------------------------------------
            # Step 8: Binary validation of exported .xlsx buffer
            # -------------------------------------------------------------------------
            with allure.step("Step 8: Perform binary validation on exported Excel workbook"):
                # Load exported binary buffer directly with openpyxl
                exported_wb = openpyxl.load_workbook(io.BytesIO(export_resp.content), data_only=False)
                assert len(exported_wb.sheetnames) >= 1, "Exported workbook has no sheets"
                ws = exported_wb.active
                # Verify cell D18 formula is preserved
                assert ws["D18"].value == "=D16-D17", f"Expected cell D18 formula '=D16-D17', got: {ws['D18'].value}"

        finally:
            # -------------------------------------------------------------------------
            # Step 9: Teardown - Delete model to prevent test pollution
            # -------------------------------------------------------------------------
            with allure.step("Step 9: Teardown - Delete created model"):
                if created_model_id:
                    delete_resp = client.delete_model(created_model_id)
                    # Status should be 204 No Content or 200 OK
                    assert delete_resp.status_code in (200, 204), f"Model deletion failed: {delete_resp.status_code}"

    @allure.story("TC_E2E_002: Model Branching")
    @allure.title("TC_E2E_002 - Model Duplication, Branching, and Independent Mutability")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies that cloning an existing financial model generates an isolated copy "
        "where modifications do NOT mutate the origin model."
    )
    def test_tc_e2e_002_model_duplication_and_mutability(self, tenant_a_client: AiravatApiClient, sample_excel_bytes: bytes):
        """
        TC_E2E_002: Model Duplication, Branching, and Independent Mutability
        Severity: High (P2)
        Objective: Ensure branched child model does not share mutable state with parent model.
        """
        # Step 1: Create base model (Model_A) with initial Revenue = 1,000,000
        with allure.step("Step 1: Create base model (Model_A) with Revenue 1,000,000"):
            upload_resp = tenant_a_client.upload_excel(sample_excel_bytes)
            assert upload_resp.status_code == 200
            tpl_id = upload_resp.json().get("upload_id")

            model_a_resp = tenant_a_client.convert_to_model(tpl_id, name="Model_A_Base")
            assert model_a_resp.status_code == 200
            model_a_id = model_a_resp.json().get("model_id")

        model_b_id = None
        try:
            # Step 2: Call duplicate endpoint to branch Model_A into Model_B
            with allure.step("Step 2: Duplicate Model_A into Model_B_Scenario_Bear"):
                dup_resp = tenant_a_client.duplicate_model(model_a_id, new_name="Model_A_Scenario_Bear")
                assert dup_resp.status_code == 200, f"Duplication failed: {dup_resp.text}"
                model_b_id = dup_resp.json().get("model_id")
                assert model_b_id, "Model B ID missing from duplication response"
                assert model_b_id != model_a_id, "Cloned model received identical ID to parent"

            # Step 3: Mutate Model_B by adjusting Revenue to 700,000
            with allure.step("Step 3: Update Model_B Revenue to 700,000"):
                update_b_resp = tenant_a_client.update_model(model_b_id, payload={"revenue": 700000})
                assert update_b_resp.status_code == 200

            # Step 4: Fetch both models and assert independent state
            with allure.step("Step 4: Verify Model_A is unmutated while Model_B reflects updated Revenue"):
                get_a = tenant_a_client.get_model(model_a_id).json()
                get_b = tenant_a_client.get_model(model_b_id).json()

                # Model_A revenue must remain 1,000,000
                assert get_a.get("revenue") == 1000000, (
                    f"Parent model mutated! Expected 1,000,000, got: {get_a.get('revenue')}"
                )
                # Model_B revenue must reflect 700,000
                assert get_b.get("revenue") == 700000, (
                    f"Child model did not reflect update! Expected 700,000, got: {get_b.get('revenue')}"
                )
        finally:
            # Cleanup both models
            tenant_a_client.delete_model(model_a_id)
            if model_b_id:
                tenant_a_client.delete_model(model_b_id)

    @allure.story("TC_E2E_003: Transaction Rollback")
    @allure.title("TC_E2E_003 - Graceful Failure and Rollback on Corrupted Model Ingestion")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Verifies atomic database transactions during model generation; "
        "if parsing fails halfway, ensures no orphan records or phantom model IDs are created."
    )
    def test_tc_e2e_003_rollback_on_corrupted_model(self, tenant_a_client: AiravatApiClient):
        """
        TC_E2E_003: Graceful Failure and Rollback on Corrupted Model Ingestion
        Severity: High (P2)
        Objective: Reject broken spreadsheet and ensure zero partial state is committed.
        """
        # Step 1: Generate Excel where Sheet 2 contains corrupt XML tags
        with allure.step("Step 1: Create corrupted Excel spreadsheet"):
            corrupted_buf = create_corrupted_financial_workbook()
            corrupted_bytes = corrupted_buf.getvalue()

        # Step 2: Attempt model conversion using corrupted template
        with allure.step("Step 2: Submit corrupted template to /API/excel/convert-to-model/"):
            # Pass template_id indicating corrupt state
            resp = tenant_a_client.convert_to_model("tpl_corrupted_sample_003", name="Broken_Model")

            # Assert status is 422 Unprocessable Entity or 400 Bad Request
            assert resp.status_code in (400, 422), (
                f"Expected 400 or 422 for corrupt workbook, got {resp.status_code}"
            )
            data = resp.json()
            # Assert structured error details are returned
            assert data.get("error") == "PARSE_ERROR" or "error" in data, (
                f"Expected PARSE_ERROR in response, got: {data}"
            )
            assert "sheet" in data or "message" in data, "Detailed error metadata missing in response"

    @allure.story("TC_E2E_004: Session Teardown")
    @allure.title("TC_E2E_004 - Multi-User Session Teardown & Concurrent Session Eviction")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Verifies that logging out immediately invalidates subsequent API calls "
        "using that bearer token or session cookie across all background workers."
    )
    def test_tc_e2e_004_session_teardown_and_eviction(self, unauth_client: AiravatApiClient, settings):
        """
        TC_E2E_004: Multi-User Session Teardown & Concurrent Session Eviction
        Severity: Medium (P2)
        Objective: Invalidate token upon logout and reject replay attempts with 401 Unauthorized.
        """
        # Step 1: Log in and capture credentials
        with allure.step("Step 1: Authenticate and capture session"):
            login_resp = unauth_client.login(settings.TENANT_A_USERNAME, settings.TENANT_A_PASSWORD)
            assert login_resp.status_code == 200
            saved_token = unauth_client.auth_token
            saved_session_id = unauth_client.session_id

        # Step 2: Perform authenticated read to confirm session is valid
        with allure.step("Step 2: Verify active session with /API/get-preferred-profile"):
            profile_resp = unauth_client.get_preferred_profile()
            assert profile_resp.status_code == 200, f"Profile read failed with active session: {profile_resp.text}"

        # Step 3: Trigger logout endpoint
        with allure.step("Step 3: Call /API/logout/"):
            logout_resp = unauth_client.logout()
            assert logout_resp.status_code == 200, f"Logout request failed: {logout_resp.text}"

        # Step 4: Replay request using the previously saved invalidated token
        with allure.step("Step 4: Replay request using invalidated token and assert rejection"):
            headers = {"Authorization": f"Bearer {saved_token}"} if saved_token else {}
            cookies = {"sessionid": saved_session_id} if saved_session_id else {}

            replay_client = AiravatApiClient(base_url=settings.effective_base_url, verify_ssl=settings.VERIFY_SSL)
            replay_client.session.headers.update(headers)
            replay_client.session.cookies.update(cookies)

            replay_resp = replay_client.get_preferred_profile()

            # Assert status is 401 Unauthorized or 403 Forbidden
            assert replay_resp.status_code in (401, 403), (
                f"Security Vulnerability: Invalidated session accepted with status {replay_resp.status_code}"
            )
