import time
import json
import logging
import requests
import allure
from typing import Optional, Dict, Any, Union

logger = logging.getLogger("airavat.client")


class AiravatApiClient:
    def __init__(self, base_url: str, verify_ssl: bool = False, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.auth_token: Optional[str] = None
        self.session_id: Optional[str] = None
        self.csrf_token: Optional[str] = None

    def _sync_csrf_headers(self) -> None:
        csrf = self.session.cookies.get("csrftoken")
        if csrf:
            self.csrf_token = csrf
            self.session.headers.update({"X-CSRFToken": csrf})

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], bytes]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        files: Optional[Dict[str, Any]] = None,
        stream: bool = False
    ) -> requests.Response:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        self._sync_csrf_headers()

        req_headers = dict(self.session.headers)
        if headers:
            req_headers.update(headers)

        start_time = time.perf_counter()
        with allure.step(f"API {method.upper()} {endpoint}"):
            try:
                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    data=data,
                    json=json_data,
                    headers=req_headers,
                    files=files,
                    timeout=self.timeout,
                    stream=stream
                )
            except requests.RequestException as exc:
                allure.attach(str(exc), name="Request Error", attachment_type=allure.attachment_type.TEXT)
                raise

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            response.elapsed_ms = elapsed_ms

            allure.attach(
                json.dumps({
                    "url": url,
                    "method": method.upper(),
                    "status_code": response.status_code,
                    "elapsed_ms": f"{elapsed_ms:.2f} ms",
                    "request_headers": dict(req_headers),
                    "request_payload": json_data if json_data else (str(data)[:200] if data else None),
                }, indent=2),
                name="HTTP Request Details",
                attachment_type=allure.attachment_type.JSON
            )

            if not stream and "application/json" in response.headers.get("Content-Type", ""):
                allure.attach(response.text, name="HTTP Response JSON", attachment_type=allure.attachment_type.JSON)
            elif not stream:
                allure.attach(response.text[:2000], name="HTTP Response Body", attachment_type=allure.attachment_type.TEXT)

            self._sync_csrf_headers()
            return response

    def get(self, endpoint: str, **kwargs) -> requests.Response:
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> requests.Response:
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> requests.Response:
        return self.request("PUT", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs) -> requests.Response:
        return self.request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> requests.Response:
        return self.request("DELETE", endpoint, **kwargs)

    def login(self, username: str, password: str) -> requests.Response:
        payload = {"username": username, "password": password}
        response = self.post("/API/login/", json_data=payload)
        if response.status_code == 200:
            data = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
            token = data.get("token") or data.get("access_token")
            if token:
                self.auth_token = token
                self.session.headers.update({"Authorization": f"Bearer {token}"})
            self.session_id = self.session.cookies.get("sessionid")
            self._sync_csrf_headers()
        return response

    def logout(self) -> requests.Response:
        response = self.get("/API/logout/")
        self.auth_token = None
        self.session_id = None
        self.session.headers.pop("Authorization", None)
        return response

    def upload_excel(self, file_content: bytes, filename: str = "Base_Template.xlsx") -> requests.Response:
        files = {
            "file": (filename, file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        }
        return self.post("/API/excel/upload/", files=files)

    def validate_pnl(self, template_id: str) -> requests.Response:
        return self.post("/API/excel/validate-pnl/", json_data={"template_id": template_id})

    def convert_to_model(self, template_id: str, name: str) -> requests.Response:
        return self.post("/API/excel/convert-to-model/", json_data={"template_id": template_id, "name": name})

    def get_model(self, model_id: str) -> requests.Response:
        return self.get(f"/API/models/{model_id}/")

    def update_model(self, model_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self.put(f"/API/models/{model_id}/", json_data=payload, headers=headers)

    def autosave_cell(self, model_id: str, cell: str, value: Any, formula: Optional[str] = None) -> requests.Response:
        payload = {
            "active_cell": cell,
            "changes": [{"cell": cell, "value": value, "formula": formula}]
        }
        return self.post(f"/API/models/{model_id}/autosave/", json_data=payload)

    def export_excel(self, model_id: str) -> requests.Response:
        return self.get(f"/API/models/{model_id}/export/excel/", stream=True)

    def duplicate_model(self, model_id: str, new_name: str) -> requests.Response:
        return self.post(f"/API/models/{model_id}/duplicate/", json_data={"new_name": new_name})

    def delete_model(self, model_id: str) -> requests.Response:
        return self.delete(f"/API/models/{model_id}/")

    def recalculate(self, model_id: str, payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self.post(f"/API/models/{model_id}/recalculate/", json_data=payload or {})

    def get_preferred_profile(self) -> requests.Response:
        return self.post("/API/get-preferred-profile")
