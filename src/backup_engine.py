from __future__ import annotations

import math


def _as_float(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    return number


def _validate_fraction(value: float, name: str) -> float:
    number = _as_float(value, name)
    if number <= 0.0 or number > 1.0:
        raise ValueError(f"{name} must be greater than 0 and less than or equal to 1.")
    return number


def interpret_cycle_life(
    equivalent_cycles_per_year: float,
    estimated_life_years_by_cycles: float | None,
    high_year_threshold: float = 25.0,
) -> dict[str, str]:
    """Return a conservative display label for theoretical cycle life."""
    cycles_per_year = _as_float(equivalent_cycles_per_year, "equivalent_cycles_per_year")
    threshold = _as_float(high_year_threshold, "high_year_threshold")
    if cycles_per_year < 0.0:
        raise ValueError("equivalent_cycles_per_year must be non-negative.")
    if threshold <= 0.0:
        raise ValueError("high_year_threshold must be greater than 0.")
    if estimated_life_years_by_cycles is None:
        return {"title": "Uso por ciclos", "value": "No disponible"}

    life_years = _as_float(estimated_life_years_by_cycles, "estimated_life_years_by_cycles")
    if life_years < 0.0:
        raise ValueError("estimated_life_years_by_cycles must be non-negative.")
    if life_years > threshold:
        return {"title": "Ciclos no limitantes", "value": f"{cycles_per_year:,.1f}/año"}
    return {"title": "Vida teórica por ciclos", "value": f"{life_years:,.1f} años"}


def calculate_bess_backup(
    critical_load_value: float,
    load_unit: str,
    power_factor: float,
    backup_hours: float,
    depth_of_discharge: float,
    system_efficiency: float,
    safety_margin: float,
    outage_frequency: float = 0.0,
    outage_frequency_unit: str = "Por mes",
    average_outage_duration_h: float = 0.0,
    typical_max_outage_duration_h: float = 0.0,
    battery_capacity_kwh: float = 5.0,
    battery_max_power_kw: float = 5.0,
    life_cycles: float = 4500.0,
) -> dict[str, float | bool | None]:
    """Calculate a preliminary BESS backup sizing estimate."""
    load = _as_float(critical_load_value, "critical_load_value")
    hours = _as_float(backup_hours, "backup_hours")
    margin = _as_float(safety_margin, "safety_margin")
    dod = _validate_fraction(depth_of_discharge, "depth_of_discharge")
    efficiency = _validate_fraction(system_efficiency, "system_efficiency")
    frequency = _as_float(outage_frequency, "outage_frequency")
    average_duration = _as_float(average_outage_duration_h, "average_outage_duration_h")
    max_duration = _as_float(typical_max_outage_duration_h, "typical_max_outage_duration_h")
    battery_capacity = _as_float(battery_capacity_kwh, "battery_capacity_kwh")
    battery_power = _as_float(battery_max_power_kw, "battery_max_power_kw")
    estimated_life_cycles = _as_float(life_cycles, "life_cycles")

    if load < 0.0:
        raise ValueError("critical_load_value must be non-negative.")
    if hours < 0.0:
        raise ValueError("backup_hours must be non-negative.")
    if margin < 0.0:
        raise ValueError("safety_margin must be non-negative.")
    if frequency < 0.0:
        raise ValueError("outage_frequency must be non-negative.")
    if average_duration < 0.0:
        raise ValueError("average_outage_duration_h must be non-negative.")
    if max_duration < 0.0:
        raise ValueError("typical_max_outage_duration_h must be non-negative.")
    if battery_capacity < 0.0:
        raise ValueError("battery_capacity_kwh must be non-negative.")
    if battery_power < 0.0:
        raise ValueError("battery_max_power_kw must be non-negative.")
    if estimated_life_cycles < 0.0:
        raise ValueError("life_cycles must be non-negative.")

    normalized_unit = str(load_unit).strip().lower()
    if normalized_unit == "kw":
        critical_load_kw = load
    elif normalized_unit == "kva":
        pf = _validate_fraction(power_factor, "power_factor")
        critical_load_kw = load * pf
    else:
        raise ValueError("load_unit must be 'kW' or 'kVA'.")

    usable_energy_required_kwh = critical_load_kw * hours
    nominal_bess_capacity_kwh = usable_energy_required_kwh * (1.0 + margin) / (dod * efficiency)
    normalized_frequency_unit = str(outage_frequency_unit).strip().lower()
    if normalized_frequency_unit in {"por semana", "semana", "semanal", "week", "weekly", "per week"}:
        annual_outage_events = frequency * 52.0
    elif normalized_frequency_unit in {"por mes", "mes", "mensual", "month", "monthly", "per month"}:
        annual_outage_events = frequency * 12.0
    else:
        raise ValueError("outage_frequency_unit must be weekly or monthly.")

    batteries_for_capacity = (
        math.ceil(nominal_bess_capacity_kwh / battery_capacity)
        if battery_capacity > 0.0 and nominal_bess_capacity_kwh > 0.0
        else 0
    )
    batteries_for_power = (
        math.ceil(critical_load_kw / battery_power)
        if battery_power > 0.0 and critical_load_kw > 0.0
        else 0
    )
    recommended_battery_count = max(batteries_for_capacity, batteries_for_power)
    total_installed_capacity_kwh = recommended_battery_count * battery_capacity
    usable_installed_energy_kwh = total_installed_capacity_kwh * dod * efficiency
    installed_backup_hours = (
        usable_installed_energy_kwh / critical_load_kw
        if critical_load_kw > 0.0
        else 0.0
    )

    annual_outage_hours = annual_outage_events * average_duration
    backed_hours_per_event = min(average_duration, installed_backup_hours)
    annual_backed_hours = annual_outage_events * backed_hours_per_event
    annual_backed_energy_kwh = critical_load_kw * annual_backed_hours
    uncovered_average_outage_hours = max(average_duration - installed_backup_hours, 0.0)
    annual_uncovered_hours = annual_outage_events * uncovered_average_outage_hours

    equivalent_cycles_per_year = (
        annual_backed_energy_kwh / usable_installed_energy_kwh
        if usable_installed_energy_kwh > 0.0
        else 0.0
    )
    estimated_life_years_by_cycles = (
        estimated_life_cycles / equivalent_cycles_per_year
        if equivalent_cycles_per_year > 0.0
        else None
    )
    average_outage_covered = installed_backup_hours >= average_duration
    long_outage_covered = installed_backup_hours >= max_duration
    long_outage_uncovered_hours = max(max_duration - installed_backup_hours, 0.0)

    return {
        "critical_load_kw": critical_load_kw,
        "backup_hours": hours,
        "usable_energy_required_kwh": usable_energy_required_kwh,
        "nominal_bess_capacity_kwh": nominal_bess_capacity_kwh,
        "depth_of_discharge": dod,
        "system_efficiency": efficiency,
        "safety_margin": margin,
        "outage_frequency": frequency,
        "annual_outage_events": annual_outage_events,
        "annual_outage_hours": annual_outage_hours,
        "installed_backup_hours": installed_backup_hours,
        "backed_hours_per_event": backed_hours_per_event,
        "annual_backed_hours": annual_backed_hours,
        "annual_backed_energy_kwh": annual_backed_energy_kwh,
        "uncovered_average_outage_hours": uncovered_average_outage_hours,
        "annual_uncovered_hours": annual_uncovered_hours,
        "equivalent_cycles_per_year": equivalent_cycles_per_year,
        "estimated_life_years_by_cycles": estimated_life_years_by_cycles,
        "average_outage_covered": average_outage_covered,
        "long_outage_covered": long_outage_covered,
        "long_outage_uncovered_hours": long_outage_uncovered_hours,
        "battery_capacity_kwh": battery_capacity,
        "battery_max_power_kw": battery_power,
        "life_cycles": estimated_life_cycles,
        "recommended_battery_count": float(recommended_battery_count),
        "total_installed_capacity_kwh": total_installed_capacity_kwh,
        "usable_installed_energy_kwh": usable_installed_energy_kwh,
    }
