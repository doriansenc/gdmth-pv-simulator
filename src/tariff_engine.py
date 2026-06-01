from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TariffConfig:
    """Configurable tariff inputs for a simplified GDMTH estimate."""

    base_rate_mxn_kwh: float
    intermediate_rate_mxn_kwh: float
    peak_rate_mxn_kwh: float
    demand_rate_mxn_kw: float
    fixed_monthly_charge_mxn: float
    demand_charge_enabled: bool = True
    distribution_rate_mxn_kw: float = 57.74
    capacity_rate_mxn_kw: float = 398.22
    iva_rate: float = 0.16
    reference_power_factor: float = 0.90
    demand_limit_load_factor: float = 0.57
    power_factor_adjustment_enabled: bool = True


def _validate_tariff_config(config: TariffConfig) -> None:
    values = {
        "base_rate_mxn_kwh": config.base_rate_mxn_kwh,
        "intermediate_rate_mxn_kwh": config.intermediate_rate_mxn_kwh,
        "peak_rate_mxn_kwh": config.peak_rate_mxn_kwh,
        "demand_rate_mxn_kw": config.demand_rate_mxn_kw,
        "fixed_monthly_charge_mxn": config.fixed_monthly_charge_mxn,
        "distribution_rate_mxn_kw": config.distribution_rate_mxn_kw,
        "capacity_rate_mxn_kw": config.capacity_rate_mxn_kw,
        "iva_rate": config.iva_rate,
        "reference_power_factor": config.reference_power_factor,
        "demand_limit_load_factor": config.demand_limit_load_factor,
    }
    negative = [name for name, value in values.items() if value < 0.0]
    if negative:
        raise ValueError(f"Los valores tarifarios no pueden ser negativos: {', '.join(negative)}.")
    if config.reference_power_factor <= 0.0 or config.reference_power_factor > 1.0:
        raise ValueError("reference_power_factor debe estar entre 0 y 1.")
    if config.demand_limit_load_factor <= 0.0:
        raise ValueError("demand_limit_load_factor debe ser positivo.")


def _reactive_power_from_dataframe(df: pd.DataFrame) -> pd.Series:
    if "reactive_power_kVAr" in df.columns:
        return pd.to_numeric(df["reactive_power_kVAr"], errors="coerce").fillna(0.0).clip(lower=0.0)
    if "apparent_power_kVA" in df.columns:
        apparent = pd.to_numeric(df["apparent_power_kVA"], errors="coerce").fillna(0.0).clip(lower=0.0)
        active = pd.to_numeric(df["demand_kW"], errors="coerce").fillna(0.0).clip(lower=0.0)
        return np.sqrt(np.maximum(apparent**2 - active**2, 0.0))
    if "power_factor" in df.columns:
        fp = pd.to_numeric(df["power_factor"], errors="coerce").fillna(0.90).clip(lower=0.01, upper=1.0)
        active = pd.to_numeric(df["demand_kW"], errors="coerce").fillna(0.0).clip(lower=0.0)
        return active * np.tan(np.arccos(fp))
    return pd.Series(np.zeros(len(df)), index=df.index)


def _global_power_factor(active_power: pd.Series, reactive_power: pd.Series) -> float:
    active_sum = float(active_power.clip(lower=0.0).sum())
    reactive_sum = float(reactive_power.clip(lower=0.0).sum())
    denominator = float(np.sqrt(active_sum**2 + reactive_sum**2))
    return active_sum / denominator if denominator > 0.0 else 1.0


def _power_factor_adjustment(fp_global: float, config: TariffConfig) -> float:
    if not config.power_factor_adjustment_enabled:
        return 0.0
    fp = max(float(fp_global), 0.01)
    return (3.0 / 5.0) * (config.reference_power_factor / fp - 1.0)


def classify_gdmth_period(timestamp: pd.Timestamp) -> str:
    """
    Classify an interval into a simplified GDMTH period.

    This schedule is editable in the app through the tariff values. It is intended for
    academic estimation, not as an official CFE billing substitute.
    """
    hour = int(timestamp.hour)
    weekday = int(timestamp.dayofweek)

    if weekday < 5:
        if hour < 6 or hour >= 22:
            return "Base"
        if 18 <= hour < 22:
            return "Punta"
        return "Intermedia"

    if weekday == 5:
        if hour < 8 or hour >= 21:
            return "Base"
        if 19 <= hour < 21:
            return "Punta"
        return "Intermedia"

    if hour < 18:
        return "Base"
    return "Intermedia"


