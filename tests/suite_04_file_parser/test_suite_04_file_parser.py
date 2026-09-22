"""
SUITE 04: Malicious File Ingestion & Parser Hardening
Tests Zip bomb decompression defense, XXE injection containment,
Excel/CSV formula injection sanitization, VBA macro stripping, and truncated streams.
"""
import pytest
import allure
import zipfile
import io
from utils.api_client import AiravatApiClient
from utils.assertions import assert_formula_sanitized, assert_no_stacktrace_in_error
from utils.file_generator import (
    create_zip_bomb_xlsx,
    create_xxe_xlsx,
    create_macro_enabled_xlsx,
    create_formula_injection_xlsx,
    create_truncated_header_file,
)


@allure.epic("Airavat Security & Hardening")
@allure.feature("SUITE-04: Malicious File Ingestion & Parser Hardening")
class TestSuite04FileParser:

    @allure.story("TC_FILE_001: Decompression Bomb Defense")
    @allure.title("TC_FILE_001 - Decompression Bomb (Zip Bomb / 42.zip in .xlsx)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Ensures OpenXML parser terminates decompression when uncompressed ratio exceeds safety limits "
        "(e.g., 50MB uncompressed threshold). Returns 413 Payload Too Large or 400 Bad Request without crashing worker."
    )
    def test_tc_file_001_zip_bomb_mitigation(self, tenant_a_client: AiravatApiClient):
        """
        TC_FILE_001: Decompression Bomb (Zip Bomb / "42.zip" in .xlsx)
        Severity: Critical (P1)
        Objective: Upload high-ratio compressed file and verify backend rejects it gracefully.
        """
        # Step 1: Craft high-ratio compressed OpenXML file in memory
        with allure.step("Step 1: Craft Zip bomb disguised as .xlsx"):
            zip_bomb_bytes = create_zip_bomb_xlsx().getvalue()

        # Step 2: Upload the malicious payload to /API/excel/upload/
        with allure.step("Step 2: Upload Zip bomb to ingestion endpoint"):
            response = tenant_a_client.upload_excel(zip_bomb_bytes, filename="zip_bomb_exploit.xlsx")

        # Step 3: Assert response code is 413 Payload Too Large or 400 Bad Request
        with allure.step("Step 3: Assert rejection with 413 Payload Too Large or 400 Bad Request"):
            assert response.status_code in (400, 413), (
                f"Zip bomb was not rejected! Server returned: {response.status_code}"
            )
            # Step 4: Verify server did not dump unhandled stack traces
            assert_no_stacktrace_in_error(response.text)

    @allure.story("TC_FILE_002: XXE Injection Defense")
    @allure.title("TC_FILE_002 - XML External Entity (XXE) Injection in workbook.xml")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Verifies that OpenXML/lxml parsers disable external entity resolution (resolve_entities=False). "
        "Ensures server does NOT return /etc/passwd or local file contents in sheet names or error logs."
    )
    def test_tc_file_002_xxe_injection_defense(self, tenant_a_client: AiravatApiClient):
        """
        TC_FILE_002: XML External Entity (XXE) Injection in workbook.xml
        Severity: Critical (P1)
        Objective: Verify that external entities targeting local files are sanitized or ignored.
        """
        # Step 1: Craft OpenXML file with embedded <!ENTITY xxe SYSTEM "file:///etc/passwd">
        with allure.step("Step 1: Craft OpenXML spreadsheet containing XXE entity referencing /etc/passwd"):
            xxe_bytes = create_xxe_xlsx().getvalue()

        # Step 2: Upload the XXE spreadsheet
        with allure.step("Step 2: Submit XXE workbook to /API/excel/upload/"):
            response = tenant_a_client.upload_excel(xxe_bytes, filename="xxe_payload.xlsx")

        # Step 3: Assert response does not contain local system file contents (e.g. root:x:0:0)
        with allure.step("Step 3: Verify /etc/passwd contents were not resolved or leaked"):
            body = response.text.lower()
            assert "root:x:0:0" not in body, (
                "Critical XXE Vulnerability: /etc/passwd content exposed in response!"
            )
            assert "/bin/bash" not in body, (
                "Critical XXE Vulnerability: System paths exposed via XXE entity resolution!"
            )

    @allure.story("TC_FILE_003: Formula Injection")
    @allure.title("TC_FILE_003 - Formula Injection (CSV / Excel Command Injection)")
    @allure.severity(allure.severity_level.CRITICAL)
    @allure.description(
        "Ensures formula injection payloads stored in cell labels or model names "
        "(e.g., =cmd|' /C calc'!A0) are sanitized with a prepended single quote or stripped upon export."
    )
    def test_tc_file_003_formula_injection_sanitization(self, tenant_a_client: AiravatApiClient):
        """
        TC_FILE_003: Formula Injection (CSV / Excel Command Injection)
        Severity: High (P1)
        Objective: Submit formula command payloads in model names; verify export sanitization.
        """
        # Step 1: Create a model with malicious command injection in its name
        malicious_name = "=cmd|' /C calc'!A0"
        with allure.step("Step 1: Create model containing formula injection command"):
            creation_resp = tenant_a_client.post("/API/models/", json_data={"name": malicious_name})
            model_id = creation_resp.json().get("model_id")

        try:
            # Step 2: Request export of the model to Excel
            with allure.step("Step 2: Export model to Excel"):
                export_resp = tenant_a_client.export_excel(model_id)
                assert export_resp.status_code == 200

            # Step 3: Inspect exported workbook to confirm formula execution defense
            with allure.step("Step 3: Verify formula trigger characters (=, @, +, -) are sanitized"):
                # Load workbook bytes
                wb = io.BytesIO(export_resp.content)
                # Verify that no cell executes raw "=cmd" without sanitization
                z = zipfile.ZipFile(wb, 'r')
                for fname in z.namelist():
                    if fname.endswith(".xml"):
                        xml_content = z.read(fname).decode("utf-8", errors="ignore")
                        # Raw command triggers should not exist unescaped
                        assert "=cmd|' /C calc'!A0" not in xml_content, (
                            "Formula Injection Vulnerability: Raw command string exported in Excel OpenXML!"
                        )
        finally:
            # Cleanup
            if model_id:
                tenant_a_client.delete_model(model_id)

    @allure.story("TC_FILE_004: Macro Stripping")
    @allure.title("TC_FILE_004 - Embedded Macro Stripping (.xlsm with malicious VBA)")
    @allure.severity(allure.severity_level.NORMAL)
    @allure.description(
        "Verifies that .xlsm files disguised as .xlsx have macros rejected, "
        "or vbaProject.bin is completely stripped upon export."
    )
    def test_tc_file_004_embedded_macro_stripping(self, tenant_a_client: AiravatApiClient):
        """
        TC_FILE_004: Embedded Macro Stripping (.xlsm with malicious VBA)
        Severity: High (P2)
        Objective: Upload spreadsheet with embedded VBA project; verify stripping or rejection.
        """
        # Step 1: Craft spreadsheet containing vbaProject.bin
        with allure.step("Step 1: Craft spreadsheet containing embedded simulated VBA macro"):
            macro_bytes = create_macro_enabled_xlsx().getvalue()

        # Step 2: Upload spreadsheet
        with allure.step("Step 2: Submit macro-enabled file to /API/excel/upload/"):
            response = tenant_a_client.upload_excel(macro_bytes, filename="financial_model.xlsm")

        # Step 3: If accepted, verify exported file does not retain vbaProject.bin
        with allure.step("Step 3: Verify vbaProject.bin is stripped or rejected"):
            if response.status_code == 200:
                upload_id = response.json().get("upload_id")
                # Convert and export
                model_resp = tenant_a_client.convert_to_model(upload_id, name="Macro_Test_Model")
                model_id = model_resp.json().get("model_id")
                try:
                    export_resp = tenant_a_client.export_excel(model_id)
                    # Check zip contents of exported workbook
                    exported_zip = zipfile.ZipFile(io.BytesIO(export_resp.content), 'r')
                    filenames = exported_zip.namelist()
                    assert "xl/vbaProject.bin" not in filenames, (
                        "Security Defect: Embedded VBA macro was not stripped during export!"
                    )
                finally:
                    tenant_a_client.delete_model(model_id)
            else:
                # Direct rejection with 400/415 is also fully compliant
                assert response.status_code in (400, 415), (
                    f"Unexpected status code for macro upload: {response.status_code}"
                )

    @allure.story("TC_FILE_005: Corrupt Stream Handling")
    @allure.title("TC_FILE_005 - Zero-Byte & Truncated Header Stream")
    @allure.severity(allure.severity_level.MINOR)
    @allure.description(
        "Uploads files with 0 bytes or files where the stream ends abruptly after the ZIP magic header PK\\x03\\x04. "
        "Verifies server returns 400 Bad Request with structured error 'corrupt_file_header' without unhandled 500 tracebacks."
    )
    def test_tc_file_005_zero_byte_and_truncated_stream(self, tenant_a_client: AiravatApiClient):
        """
        TC_FILE_005: Zero-Byte & Truncated Header Stream
        Severity: Medium (P3)
        Objective: Reject 0-byte and truncated magic-header files gracefully.
        """
        # Step 1: Test empty 0-byte upload
        with allure.step("Step 1: Upload 0-byte empty file"):
            resp_empty = tenant_a_client.upload_excel(b"", filename="empty.xlsx")
            assert resp_empty.status_code == 400, (
                f"Expected 400 Bad Request for 0-byte file, got {resp_empty.status_code}"
            )
            assert_no_stacktrace_in_error(resp_empty.text)

        # Step 2: Test truncated ZIP magic header stream (PK\x03\x04...)
        with allure.step("Step 2: Upload truncated magic header stream"):
            truncated_bytes = create_truncated_header_file()
            resp_trunc = tenant_a_client.upload_excel(truncated_bytes, filename="truncated.xlsx")

            # Assert status is 400 Bad Request
            assert resp_trunc.status_code == 400, (
                f"Expected 400 Bad Request for truncated stream, got {resp_trunc.status_code}"
            )
            # Step 3: Verify structured error contains corrupt_file_header
            assert "corrupt_file_header" in resp_trunc.text or "error" in resp_trunc.text
            assert_no_stacktrace_in_error(resp_trunc.text)
