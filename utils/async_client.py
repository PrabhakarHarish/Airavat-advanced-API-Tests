import httpx
from typing import Dict, Any, Optional


class AiravatAsyncClient:
    def __init__(self, base_url: str, cookies: Optional[Dict[str, str]] = None, headers: Optional[Dict[str, str]] = None):
        self.base_url = base_url.rstrip("/")
        self.default_headers = headers or {}
        self.default_cookies = cookies or {}

    async def autosave(self, client: httpx.AsyncClient, model_id: str, cell: str, value: Any, formula: Optional[str] = None) -> httpx.Response:
        url = f"{self.base_url}/API/models/{model_id}/autosave/"
        payload = {
            "active_cell": cell,
            "changes": [{"cell": cell, "value": value, "formula": formula}]
        }
        return await client.post(url, json=payload)

    async def upload_file(self, client: httpx.AsyncClient, file_bytes: bytes, filename: str) -> httpx.Response:
        url = f"{self.base_url}/API/excel/upload/"
        files = {"file": (filename, file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        return await client.post(url, files=files)

    async def create_model_with_idempotency(self, client: httpx.AsyncClient, idempotency_key: str, payload: Dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}/API/models/"
        headers = {"Idempotency-Key": idempotency_key}
        return await client.post(url, json=payload, headers=headers)