def add_tariff_columns(df: pd.DataFrame, config: TariffConfig) -> pd.DataFrame:
    """Add period labels and energy-cost estimates with and without PV generation."""
    _validate_tariff_config(config)
    result = df.copy()
    result["tariff_period"] = result["datetime"].apply(classify_gdmth_period)
    rate_map = {
        "Base": config.base_rate_mxn_kwh,
        "Intermedia": config.intermediate_rate_mxn_kwh,
        "Punta": config.peak_rate_mxn_kwh,
    }
    result["energy_rate_mxn_kwh"] = result["tariff_period"].map(rate_map).astype(float)
    result["grid_power_kW"] = np.maximum(result["demand_kW"] - result["generation_kW"], 0.0)
    result["reactive_power_kVAr"] = _reactive_power_from_dataframe(result)
    result["grid_reactive_power_kVAr"] = result["reactive_power_kVAr"]
    result["cost_without_pv_mxn"] = result["demand_energy_kWh"] * result["energy_rate_mxn_kwh"]
    result["cost_with_pv_mxn"] = result["grid_energy_kWh"] * result["energy_rate_mxn_kwh"]
    result["energy_savings_mxn"] = result["cost_without_pv_mxn"] - result["cost_with_pv_mxn"]
    return result


def _scenario_monthly_values(
    group: pd.DataFrame,
    config: TariffConfig,
    active_col: str,
    energy_col: str,
    reactive_col: str,
    suffix: str,
) -> dict[str, float]:
    period_codes = {"Base": "base", "Intermedia": "intermediate", "Punta": "peak"}
    energy_by_period: dict[str, float] = {}
    peak_by_period: dict[str, float] = {}
    cost_by_period: dict[str, float] = {}
    rate_by_code = {
        "base": config.base_rate_mxn_kwh,
        "intermediate": config.intermediate_rate_mxn_kwh,
        "peak": config.peak_rate_mxn_kwh,
    }

    for period, code in period_codes.items():
        period_rows = group[group["tariff_period"] == period]
        energy = float(period_rows[energy_col].sum())
        peak = float(period_rows[active_col].max()) if not period_rows.empty else 0.0
        energy_by_period[code] = energy
        peak_by_period[code] = peak
        cost_by_period[code] = energy * rate_by_code[code]

    month_start = group["month_start"].iloc[0]
    month_hours = float(pd.Timestamp(month_start).days_in_month * 24)
    total_energy = float(group[energy_col].sum())
    demand_limit_kw = total_energy / (month_hours * config.demand_limit_load_factor) if total_energy > 0.0 else 0.0
    distribution_demand_kw = min(max(peak_by_period.values()), demand_limit_kw)
    capacity_demand_kw = min(peak_by_period["peak"], demand_limit_kw)

    if config.demand_charge_enabled:
        distribution_cost = distribution_demand_kw * config.distribution_rate_mxn_kw
        capacity_cost = capacity_demand_kw * config.capacity_rate_mxn_kw
    else:
        distribution_cost = 0.0
        capacity_cost = 0.0

    active = group[active_col].astype(float).clip(lower=0.0)
    reactive = group[reactive_col].astype(float).clip(lower=0.0)
    fp_global = _global_power_factor(active, reactive)
    fp_adjustment = _power_factor_adjustment(fp_global, config)
    energy_cost = sum(cost_by_period.values())
    demand_cost = distribution_cost + capacity_cost
    subtotal_before_fp = energy_cost + demand_cost
    power_factor_adjustment_mxn = subtotal_before_fp * fp_adjustment
    subtotal_after_fp = max(0.0, subtotal_before_fp + power_factor_adjustment_mxn) + config.fixed_monthly_charge_mxn
    iva_mxn = subtotal_after_fp * config.iva_rate
    total = subtotal_after_fp + iva_mxn

    return {
        f"base_energy_{suffix}_kWh": energy_by_period["base"],
        f"intermediate_energy_{suffix}_kWh": energy_by_period["intermediate"],
        f"peak_energy_{suffix}_kWh": energy_by_period["peak"],
        f"base_energy_cost_{suffix}_mxn": cost_by_period["base"],
        f"intermediate_energy_cost_{suffix}_mxn": cost_by_period["intermediate"],
        f"peak_energy_cost_{suffix}_mxn": cost_by_period["peak"],
        f"energy_cost_{suffix}_mxn": energy_cost,
        f"peak_demand_{suffix}_kW": max(peak_by_period.values()),
        f"peak_period_demand_{suffix}_kW": peak_by_period["peak"],
        f"demand_limit_{suffix}_kW": demand_limit_kw,
        f"distribution_demand_{suffix}_kW": distribution_demand_kw,
        f"capacity_demand_{suffix}_kW": capacity_demand_kw,
        f"distribution_cost_{suffix}_mxn": distribution_cost,
        f"capacity_cost_{suffix}_mxn": capacity_cost,
        f"demand_cost_{suffix}_mxn": demand_cost,
        f"power_factor_{suffix}": fp_global,
        f"power_factor_adjustment_{suffix}": fp_adjustment,
        f"power_factor_adjustment_{suffix}_mxn": power_factor_adjustment_mxn,
        f"subtotal_before_fp_{suffix}_mxn": subtotal_before_fp,
        f"subtotal_after_fp_{suffix}_mxn": subtotal_after_fp,
        f"iva_{suffix}_mxn": iva_mxn,
        f"total_{suffix}_mxn": total,
    }


