import io
import re
import json
import time
import html
import zipfile
import threading
from socketserver import ThreadingMixIn
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional

from utils.file_generator import create_valid_financial_workbook


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class MockAiravatHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    db_models: Dict[str, Dict[str, Any]] = {}
    active_sessions: Dict[str, str] = {}
    active_tokens: Dict[str, str] = {}
    idempotency_records: Dict[str, str] = {}
    failed_login_attempts: List[float] = []
    lock = threading.RLock()

    def log_message(self, format, *args):
        return

    def _set_security_headers(self, is_financial: bool = False, is_file: bool = False):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Server", "Airavat-Gateway/1.0")

        if is_financial:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")

    def _send_json(
        self,
        status_code: int,
        data: Any,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[List[str]] = None,
        is_financial: bool = False
    ):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self._set_security_headers(is_financial=is_financial)

        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        if cookies:
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)

        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def _send_bytes(
        self,
        status_code: int,
        data: bytes,
        content_type: str,
        headers: Optional[Dict[str, str]] = None,
        is_financial: bool = False
    ):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self._set_security_headers(is_financial=is_financial, is_file=True)

        if headers:
            for k, v in headers.items():
                self.send_header(k, v)

        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def _parse_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            return b""
        return self.rfile.read(content_length)

    def _parse_json(self) -> Dict[str, Any]:
        raw = self._parse_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _get_auth_user(self) -> str:
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            with MockAiravatHandler.lock:
                if token in MockAiravatHandler.active_tokens:
                    return MockAiravatHandler.active_tokens[token]

        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("sessionid="):
                sess_id = part.split("=", 1)[1]
                with MockAiravatHandler.lock:
                    if sess_id in MockAiravatHandler.active_sessions:
                        return MockAiravatHandler.active_sessions[sess_id]
        return ""

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") + "/"

        if path == "/API/login/":
            now = time.time()
            with MockAiravatHandler.lock:
                MockAiravatHandler.failed_login_attempts = [
                    t for t in MockAiravatHandler.failed_login_attempts if now - t < 5.0
                ]

            data = self._parse_json()
            username = data.get("username")
            password = data.get("password")

            valid_users = {
                "analyst_alpha": "SecretAlpha#2026!",
                "analyst_beta": "SecretBeta#2026!"
            }

            if username in valid_users and valid_users[username] == password:
                token = f"jwt_token_for_{username}_{int(now)}"
                session_id = f"sess_{username}_{int(now)}"
                csrf_token = f"csrf_{int(now)}"

                with MockAiravatHandler.lock:
                    MockAiravatHandler.active_sessions[session_id] = username
                    MockAiravatHandler.active_tokens[token] = username

                cookies = [
                    f"sessionid={session_id}; Path=/; HttpOnly",
                    f"csrftoken={csrf_token}; Path=/"
                ]
                self._send_json(200, {
                    "status": "success",
                    "token": token,
                    "sessionid": session_id,
                    "user": username
                }, cookies=cookies)
                return
            else:
                with MockAiravatHandler.lock:
                    MockAiravatHandler.failed_login_attempts.append(now)
                    num_attempts = len(MockAiravatHandler.failed_login_attempts)

                if num_attempts > 5:
                    self._send_json(429, {"error": "Too Many Requests", "retry_after": 5}, headers={"Retry-After": "5"})
                    return
                else:
                    self._send_json(401, {"error": "Invalid credentials"})
                    return

        if path == "/API/get-preferred-profile/":
            user = self._get_auth_user()
            if not user:
                self._send_json(401, {"error": "Unauthorized"})
                return
            self._send_json(200, {"username": user, "role": "financial_analyst"})
            return

        if path == "/API/excel/upload/":
            raw_body = self._parse_body()

            if (
                b'filename="empty.xlsx"' in raw_body
                or b'filename="truncated.xlsx"' in raw_body
                or len(raw_body) < 20
            ):
                self._send_json(400, {
                    "error": "corrupt_file_header",
                    "message": "Zero-byte or truncated header stream rejected"
                })
                return

            if b"zip_bomb" in raw_body:
                self._send_json(413, {"error": "Payload Too Large: Decompression limit exceeded"})
                return

            if b"<!ENTITY xxe SYSTEM" in raw_body or b"/etc/passwd" in raw_body:
                self._send_json(200, {"upload_id": "tpl_xxe_safe", "sheets": ["sanitized_sheet"]})
                return

            upload_id = f"tpl_{int(time.time() * 1000)}"
            self._send_json(200, {"upload_id": upload_id, "status": "UPLOADED"})
            return

        if path == "/API/excel/validate-pnl/":
            self._send_json(200, {
                "reconciliation_status": "BALANCED",
                "variance": 0.00
            }, is_financial=True)
            return

        if path == "/API/excel/convert-to-model/":
            data = self._parse_json()
            template_id = data.get("template_id", "")
            if "corrupt" in template_id or data.get("corrupted", False):
                self._send_json(422, {
                    "error": "PARSE_ERROR",
                    "sheet": "Balance Sheet",
                    "row": 42,
                    "message": "Malformed OpenXML markup at row 42"
                })
                return

            user = self._get_auth_user() or "analyst_alpha"
            model_id = f"model_{int(time.time() * 1000) % 100000}"
            model_record = {
                "id": model_id,
                "name": data.get("name", "Financial_Model"),
                "owner": user,
                "version": 1,
                "revenue": 1000000,
                "assumptions": {},
                "cells": {"D18": {"value": 5000000, "formula": "=D16-D17"}},
                "updated_at": time.time()
            }
            with MockAiravatHandler.lock:
                MockAiravatHandler.db_models[model_id] = model_record

            self._send_json(200, {
                "model_id": model_id,
                "status": "CREATED",
                "name": model_record["name"]
            }, is_financial=True)
            return

        if path == "/API/models/":
            cookie = self.headers.get("Cookie", "")
            if "sessionid=" in cookie and not self.headers.get("X-CSRFToken"):
                self._send_json(403, {"detail": "CSRF Failed: CSRF cookie not set or missing header"})
                return

            idempotency_key = self.headers.get("Idempotency-Key")
            data = self._parse_json()
            user = self._get_auth_user() or "analyst_alpha"
            existing_id = None
            is_idempotent = False

            with MockAiravatHandler.lock:
                if idempotency_key and idempotency_key in MockAiravatHandler.idempotency_records:
                    existing_id = MockAiravatHandler.idempotency_records[idempotency_key]
                    is_idempotent = True
                else:
                    raw_name = data.get("name", "New Model")
                    sanitized_name = html.escape(raw_name)
                    new_id = f"model_{int(time.time() * 1000) % 100000}"
                    MockAiravatHandler.db_models[new_id] = {
                        "id": new_id,
                        "name": sanitized_name,
                        "owner": user,
                        "version": 1,
                        "revenue": 1000000,
                        "assumptions": {},
                        "cells": {},
                        "updated_at": time.time()
                    }
                    if idempotency_key:
                        MockAiravatHandler.idempotency_records[idempotency_key] = new_id

            if is_idempotent:
                self._send_json(200, {
                    "model_id": existing_id,
                    "status": "IDEMPOTENT_MATCH",
                    "message": "Model previously created with this idempotency key"
                })
                return

            self._send_json(201, {"model_id": new_id, "name": sanitized_name, "status": "CREATED"})
            return

        m_auto = re.match(r"^/API/models/([^/]+)/autosave/$", path)
        if m_auto:
            model_id = m_auto.group(1)
            data = self._parse_json()
            changes = data.get("changes", [])

            has_circular = False
            formula_refs = {}
            for ch in changes:
                cell = ch.get("cell")
                formula = ch.get("formula") or ""
                formula_refs[cell] = formula
                if "CIRCULAR" in formula:
                    has_circular = True

            if "A1" in formula_refs and "B1" in formula_refs:
                if "B1" in formula_refs["A1"] and "A1" in formula_refs["B1"]:
                    has_circular = True

            if has_circular:
                self._send_json(400, {
                    "status": "CIRCULAR_DEPENDENCY_ERROR",
                    "cycle_path": ["A1", "B1", "A1"]
                })
                return

            with MockAiravatHandler.lock:
                if model_id not in MockAiravatHandler.db_models:
                    MockAiravatHandler.db_models[model_id] = {
                        "id": model_id,
                        "cells": {},
                        "owner": "analyst_alpha",
                        "version": 1
                    }
                model = MockAiravatHandler.db_models[model_id]
                for ch in changes:
                    cell_name = ch.get("cell")
                    model["cells"][cell_name] = {"value": ch.get("value"), "formula": ch.get("formula")}
                model["updated_at"] = time.time()

            self._send_json(200, {
                "status": "SAVED",
                "active_cell": data.get("active_cell"),
                "updated_at": time.time()
            }, is_financial=True)
            return

        m_dup = re.match(r"^/API/models/([^/]+)/duplicate/$", path)
        if m_dup:
            src_id = m_dup.group(1)
            data = self._parse_json()
            new_name = data.get("new_name", "Branched_Model")
            with MockAiravatHandler.lock:
                src_model = MockAiravatHandler.db_models.get(
                    src_id, {"revenue": 1000000, "owner": "analyst_alpha", "cells": {}}
                )
                new_id = f"model_branch_{int(time.time() * 1000) % 100000}"
                MockAiravatHandler.db_models[new_id] = {
                    "id": new_id,
                    "name": new_name,
                    "owner": src_model.get("owner", "analyst_alpha"),
                    "revenue": src_model.get("revenue", 1000000),
                    "version": 1,
                    "parent_id": src_id,
                    "cells": dict(src_model.get("cells", {}))
                }

            self._send_json(200, {"model_id": new_id, "name": new_name, "parent_id": src_id})
            return

        m_recalc = re.match(r"^/API/models/([^/]+)/recalculate/$", path)
        if m_recalc:
            data = self._parse_json()
            line_items = data.get("line_items", {})
            if "Operating_Revenue" in line_items:
                cost_list = line_items.get("Direct_Cost", [0])
                total_cost = round(sum(cost_list), 4)
                gp_list = line_items.get("Gross_Profit", [0])
                total_gp = round(sum(gp_list), 4)

                self._send_json(200, {
                    "statement_type": "PNL",
                    "totals": {
                        "Operating_Revenue": 1000001.20,
                        "Direct_Cost": total_cost,
                        "Gross_Profit": total_gp
                    },
                    "variance": 0.0000
                }, is_financial=True)
                return

            if data.get("Revenue") == 0:
                self._send_json(200, {
                    "cell": data.get("target_cell", "C12"),
                    "error": "#DIV/0!",
                    "display": "N/A"
                }, is_financial=True)
                return

            if "subsidiaries" in data:
                fx = data.get("fx_rates", {})
                total_usd = 0.0
                for sub in data["subsidiaries"]:
                    curr = sub["currency"]
                    total_usd += sub["revenue"] * fx.get(curr, 1.0)
                self._send_json(200, {
                    "reporting_currency": "USD",
                    "consolidated_revenue": round(total_usd, 2),
                    "status": "RECONCILED"
                }, is_financial=True)
                return

            if "matrix" in data:
                self._send_json(200, {
                    "status": "RECALCULATED",
                    "cells_evaluated": data.get("total_cells", 9000),
                    "execution_time_ms": 120.5
                }, is_financial=True)
                return

            self._send_json(200, {"status": "RECALCULATED"}, is_financial=True)
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") + "/"
        current_user = self._get_auth_user()

        if path == "/API/logout/":
            auth_header = self.headers.get("Authorization", "")
            with MockAiravatHandler.lock:
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ", 1)[1]
                    MockAiravatHandler.active_tokens.pop(token, None)
                cookie_header = self.headers.get("Cookie", "")
                for part in cookie_header.split(";"):
                    part = part.strip()
                    if part.startswith("sessionid="):
                        sess_id = part.split("=", 1)[1]
                        MockAiravatHandler.active_sessions.pop(sess_id, None)

            self._send_json(200, {"message": "Logged out successfully"})
            return

        m_exp = re.match(r"^/API/models/([^/]+)/export/excel/$", path)
        if m_exp:
            model_id = m_exp.group(1)
            model = MockAiravatHandler.db_models.get(model_id)

            if model and model.get("owner") and current_user and model["owner"] != current_user:
                self._send_json(403, {"error": "Forbidden: Tenant mismatch on export"})
                return

            buf = create_valid_financial_workbook()
            excel_bytes = buf.getvalue()

            self._send_bytes(
                200,
                excel_bytes,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename=model_{model_id}_export.xlsx"},
                is_financial=True
            )
            return

        m_mod = re.match(r"^/API/models/([^/]+)/$", path)
        if m_mod:
            model_id = m_mod.group(1)
            model = MockAiravatHandler.db_models.get(model_id)

            if model and model.get("owner") and current_user and model["owner"] != current_user:
                self._send_json(403, {"error": "Forbidden: Tenant isolation violation"})
                return

            if not model:
                model = {
                    "id": model_id,
                    "name": "Default_Model",
                    "owner": current_user or "analyst_alpha",
                    "revenue": 1000000,
                    "version": 5,
                    "cells": {
                        "C5": {"value": "1000"},
                        "D5": {"value": "2000"},
                        "D18": {"value": 5000000, "formula": "=D16-D17"}
                    }
                }

            self._send_json(200, model, is_financial=True)
            return

        if path == "/API/models/":
            self._send_json(200, {
                "count": len(MockAiravatHandler.db_models),
                "results": list(MockAiravatHandler.db_models.values())
            })
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") + "/"
        current_user = self._get_auth_user()

        m_mod = re.match(r"^/API/models/([^/]+)/$", path)
        if m_mod:
            model_id = m_mod.group(1)
            data = self._parse_json()
            model = MockAiravatHandler.db_models.get(model_id)

            incoming_version = data.get("version")
            if incoming_version is not None:
                current_server_version = model.get("version", 5) if model else 5
                if incoming_version < current_server_version:
                    self._send_json(409, {
                        "error": "Conflict",
                        "message": "Stale version update rejected",
                        "server_version": current_server_version,
                        "diff": {"version_conflict": True}
                    })
                    return

            if model and model.get("owner") and current_user and model["owner"] != current_user:
                self._send_json(403, {"error": "Forbidden: Tenant isolation violation"})
                return

            assumptions = data.get("assumptions", {})
            if "discount_rate" in assumptions:
                dr = assumptions["discount_rate"]
                tier1_df = round(1.0 / (1.0 + dr), 4)
                tier2_pv = round(25000000.0 * tier1_df, 2)
                tier3_ev = round(tier2_pv + 5000000.0, 2)
                tier4_price = round((tier3_ev - 2000000.0) / 1000000.0, 2)

                self._send_json(200, {
                    "model_id": model_id,
                    "tier0_discount_rate": dr,
                    "tier1_discount_factor": tier1_df,
                    "tier2_present_value_fcf": tier2_pv,
                    "tier3_enterprise_value": tier3_ev,
                    "tier4_target_share_price": tier4_price,
                    "status": "ATOMIC_CASCADE_SUCCESS"
                }, is_financial=True)
                return

            with MockAiravatHandler.lock:
                if not model:
                    model = {"id": model_id, "owner": current_user or "analyst_alpha", "version": 5}
                    MockAiravatHandler.db_models[model_id] = model
                model.update(data)
                model["version"] = model.get("version", 5) + 1
                if "revenue" in data:
                    model["revenue"] = data["revenue"]

            self._send_json(200, {
                "model_id": model_id,
                "status": "UPDATED",
                "version": model["version"],
                "enterprise_value": 45000000.0,
                "equity_value": 38000000.0,
                "revenue": model.get("revenue")
            }, is_financial=True)
            return

        self._send_json(404, {"error": "Endpoint not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") + "/"
        current_user = self._get_auth_user()

        m_mod = re.match(r"^/API/models/([^/]+)/$", path)
        if m_mod:
            model_id = m_mod.group(1)
            model = MockAiravatHandler.db_models.get(model_id)

            if model and model.get("owner") and current_user and model["owner"] != current_user:
                self._send_json(403, {"error": "Forbidden: Tenant isolation violation"})
                return

            with MockAiravatHandler.lock:
                MockAiravatHandler.db_models.pop(model_id, None)

            self.send_response(204)
            self.send_header("Connection", "close")
            self._set_security_headers()
            self.end_headers()
            self.close_connection = True
            return

        self._send_json(404, {"error": "Endpoint not found"})


class MockAiravatServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8008):
        self.host = host
        self.port = port
        self.server = ThreadedHTTPServer((self.host, self.port), MockAiravatHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
