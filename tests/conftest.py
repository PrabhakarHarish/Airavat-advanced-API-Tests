"""
Pytest Configuration and Shared Fixtures for Air-avat  API Testing.
Provides authenticated clients, test data generators, and mock server lifecycle.
"""
import pytest
import time
from typing import Generator
from config.settings import get_settings, Settings
from utils.api_client import AiravatApiClient
from utils.file_generator import create_valid_financial_workbook
from mock_server.airavat_mock_api import MockAiravatServer


def pytest_addoption(parser):
    """Adds CLI options for live vs mock execution."""
    parser.addoption(
        "--live", action="store_true", default=False,
        help="Run tests against live Airavat backend instead of mock server."
    )
    parser.addoption(
        "--mock", action="store_true", default=False,
        help="Force running tests against built-in mock server."
    )


@pytest.fixture(scope="session")
def settings(request) -> Settings:
    """
    Session-level configuration settings.
    Overrides USE_MOCK based on CLI flags.
    """
    conf = get_settings()
    if request.config.getoption("--live"):
        conf.USE_MOCK = False
    elif request.config.getoption("--mock"):
        conf.USE_MOCK = True
    return conf


@pytest.fixture(scope="session", autouse=True)
def mock_server(settings: Settings) -> Generator[None, None, None]:
    """
    Automatically spins up the local high-fidelity mock server if USE_MOCK is True.
    """
    if not settings.USE_MOCK:
        yield
        return

    server = MockAiravatServer(host=settings.MOCK_HOST, port=settings.MOCK_PORT)
    server.start()
    # Allow socket to bind
    time.sleep(0.1)
    yield
    server.stop()


@pytest.fixture
def unauth_client(settings: Settings) -> AiravatApiClient:
    """
    Returns an unauthenticated client.
    """
    return AiravatApiClient(
        base_url=settings.effective_base_url,
        verify_ssl=settings.VERIFY_SSL,
        timeout=settings.REQUEST_TIMEOUT
    )


@pytest.fixture
def tenant_a_client(settings: Settings) -> AiravatApiClient:
    """
    Returns an authenticated client for Tenant A (Primary Analyst: analyst_alpha).
    """
    client = AiravatApiClient(
        base_url=settings.effective_base_url,
        verify_ssl=settings.VERIFY_SSL,
        timeout=settings.REQUEST_TIMEOUT
    )
    resp = client.login(settings.TENANT_A_USERNAME, settings.TENANT_A_PASSWORD)
    assert resp.status_code == 200, f"Tenant A authentication failed: {resp.text}"
    return client


@pytest.fixture
def tenant_b_client(settings: Settings) -> AiravatApiClient:
    """
    Returns an authenticated client for Tenant B (Secondary Analyst: analyst_beta).
    Used for IDOR and tenant boundary testing.
    """
    client = AiravatApiClient(
        base_url=settings.effective_base_url,
        verify_ssl=settings.VERIFY_SSL,
        timeout=settings.REQUEST_TIMEOUT
    )
    resp = client.login(settings.TENANT_B_USERNAME, settings.TENANT_B_PASSWORD)
    assert resp.status_code == 200, f"Tenant B authentication failed: {resp.text}"
    return client


@pytest.fixture
def sample_excel_bytes() -> bytes:
    """
    Generates a byte buffer of a valid 3-statement financial workbook.
    """
    buf = create_valid_financial_workbook()
    return buf.getvalue()


@pytest.fixture
def tenant_a_model(tenant_a_client: AiravatApiClient, sample_excel_bytes: bytes) -> Generator[str, None, None]:
    """
    Fixture that creates a live model under Tenant A and ensures cleanup during teardown.
    """
    # 1. Ingest template
    upload_resp = tenant_a_client.upload_excel(sample_excel_bytes)
    assert upload_resp.status_code == 200
    upload_id = upload_resp.json().get("upload_id")

    # 2. Convert to model
    model_resp = tenant_a_client.convert_to_model(upload_id, "Tenant_A_Base_Model")
    assert model_resp.status_code == 200
    model_id = model_resp.json().get("model_id")

    yield model_id

    # 3. Teardown
    tenant_a_client.delete_model(model_id)