def monthly_tariff_summary(df: pd.DataFrame, config: TariffConfig) -> pd.DataFrame:
    """
    Return monthly estimated tariff impacts.

    The demand charge is a simplified estimate based on the maximum power during
    the modeled peak period. With PV, it uses grid_power_kW, so PV can reduce the
    estimated demand charge only when it reduces grid draw during that same period.
    This is not an official CFE billing substitute.
    """
    _validate_tariff_config(config)
    result = df.copy()
    datetime_local = result["datetime"]
    if isinstance(datetime_local.dtype, pd.DatetimeTZDtype):
        datetime_local = datetime_local.dt.tz_localize(None)
    result["month_start"] = datetime_local.dt.to_period("M").dt.to_timestamp()
    if "tariff_period" not in result.columns or "grid_power_kW" not in result.columns:
        result = add_tariff_columns(result, config)

    rows: list[dict[str, float | pd.Timestamp | str]] = []
    for month_start, group in result.groupby("month_start", sort=True):
        row: dict[str, float | pd.Timestamp | str] = {
            "month_start": month_start,
            "demand_energy_kWh": float(group["demand_energy_kWh"].sum()),
            "grid_energy_kWh": float(group["grid_energy_kWh"].sum()),
            "generation_kWh": float(group["energy_kWh"].sum()),
            "self_consumed_kWh": float(group["self_consumed_kWh"].sum()),
            "fixed_charge_mxn": config.fixed_monthly_charge_mxn,
        }
        row.update(
            _scenario_monthly_values(
                group,
                config,
                active_col="demand_kW",
                energy_col="demand_energy_kWh",
                reactive_col="reactive_power_kVAr",
                suffix="without_pv",
            )
        )
        row.update(
            _scenario_monthly_values(
                group,
                config,
                active_col="grid_power_kW",
                energy_col="grid_energy_kWh",
                reactive_col="grid_reactive_power_kVAr",
                suffix="with_pv",
            )
        )
        rows.append(row)

    grouped = pd.DataFrame(rows)
    grouped["energy_cost_without_pv_mxn"] = grouped["energy_cost_without_pv_mxn"]
    grouped["energy_cost_with_pv_mxn"] = grouped["energy_cost_with_pv_mxn"]
    grouped["demand_cost_without_pv_mxn"] = grouped["demand_cost_without_pv_mxn"]
    grouped["demand_cost_with_pv_mxn"] = grouped["demand_cost_with_pv_mxn"]
    grouped["peak_demand_without_pv_kW"] = grouped["peak_demand_without_pv_kW"]
    grouped["peak_demand_with_pv_kW"] = grouped["peak_demand_with_pv_kW"]
    grouped["peak_period_demand_without_pv_kW"] = grouped["peak_period_demand_without_pv_kW"]
    grouped["peak_period_demand_with_pv_kW"] = grouped["peak_period_demand_with_pv_kW"]
    grouped["total_without_pv_mxn"] = grouped["total_without_pv_mxn"]
    grouped["total_with_pv_mxn"] = grouped["total_with_pv_mxn"]
    grouped["estimated_savings_mxn"] = grouped["total_without_pv_mxn"] - grouped["total_with_pv_mxn"]
    grouped["savings_percent"] = np.where(
        grouped["total_without_pv_mxn"] > 0.0,
        100.0 * grouped["estimated_savings_mxn"] / grouped["total_without_pv_mxn"],
        0.0,
    )
    grouped["month"] = grouped["month_start"].dt.strftime("%b")
    return grouped


def annual_tariff_summary(monthly: pd.DataFrame) -> dict[str, float]:
    """Aggregate monthly tariff results into annual indicators."""
    without_pv = float(monthly["total_without_pv_mxn"].sum())
    with_pv = float(monthly["total_with_pv_mxn"].sum())
    savings = float(monthly["estimated_savings_mxn"].sum())
    savings_percent = 100.0 * savings / without_pv if without_pv > 0 else 0.0
    return {
        "annual_cost_without_pv_mxn": without_pv,
        "annual_cost_with_pv_mxn": with_pv,
        "annual_savings_mxn": savings,
        "annual_savings_percent": savings_percent,
        "annual_iva_without_pv_mxn": float(monthly["iva_without_pv_mxn"].sum()) if "iva_without_pv_mxn" in monthly else 0.0,
        "annual_iva_with_pv_mxn": float(monthly["iva_with_pv_mxn"].sum()) if "iva_with_pv_mxn" in monthly else 0.0,
        "annual_distribution_cost_without_pv_mxn": (
            float(monthly["distribution_cost_without_pv_mxn"].sum())
            if "distribution_cost_without_pv_mxn" in monthly
            else 0.0
        ),
        "annual_distribution_cost_with_pv_mxn": (
            float(monthly["distribution_cost_with_pv_mxn"].sum())
            if "distribution_cost_with_pv_mxn" in monthly
            else 0.0
        ),
        "annual_capacity_cost_without_pv_mxn": (
            float(monthly["capacity_cost_without_pv_mxn"].sum())
            if "capacity_cost_without_pv_mxn" in monthly
            else 0.0
        ),
        "annual_capacity_cost_with_pv_mxn": (
            float(monthly["capacity_cost_with_pv_mxn"].sum())
            if "capacity_cost_with_pv_mxn" in monthly
            else 0.0
        ),
    }
