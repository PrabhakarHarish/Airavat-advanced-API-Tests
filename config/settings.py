import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    BASE_URL: str = os.getenv("AIRAVAT_BASE_URL", "https://10.20.11.244:3000").rstrip("/")
    USE_MOCK: bool = os.getenv("AIRAVAT_USE_MOCK", "true").lower() in ("true", "1", "yes")
    MOCK_HOST: str = os.getenv("MOCK_HOST", "127.0.0.1")
    MOCK_PORT: int = int(os.getenv("MOCK_PORT", "8008"))
    TENANT_A_USERNAME: str = os.getenv("TENANT_A_USER", "analyst_alpha")
    TENANT_A_PASSWORD: str = os.getenv("TENANT_A_PASS", "SecretAlpha#2026!")
    TENANT_B_USERNAME: str = os.getenv("TENANT_B_USER", "analyst_beta")
    TENANT_B_PASSWORD: str = os.getenv("TENANT_B_PASS", "SecretBeta#2026!")
    VERIFY_SSL: bool = os.getenv("AIRAVAT_VERIFY_SSL", "false").lower() in ("true", "1", "yes")
    REQUEST_TIMEOUT: float = float(os.getenv("AIRAVAT_TIMEOUT", "15.0"))
    RECALCULATION_SLA_MS: float = float(os.getenv("RECALC_SLA_MS", "1500.0"))
    SEARCH_QUERY_SLA_MS: float = float(os.getenv("SEARCH_SLA_MS", "300.0"))
    CIRCULAR_REF_CUTOFF_MS: float = float(os.getenv("CIRCULAR_CUTOFF_MS", "500.0"))

    @property
    def effective_base_url(self) -> str:
        if self.USE_MOCK:
            return f"http://{self.MOCK_HOST}:{self.MOCK_PORT}"
        return self.BASE_URL


_settings_instance = None


def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance
