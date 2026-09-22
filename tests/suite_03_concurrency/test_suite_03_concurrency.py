"""
SUITE 03: Concurrency, Race Conditions & State Locks
Tests simultaneous autosave race conditions, optimistic locking version conflicts,
idempotent double-submissions, and concurrent file ingestion loads.
"""
import uuid
import pytest
import asyncio
import httpx
import allure
from utils.api_client import AiravatApiClient
from utils.async_client import AiravatAsyncClient
from utils.file_generator import create_valid_financial_workbook


@allure.epic("Airavat Financial Engine")
@allure.feature("SUITE-03: Concurrency, Race Conditions & State Locks")
class TestSuite03Concurrency:

    @pytest.mark.asyncio
    @allure.story("TC_CONC_001: Concurrent Autosave Race Condition")
    @allure.title("TC_CONC_001 - Concurrent Autosave Race Condition (Lost Update Problem)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies that two simultaneous autosave requests targeting different cells "
        "(C5 to '1000' and D5 to '2000') in the same model do not overwrite each other "
        "due to unversioned row locking."
    )
    async def test_tc_conc_001_concurrent_autosave(self, settings, tenant_a_client: AiravatApiClient):
        """
        TC_CONC_001: Concurrent Autosave Race Condition (Lost Update Problem)
        Severity: Critical (P1)
        Objective: Dispatch simultaneous edits to cells C5 and D5; verify both persist.
        """
        model_id = "model_conc_100"

        # Step 1: Initialize async HTTP client session
        with allure.step("Step 1: Set up asynchronous HTTP client"):
            async_helper = AiravatAsyncClient(base_url=settings.effective_base_url)

        # Step 2: Concurrently dispatch Request 1 (C5 = 1000) and Request 2 (D5 = 2000)
        with allure.step("Step 2: Simultaneously dispatch cell C5 and D5 autosave requests via asyncio.gather"):
            async with httpx.AsyncClient(base_url=settings.effective_base_url, verify=settings.VERIFY_SSL) as async_client:
                # Fire both requests concurrently
                res1, res2 = await asyncio.gather(
                    async_helper.autosave(async_client, model_id=model_id, cell="C5", value="1000"),
                    async_helper.autosave(async_client, model_id=model_id, cell="D5", value="2000")
                )

        # Step 3: Assert both requests succeeded with 200 OK
        with allure.step("Step 3: Assert both autosave requests returned 200 OK"):
            assert res1.status_code == 200, f"Request 1 failed: {res1.text}"
            assert res2.status_code == 200, f"Request 2 failed: {res2.text}"

        # Step 4: Fetch model and verify both C5 and D5 exist without lost updates
        with allure.step("Step 4: Fetch model state and verify neither cell edit was lost"):
            get_resp = tenant_a_client.get_model(model_id)
            assert get_resp.status_code == 200
            model_data = get_resp.json()
            cells = model_data.get("cells", {})

            # Assert Cell C5 retained value "1000"
            assert "C5" in cells, "Cell C5 is missing from model state"
            assert cells["C5"]["value"] == "1000", f"Cell C5 lost update: {cells['C5']}"

            # Assert Cell D5 retained value "2000"
            assert "D5" in cells, "Cell D5 is missing from model state"
            assert cells["D5"]["value"] == "2000", f"Cell D5 lost update: {cells['D5']}"

    @allure.story("TC_CONC_002: Optimistic Locking")
    @allure.title("TC_CONC_002 - Optimistic Locking on Simultaneous Assumption Updates")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Ensures that conflicting full-model updates reject stale versions (409 Conflict). "
        "User A submits update with version 5 (accepted), User B submits with stale version 5 (rejected)."
    )
    def test_tc_conc_002_optimistic_locking(self, tenant_a_client: AiravatApiClient, tenant_b_client: AiravatApiClient):
        """
        TC_CONC_002: Optimistic Locking on Simultaneous Assumption Updates
        Severity: High (P2)
        Objective: Reject update containing stale version with 409 Conflict and latest diff.
        """
        model_id = "model_lock_002"

        # Step 1: User A and User B fetch Model at version 5
        with allure.step("Step 1: Fetch initial model version (version = 5)"):
            base_model = tenant_a_client.get_model(model_id).json()
            initial_version = base_model.get("version", 5)

        # Step 2: User A submits update with version 5 -> Accepted (Moves to version 6)
        with allure.step("Step 2: User A submits update with version 5 (Accepted -> version moves to 6)"):
            payload_a = {"version": initial_version, "assumptions": {"wacc": 0.08}}
            resp_a = tenant_a_client.update_model(model_id, payload_a)
            assert resp_a.status_code == 200, f"User A update failed: {resp_a.text}"

        # Step 3: User B submits update with stale version 5 -> Rejected with 409 Conflict
        with allure.step("Step 3: User B submits update with stale version 5 (Expect 409 Conflict)"):
            payload_b = {"version": initial_version, "assumptions": {"wacc": 0.09}}
            resp_b = tenant_b_client.update_model(model_id, payload_b)

            # Assert status is 409 Conflict
            assert resp_b.status_code == 409, (
                f"Expected 409 Conflict for stale version, got: {resp_b.status_code}"
            )
            data_b = resp_b.json()
            # Verify response provides latest server_version and diff
            assert "server_version" in data_b, "Latest server_version missing in 409 response"
            assert data_b.get("server_version") >= 6, (
                f"Expected server_version >= 6, got: {data_b.get('server_version')}"
            )

    @pytest.mark.asyncio
    @allure.story("TC_CONC_003: Idempotency")
    @allure.title("TC_CONC_003 - Idempotency of Model Creation on Double-Submit")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Prevents duplicate model creation when network retries send duplicate requests "
        "with matching Idempotency-Key header."
    )
    async def test_tc_conc_003_double_submit_idempotency(self, settings):
        """
        TC_CONC_003: Idempotency of Model Creation on Double-Submit
        Severity: Medium (P2)
        Objective: Replay duplicate creation requests; ensure single entity created.
        """
        idempotency_key = f"e2e-uuid-{uuid.uuid4()}"
        creation_payload = {"name": "Idempotent_Model_Test", "template_id": "tpl_standard"}
        async_helper = AiravatAsyncClient(base_url=settings.effective_base_url)

        # Step 1: Dispatch first creation request with Idempotency-Key
        with allure.step("Step 1: Submit first model creation request with Idempotency-Key"):
            async with httpx.AsyncClient(base_url=settings.effective_base_url, verify=settings.VERIFY_SSL) as client:
                res1 = await async_helper.create_model_with_idempotency(client, idempotency_key, creation_payload)
                assert res1.status_code == 201, f"First creation failed: {res1.text}"
                first_model_id = res1.json().get("model_id")
                assert first_model_id, "Model ID was not returned in first response"

        # Step 2: Dispatch duplicate creation request with identical Idempotency-Key
        with allure.step("Step 2: Replay duplicate creation request with identical Idempotency-Key"):
            async with httpx.AsyncClient(base_url=settings.effective_base_url, verify=settings.VERIFY_SSL) as client:
                res2 = await async_helper.create_model_with_idempotency(client, idempotency_key, creation_payload)

        # Step 3: Assert second request returns 200 OK or 201 Created with identical model_id
        with allure.step("Step 3: Assert second request references identical model_id (no duplicate entity)"):
            assert res2.status_code in (200, 201), f"Second request failed: {res2.text}"
            second_model_id = res2.json().get("model_id")
            assert second_model_id == first_model_id, (
                f"Idempotency violation! New entity created: {second_model_id} != {first_model_id}"
            )

    @pytest.mark.asyncio
    @allure.story("TC_CONC_004: Heavy Ingestion Load")
    @allure.title("TC_CONC_004 - Heavy Concurrent Ingestion Load")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Stress tests backend worker pool by uploading 10 spreadsheets concurrently. "
        "Verifies all 10 work orders queue and resolve without worker memory exhaustion (OOMKilled) or 502 Bad Gateway."
    )
    async def test_tc_conc_004_concurrent_ingestion_load(self, settings):
        """
        TC_CONC_004: Heavy Concurrent Ingestion Load
        Severity: High (P2)
        Objective: Upload 10 spreadsheets simultaneously; assert all return 200 OK without gateway dropouts.
        """
        # Step 1: Generate valid spreadsheet workbook bytes
        with allure.step("Step 1: Generate test spreadsheet workbook"):
            file_bytes = create_valid_financial_workbook().getvalue()

        # Step 2: Dispatch 10 concurrent file uploads
        with allure.step("Step 2: Dispatch 10 concurrent uploads via asyncio.gather"):
            async_helper = AiravatAsyncClient(base_url=settings.effective_base_url)
            async with httpx.AsyncClient(base_url=settings.effective_base_url, verify=settings.VERIFY_SSL, timeout=30.0) as client:
                tasks = [
                    async_helper.upload_file(client, file_bytes, f"Concurrent_Upload_{i}.xlsx")
                    for i in range(10)
                ]
                responses = await asyncio.gather(*tasks)

        # Step 3: Assert all 10 work orders succeeded without 502 Bad Gateway or 500 crashes
        with allure.step("Step 3: Assert all 10 concurrent uploads completed with 200 OK"):
            for idx, resp in enumerate(responses):
                assert resp.status_code == 200, (
                    f"Upload #{idx+1} failed with status {resp.status_code}: {resp.text}"
                )
                assert "upload_id" in resp.json(), f"Upload #{idx+1} missing upload_id in response"
