from typing import Dict, Any, List


def get_valid_pnl_dataset() -> Dict[str, Any]:
    return {
        "statement_type": "PNL",
        "periods": ["Q1", "Q2", "Q3", "Q4", "FY"],
        "line_items": {
            "Operating_Revenue": [100000.15, 200000.25, 300000.35, 400000.45],
            "Direct_Cost": [40000.05, 80000.10, 120000.15, 160000.20],
            "Gross_Profit": [60000.10, 120000.15, 180000.20, 240000.25]
        }
    }


def get_circular_ref_payload() -> Dict[str, Any]:
    return {
        "cells": {
            "A1": {"formula": "=B1 * 1.05", "value": None},
            "B1": {"formula": "=A1 + 100", "value": None}
        }
    }


def get_div_by_zero_payload() -> Dict[str, Any]:
    return {
        "Revenue": 0,
        "Net_Profit": -15000,
        "Gross_Profit": 0,
        "formula": "GrossMargin = GrossProfit / Revenue",
        "target_cell": "C12"
    }


def get_cascade_formula_payload(discount_rate: float = 0.10) -> Dict[str, Any]:
    return {
        "assumptions": {
            "discount_rate": discount_rate,
            "projected_fcf": [5000000, 5500000, 6000000, 6500000, 7000000],
            "shares_outstanding": 10000000,
            "net_debt": 2000000
        }
    }


def get_multi_currency_payload() -> Dict[str, Any]:
    return {
        "reporting_currency": "USD",
        "fx_rates": {
            "EUR": 1.0850,
            "INR": 0.0120,
            "USD": 1.0000
        },
        "subsidiaries": [
            {"entity": "US_HQ", "currency": "USD", "revenue": 1000000.00},
            {"entity": "EU_Branch", "currency": "EUR", "revenue": 850000.00},
            {"entity": "IN_Branch", "currency": "INR", "revenue": 45000000.00}
        ]
    }


def get_model_assumptions_payload() -> Dict[str, Any]:
    return {
        "assumptions": {
            "wacc": 0.085,
            "terminal_growth_rate": 0.03,
            "tax_rate": 0.25
        }
    }


def get_cell_autosave_payload(cell: str = "D18", value: float = 5000000, formula: str = "=D16-D17") -> Dict[str, Any]:
    return {
        "active_cell": cell,
        "changes": [
            {
                "cell": cell,
                "value": value,
                "formula": formula
            }
        ]
    }


def get_heavy_recalc_dataset(periods: int = 60, accounts: int = 150) -> Dict[str, Any]:
    dataset: Dict[str, List[float]] = {}
    for acc_idx in range(accounts):
        account_name = f"Line_Item_{acc_idx + 1:03d}"
        base_val = (acc_idx + 1) * 100.0
        dataset[account_name] = [round(base_val * (1.0 + (p * 0.01)), 2) for p in range(periods)]
    return {
        "model_id": "heavy_perf_model",
        "periods_count": periods,
        "accounts_count": accounts,
        "total_cells": periods * accounts,
        "matrix": dataset
    }


XSS_PAYLOADS = [
    "<script>alert(document.cookie)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:/*--></title></style></textarea></script></xmp><svg/onload='+/'/+/onmouseover=1/+/[*/[]/+alert(1)//'>",
]

FORMULA_INJECTION_PAYLOADS = [
    "=cmd|' /C calc'!A0",
    "@SUM(1+1)*cmd|' /C calc'!A0",
    "-2+3+cmd|' /C calc'!A0",
    "+cmd|' /C calc'!A0",
]
