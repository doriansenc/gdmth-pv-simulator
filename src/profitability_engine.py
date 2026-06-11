from __future__ import annotations


def _as_float(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    return number


def _non_negative(value: float, name: str) -> float:
    number = _as_float(value, name)
    if number < 0.0:
        raise ValueError(f"{name} must be non-negative.")
    return number


def _fraction(value: float, name: str) -> float:
    number = _as_float(value, name)
    if number < 0.0 or number > 1.0:
        raise ValueError(f"{name} must be between 0 and 1.")
    return number


def percent_to_fraction(value: float, name: str, max_percent: float = 100.0) -> float:
    """Convert a visible percent value such as 90 into its internal fraction."""
    percent = _as_float(value, name)
    max_value = _as_float(max_percent, "max_percent")
    if max_value <= 0.0:
        raise ValueError("max_percent must be greater than 0.")
    if percent < 0.0 or percent > max_value:
        raise ValueError(f"{name} must be between 0 and {max_value}.")
    return percent / 100.0


def calculate_profitability(
    annual_outage_events: float,
    annual_outage_hours: float,
    outage_cost_per_hour: float,
    fixed_cost_per_outage: float,
    annual_repairs_or_damage_cost: float,
    avoidable_loss_fraction: float,
    recommended_batteries: float,
    battery_unit_cost: float,
    balance_of_system_mode: str,
    balance_of_system_percentage: float,
    balance_of_system_manual_cost: float,
    include_pv_investment: bool,
    pv_investment_cost: float,
    include_energy_savings: bool,
    annual_energy_savings: float,
) -> dict[str, float | None]:
    """Return a simple annual profitability estimate for backup investment."""
    events = _non_negative(annual_outage_events, "annual_outage_events")
    hours = _non_negative(annual_outage_hours, "annual_outage_hours")
    hourly_cost = _non_negative(outage_cost_per_hour, "outage_cost_per_hour")
    event_cost = _non_negative(fixed_cost_per_outage, "fixed_cost_per_outage")
    repairs = _non_negative(annual_repairs_or_damage_cost, "annual_repairs_or_damage_cost")
    avoidable_fraction = _fraction(avoidable_loss_fraction, "avoidable_loss_fraction")
    batteries = _non_negative(recommended_batteries, "recommended_batteries")
    unit_cost = _non_negative(battery_unit_cost, "battery_unit_cost")
    bos_percentage = _fraction(balance_of_system_percentage, "balance_of_system_percentage")
    bos_manual = _non_negative(balance_of_system_manual_cost, "balance_of_system_manual_cost")
    pv_cost = _non_negative(pv_investment_cost, "pv_investment_cost")
    energy_savings = _non_negative(annual_energy_savings, "annual_energy_savings")

    annual_downtime_cost = hourly_cost * hours
    annual_event_cost = event_cost * events
    annual_inaction_cost = annual_downtime_cost + annual_event_cost + repairs
    avoidable_losses = annual_inaction_cost * avoidable_fraction

    battery_total_cost = batteries * unit_cost
    normalized_mode = str(balance_of_system_mode).strip().lower()
    if normalized_mode in {"porcentaje", "percentage", "percent"}:
        balance_of_system_cost = battery_total_cost * bos_percentage
    elif normalized_mode in {"monto manual", "manual", "mxn"}:
        balance_of_system_cost = bos_manual
    else:
        raise ValueError("balance_of_system_mode must be percentage or manual.")

    bess_investment = battery_total_cost + balance_of_system_cost
    pv_investment = pv_cost if include_pv_investment else 0.0
    total_investment = bess_investment + pv_investment
    annual_energy_savings_value = energy_savings if include_energy_savings else 0.0
    annual_total_benefit = avoidable_losses + annual_energy_savings_value

    simple_payback_years = (
        total_investment / annual_total_benefit
        if total_investment > 0.0 and annual_total_benefit > 0.0
        else None
    )
    simple_roi_pct = (
        annual_total_benefit / total_investment * 100.0
        if total_investment > 0.0
        else None
    )

    return {
        "annual_outage_events": events,
        "annual_outage_hours": hours,
        "annual_downtime_cost": annual_downtime_cost,
        "annual_event_cost": annual_event_cost,
        "annual_inaction_cost": annual_inaction_cost,
        "avoidable_losses": avoidable_losses,
        "recommended_batteries": batteries,
        "battery_unit_cost": unit_cost,
        "battery_total_cost": battery_total_cost,
        "balance_of_system_cost": balance_of_system_cost,
        "bess_investment": bess_investment,
        "pv_investment": pv_investment,
        "total_investment": total_investment,
        "annual_energy_savings": annual_energy_savings_value,
        "annual_total_benefit": annual_total_benefit,
        "simple_payback_years": simple_payback_years,
        "simple_roi_pct": simple_roi_pct,
        "inaction_cost_3_years": annual_inaction_cost * 3.0,
        "inaction_cost_5_years": annual_inaction_cost * 5.0,
        "inaction_cost_10_years": annual_inaction_cost * 10.0,
    }
