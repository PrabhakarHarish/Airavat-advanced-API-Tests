from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Union


def assert_financial_precision(
    actual: Union[float, int, str, Decimal],
    expected: Union[float, int, str, Decimal],
    decimal_places: int = 4,
    tolerance: float = 0.0001
) -> None:
    d_actual = Decimal(str(actual)).quantize(Decimal(f"1e-{decimal_places}"), rounding=ROUND_HALF_UP)
    d_expected = Decimal(str(expected)).quantize(Decimal(f"1e-{decimal_places}"), rounding=ROUND_HALF_UP)
    difference = abs(float(d_actual - d_expected))
    assert difference <= tolerance, (
        f"Financial Precision Failure: Expected {d_expected}, got {d_actual} (diff={difference} > {tolerance})"
    )


def assert_security_headers(headers: Dict[str, str], is_financial_endpoint: bool = False) -> None:
    headers_lower = {k.lower(): v for k, v in headers.items()}

    assert headers_lower.get("x-content-type-options") == "nosniff", (
        f"Missing or invalid X-Content-Type-Options: {headers_lower.get('x-content-type-options')}"
    )

    xfo = headers_lower.get("x-frame-options", "").upper()
    assert xfo in ("DENY", "SAMEORIGIN"), (
        f"Missing or insecure X-Frame-Options: {xfo}"
    )

    hsts = headers_lower.get("strict-transport-security", "")
    assert "max-age" in hsts, f"Missing HSTS header: {hsts}"

    if is_financial_endpoint:
        cache_control = headers_lower.get("cache-control", "").lower()
        assert "no-store" in cache_control or "no-cache" in cache_control, (
            f"Financial endpoint response must not be cached! Cache-Control: {cache_control}"
        )


def assert_no_server_leakage(headers: Dict[str, str]) -> None:
    headers_lower = {k.lower(): v for k, v in headers.items()}
    server_header = headers_lower.get("server", "")
    assert "cpython" not in server_header.lower(), (
        f"Information Disclosure Vulnerability: Server header reveals CPython version: {server_header}"
    )
    assert "wsgiserver" not in server_header.lower(), (
        f"Information Disclosure Vulnerability: Server header reveals WSGIServer details: {server_header}"
    )


def assert_no_stacktrace_in_error(response_body: Union[str, Dict[str, Any]]) -> None:
    body_str = str(response_body).lower()
    dangerous_keywords = [
        "traceback (most recent call last)",
        "django.core.exceptions",
        "operationalerror",
        "syntaxerror at or near",
        "/home/",
        "c:\\users\\",
        "wsgi.py",
        "models.py"
    ]
    for kw in dangerous_keywords:
        assert kw not in body_str, f"Information leakage detected in error response! Keyword found: '{kw}'"


def assert_xss_sanitized(content: str) -> None:
    lower_content = content.lower()
    assert "<script" not in lower_content, f"Unsanitized raw <script> tag found in content: {content}"
    assert "<img" not in lower_content, f"Unsanitized raw <img> tag found in content: {content}"
    assert "<svg" not in lower_content, f"Unsanitized raw <svg> tag found in content: {content}"
    if "img" in lower_content or "script" in lower_content:
        assert ("&lt;" in content and "&gt;" in content) or ("<" not in content and ">" not in content), (
            f"Content was neither escaped nor stripped: {content}"
        )


def assert_formula_sanitized(exported_cell_value: str) -> None:
    if not exported_cell_value:
        return
    for trigger in ("=cmd", "@cmd", "+cmd", "-cmd", "=SUM"):
        if exported_cell_value.startswith(trigger):
            raise AssertionError(f"Formula Injection vulnerability! Raw executable formula exported: {exported_cell_value}")
