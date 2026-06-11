from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ReceiptPeriodInput:
    period: str
    consumption_kwh: float
    average_price_mxn_kwh: float
    demand_kw: float | None = None
    power_factor_percent: float | None = None


def suggest_industrial_tariff_family(contracted_demand_kw: float) -> str:
    """Suggest GDMTO/GDMTH from contracted demand without using location-specific data."""
    demand = max(float(contracted_demand_kw), 0.0)
    return "GDMTO" if demand < 100.0 else "GDMTH"


def _coerce_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _period_from_mapping(raw_period: Mapping[str, object]) -> ReceiptPeriodInput:
    return ReceiptPeriodInput(
        period=str(raw_period.get("period", raw_period.get("Periodo", ""))).strip(),
        consumption_kwh=max(
            _coerce_float(
                raw_period.get(
                    "consumption_kwh",
                    raw_period.get("Consumo total kWh", raw_period.get("Consumo kWh", 0.0)),
                )
            ),
            0.0,
        ),
        average_price_mxn_kwh=max(
            _coerce_float(
                raw_period.get(
                    "average_price_mxn_kwh",
                    raw_period.get("Precio medio MXN/kWh", 0.0),
                )
            ),
            0.0,
        ),
        demand_kw=(
            max(_coerce_float(raw_period.get("demand_kw", raw_period.get("Demanda kW"))), 0.0)
            if raw_period.get("demand_kw", raw_period.get("Demanda kW")) is not None
            else None
        ),
        power_factor_percent=(
            max(
                _coerce_float(
                    raw_period.get(
                        "power_factor_percent",
                        raw_period.get("Factor de potencia %"),
                    )
                ),
                0.0,
            )
            if raw_period.get("power_factor_percent", raw_period.get("Factor de potencia %")) is not None
            else None
        ),
    )


def _normalize_periods(periods: Iterable[ReceiptPeriodInput | Mapping[str, object]]) -> list[ReceiptPeriodInput]:
    normalized: list[ReceiptPeriodInput] = []
    for period in periods:
        if isinstance(period, ReceiptPeriodInput):
            normalized.append(period)
        else:
            normalized.append(_period_from_mapping(period))
    return [
        period
        for period in normalized
        if period.consumption_kwh > 0.0 and period.average_price_mxn_kwh >= 0.0
    ]


def compute_receipt_based_savings(
    periods: Iterable[ReceiptPeriodInput | Mapping[str, object]],
    annual_generation_kwh: float,
    period_frequency: str = "Mensual",
) -> dict[str, object]:
    """Summarize receipt periods and estimate annual savings with average billed price."""
    valid_periods = _normalize_periods(periods)
    periods_per_year = 6 if str(period_frequency).lower().startswith("bim") else 12
    captured_periods = len(valid_periods)

    period_results = [
        {
            "period": period.period,
            "consumption_kwh": period.consumption_kwh,
            "average_price_mxn_kwh": period.average_price_mxn_kwh,
            "estimated_cost_without_pv_mxn": period.consumption_kwh * period.average_price_mxn_kwh,
            "demand_kw": period.demand_kw,
            "power_factor_percent": period.power_factor_percent,
        }
        for period in valid_periods
    ]

    captured_consumption = sum(period["consumption_kwh"] for period in period_results)
    captured_cost = sum(period["estimated_cost_without_pv_mxn"] for period in period_results)
    projection_factor = (periods_per_year / captured_periods) if 0 < captured_periods < periods_per_year else 1.0
    analysis_type = "Histórico anual" if captured_periods >= periods_per_year else "Proyección anual"

    annual_consumption = captured_consumption * projection_factor
    annual_cost_without_pv = captured_cost * projection_factor
    generation = max(float(annual_generation_kwh), 0.0)
    self_consumed = min(annual_consumption, generation)
    grid_energy = max(annual_consumption - generation, 0.0)
    exported = max(generation - annual_consumption, 0.0)
    average_price = annual_cost_without_pv / annual_consumption if annual_consumption > 0.0 else 0.0
    annual_cost_with_pv = grid_energy * average_price
    annual_savings = max(annual_cost_without_pv - annual_cost_with_pv, 0.0)
    savings_pct = (annual_savings / annual_cost_without_pv * 100.0) if annual_cost_without_pv > 0.0 else 0.0
    coverage_pct = (self_consumed / annual_consumption * 100.0) if annual_consumption > 0.0 else 0.0

    return {
        "analysis_type": analysis_type,
        "period_frequency": "Bimestral" if periods_per_year == 6 else "Mensual",
        "captured_periods": captured_periods,
        "periods_per_year": periods_per_year,
        "projection_factor": projection_factor,
        "period_results": period_results,
        "annual_consumption_kWh": annual_consumption,
        "annual_cost_without_pv_mxn": annual_cost_without_pv,
        "annual_generation_kWh": generation,
        "self_consumed_kWh": self_consumed,
        "grid_energy_kWh": grid_energy,
        "exported_kWh": exported,
        "weighted_average_price_mxn_kwh": average_price,
        "annual_cost_with_pv_mxn": annual_cost_with_pv,
        "annual_savings_mxn": annual_savings,
        "annual_savings_percent": savings_pct,
        "solar_coverage_percent": coverage_pct,
    }
