from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DemandConfig:
    """Inputs for the synthetic industrial demand profile.

    power_factor is used to calculate apparent_power_kVA/reactive power and can
    affect the GDMTH power-factor adjustment in the tariff estimate.
    """

    max_demand_kw: float
    plant_factor: float
    power_factor: float
    random_seed: int
    weekend_reduction: float
    summer_increase: float


def _match_load_factor(shape: np.ndarray, target_load_factor: float) -> np.ndarray:
    """Scale a normalized load shape so mean/peak equals the target load factor."""
    normalized = np.asarray(shape, dtype=float)
    normalized = np.clip(normalized, 0.0, None)
    peak = float(normalized.max())
    if peak <= 0.0:
        return np.full_like(normalized, target_load_factor)

    normalized = normalized / peak
    target = float(np.clip(target_load_factor, 0.0, 1.0))
    current_mean = float(normalized.mean())

    if abs(current_mean - target) < 1e-6:
        return normalized

    if target > current_mean:
        base_fraction = (target - current_mean) / max(1.0 - current_mean, 1e-9)
        return base_fraction + (1.0 - base_fraction) * normalized

    low, high = 1.0, 20.0
    for _ in range(80):
        mid = (low + high) / 2.0
        candidate = normalized**mid
        if float(candidate.mean()) > target:
            low = mid
        else:
            high = mid
    return normalized**high


def _add_energy_balance_columns(result: pd.DataFrame, demand_source: str) -> pd.DataFrame:
    result["demand_energy_kWh"] = result["demand_energy_kWh"].astype(float)
    result["self_consumed_kWh"] = np.minimum(result["energy_kWh"], result["demand_energy_kWh"])
    result["exported_kWh"] = np.maximum(result["energy_kWh"] - result["demand_energy_kWh"], 0.0)
    result["grid_energy_kWh"] = np.maximum(result["demand_energy_kWh"] - result["energy_kWh"], 0.0)
    result["net_power_kW"] = result["generation_kW"] - result["demand_kW"]
    result["demand_source"] = demand_source
    return result


def add_synthetic_industrial_demand(df: pd.DataFrame, config: DemandConfig) -> pd.DataFrame:
    """Add a reproducible synthetic industrial load profile to a PV simulation table."""
    result = df.copy()
    if config.max_demand_kw <= 0:
        raise ValueError("max_demand_kw must be positive.")
    if not (0.0 < config.plant_factor <= 1.0):
        raise ValueError("plant_factor must be between 0 and 1.")
    if not (0.0 < config.power_factor <= 1.0):
        raise ValueError("power_factor must be between 0 and 1.")
    if not (0.0 <= config.weekend_reduction <= 1.0):
        raise ValueError("weekend_reduction must be between 0 and 1.")
    if config.summer_increase < 0.0:
        raise ValueError("summer_increase must be non-negative.")

    rng = np.random.default_rng(config.random_seed)

    hour = result["datetime"].dt.hour
    weekday = result["datetime"].dt.dayofweek
    month = result["datetime"].dt.month

    morning_ramp = np.where((hour >= 6) & (hour < 9), 0.70, 0.0)
    production_block = np.where((hour >= 9) & (hour <= 18), 0.95, 0.0)
    evening_ramp = np.where((hour > 18) & (hour <= 21), 0.62, 0.0)
    night_base = np.where((hour < 6) | (hour > 21), 0.35, 0.0)

    normalized_shape = morning_ramp + production_block + evening_ramp + night_base
    normalized_shape = np.where(normalized_shape == 0.0, 0.48, normalized_shape)

    weekend_factor = np.where(weekday >= 5, 1.0 - config.weekend_reduction, 1.0)
    summer_factor = np.where(month.isin([5, 6, 7, 8, 9]), 1.0 + config.summer_increase, 0.96)
    noise = rng.normal(loc=1.0, scale=0.035, size=len(result))

    raw_shape = normalized_shape * weekend_factor * summer_factor * noise
    load_fraction = _match_load_factor(raw_shape, config.plant_factor)
    demand_kw = np.clip(config.max_demand_kw * load_fraction, 0.0, config.max_demand_kw)

    result["demand_kW"] = demand_kw
    result["load_fraction"] = load_fraction
    result["apparent_power_kVA"] = demand_kw / config.power_factor
    result["demand_energy_kWh"] = demand_kw * 0.25
    result["power_factor"] = config.power_factor

    return _add_energy_balance_columns(result, "Sintetica industrial")


def _read_demand_file(file: Any) -> pd.DataFrame:
    filename = str(getattr(file, "name", "")).lower()
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(file)
    return pd.read_csv(file)


