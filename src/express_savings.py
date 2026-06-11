from __future__ import annotations


def _as_non_negative_float(value: float, name: str) -> float:
    number = float(value)
    if number < 0.0:
        raise ValueError(f"{name} must be non-negative.")
    return number


def compute_express_savings(
    annual_consumption_kwh: float,
    annual_generation_kwh: float,
    average_cost_mxn_kwh: float | None = None,
    economic_enabled: bool = False,
) -> dict[str, float | None]:
    """Return an annual express energy and savings estimate.

    This simplified estimate compares annual PV generation against annual
    consumption. It intentionally excludes tariff periods, demand charges,
    fixed charges, IVA and power-factor effects.
    """
    annual_consumption = _as_non_negative_float(annual_consumption_kwh, "annual_consumption_kwh")
    annual_generation = _as_non_negative_float(annual_generation_kwh, "annual_generation_kwh")

    self_consumed = min(annual_generation, annual_consumption)
    grid_energy = max(annual_consumption - annual_generation, 0.0)
    exported = max(annual_generation - annual_consumption, 0.0)
    coverage = 100.0 * self_consumed / annual_consumption if annual_consumption > 0.0 else 0.0

    current_annual_cost: float | None = None
    annual_cost_with_pv: float | None = None
    annual_savings: float | None = None
    savings_pct: float | None = None

    if economic_enabled and average_cost_mxn_kwh is not None:
        average_cost = _as_non_negative_float(average_cost_mxn_kwh, "average_cost_mxn_kwh")
        current_annual_cost = annual_consumption * average_cost
        annual_cost_with_pv = grid_energy * average_cost
        annual_savings = current_annual_cost - annual_cost_with_pv
        savings_pct = 100.0 * annual_savings / current_annual_cost if current_annual_cost > 0.0 else 0.0

    return {
        "annual_consumption_kWh": annual_consumption,
        "annual_generation_kWh": annual_generation,
        "self_consumed_kWh": self_consumed,
        "grid_energy_kWh": grid_energy,
        "exported_kWh": exported,
        "solar_coverage_pct": coverage,
        "current_annual_cost": current_annual_cost,
        "annual_cost_with_pv": annual_cost_with_pv,
        "annual_savings": annual_savings,
        "savings_pct": savings_pct,
    }