def read_uploaded_demand(
    file: Any,
    year: int,
    timezone: str,
    default_power_factor: float,
) -> pd.DataFrame:
    """Read, validate and convert an uploaded demand file to a 15-minute annual profile."""
    if not (0.0 < default_power_factor <= 1.0):
        raise ValueError("default_power_factor must be between 0 and 1.")

    raw = _read_demand_file(file)
    if raw.empty:
        raise ValueError("El archivo de demanda esta vacio.")
    if "datetime" not in raw.columns or "demand_kW" not in raw.columns:
        raise ValueError("El archivo de demanda debe incluir las columnas datetime y demand_kW.")

    warnings: list[str] = []
    demand = raw.copy()
    demand["datetime"] = pd.to_datetime(demand["datetime"], errors="coerce")
    demand["demand_kW"] = pd.to_numeric(demand["demand_kW"], errors="coerce")
    demand = demand.dropna(subset=["datetime", "demand_kW"])
    if demand.empty:
        raise ValueError("El archivo de demanda no contiene registros validos.")
    if (demand["demand_kW"] < 0.0).any():
        raise ValueError("La columna demand_kW no puede contener valores negativos.")

    if "demand_energy_kWh" in demand.columns:
        demand["demand_energy_kWh"] = pd.to_numeric(demand["demand_energy_kWh"], errors="coerce")
        if (demand["demand_energy_kWh"].dropna() < 0.0).any():
            raise ValueError("La columna demand_energy_kWh no puede contener valores negativos.")
    else:
        demand["demand_energy_kWh"] = np.nan

    if "power_factor" in demand.columns:
        demand["power_factor"] = pd.to_numeric(demand["power_factor"], errors="coerce")
        valid_power_factor = demand["power_factor"].dropna()
        if ((valid_power_factor <= 0.0) | (valid_power_factor > 1.0)).any():
            raise ValueError("La columna power_factor debe estar entre 0 y 1.")
        demand["power_factor"] = demand["power_factor"].fillna(default_power_factor)
    else:
        demand["power_factor"] = default_power_factor

    if demand["datetime"].dt.tz is None:
        demand["datetime"] = demand["datetime"].dt.tz_localize(timezone)
    else:
        demand["datetime"] = demand["datetime"].dt.tz_convert(timezone)
    demand = demand[demand["datetime"].dt.year == int(year)]
    if demand.empty:
        raise ValueError("El archivo de demanda no tiene registros para el ano seleccionado.")

    duplicated_count = int(demand["datetime"].duplicated().sum())
    if duplicated_count:
        warnings.append(f"Se encontraron {duplicated_count} timestamps duplicados; se promediaron por fecha/hora.")

    demand = (
        demand[["datetime", "demand_kW", "demand_energy_kWh", "power_factor"]]
        .groupby("datetime", as_index=True)
        .mean(numeric_only=True)
        .sort_index()
    )

    intervals = demand.index.to_series().diff().dropna()
    if not intervals.empty:
        median_interval = intervals.median()
        if median_interval != pd.Timedelta(minutes=15):
            warnings.append(
                f"La resolucion detectada es {median_interval}; se convirtio a intervalos de 15 minutos."
            )

    start = pd.Timestamp(f"{year}-01-01 00:00:00", tz=timezone)
    end = pd.Timestamp(f"{year}-12-31 23:45:00", tz=timezone)
    target_index = pd.date_range(start=start, end=end, freq="15min")
    missing_count = int(target_index.difference(demand.index).size)
    if missing_count:
        warnings.append(
            f"Faltaban {missing_count} intervalos de 15 minutos; se interpolaron o rellenaron para completar el ano."
        )

    demand = demand.reindex(target_index.union(demand.index)).interpolate(method="time").reindex(target_index)
    demand = demand.ffill().bfill()
    demand["demand_kW"] = demand["demand_kW"].clip(lower=0.0)
    demand["power_factor"] = demand["power_factor"].fillna(default_power_factor).clip(lower=0.01, upper=1.0)
    demand["demand_energy_kWh"] = demand["demand_energy_kWh"].fillna(demand["demand_kW"] * 0.25)

    output = demand.reset_index().rename(columns={"index": "datetime"})
    output["apparent_power_kVA"] = output["demand_kW"] / output["power_factor"]
    output["demand_source"] = "Archivo cargado"
    output.attrs["warnings"] = warnings
    return output


def add_real_demand_to_simulation(pv_df: pd.DataFrame, demand_df: pd.DataFrame) -> pd.DataFrame:
    """Attach a validated real demand profile to a PV simulation table."""
    required_columns = {"datetime", "demand_kW", "demand_energy_kWh", "apparent_power_kVA"}
    missing_columns = required_columns.difference(demand_df.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"La demanda cargada no tiene columnas requeridas: {missing}.")

    result = pv_df.copy()
    demand = demand_df.copy()
    demand["datetime"] = pd.to_datetime(demand["datetime"])
    result = result.merge(
        demand[["datetime", "demand_kW", "demand_energy_kWh", "apparent_power_kVA", "demand_source"]],
        on="datetime",
        how="left",
    )
    demand_columns = ["demand_kW", "demand_energy_kWh", "apparent_power_kVA"]
    if result[demand_columns].isna().any().any():
        raise ValueError("La demanda cargada no cubre todos los intervalos de la simulacion.")
    result["load_fraction"] = np.where(
        result["demand_kW"].max() > 0.0,
        result["demand_kW"] / result["demand_kW"].max(),
        0.0,
    )
    return _add_energy_balance_columns(result, "Archivo cargado")
