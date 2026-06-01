from __future__ import annotations

from dataclasses import replace

import pandas as pd

from src.demand_engine import DemandConfig, add_synthetic_industrial_demand
from src.solar_engine import PVSystemConfig, simulate_pv_system
from src.summary import compute_summary


def parse_number_list(raw: str, value_type: type = float) -> list:
    """Parse a comma-separated list into numeric values."""
    values = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        values.append(value_type(item))
    return values


def compare_scenarios(
    base_config: PVSystemConfig,
    demand_config: DemandConfig,
    panel_counts: list[int],
    tilts: list[float],
    azimuths: list[float],
    irradiance_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run a small grid of PV scenarios and return summary metrics."""
    rows: list[dict[str, float | str]] = []
    scenario_id = 1
    for panels in panel_counts:
        for tilt in tilts:
            for azimuth in azimuths:
                config = replace(
                    base_config,
                    number_of_panels=int(panels),
                    tilt_deg=float(tilt),
                    azimuth_deg=float(azimuth),
                )
                df = simulate_pv_system(config, irradiance_df=irradiance_df, irradiance_source_label="Escenario")
                df = add_synthetic_industrial_demand(df, demand_config)
                summary = compute_summary(df, config.installed_power_kw, config.total_area_m2)
                rows.append(
                    {
                        "scenario": f"S{scenario_id}",
                        "number_of_panels": int(panels),
                        "tilt_deg": float(tilt),
                        "azimuth_deg": float(azimuth),
                        "installed_power_kw": summary["installed_power_kw"],
                        "annual_generation_kWh": summary["total_generation_kwh"],
                        "coverage_percent": summary["coverage_percent"],
                        "self_consumed_kWh": summary["self_consumed_kwh"],
                        "exported_kWh": summary["exported_kwh"],
                        "grid_energy_kWh": summary["grid_energy_kwh"],
                        "specific_yield_kWh_kWp": summary["specific_yield_kwh_kwp"],
                    }
                )
                scenario_id += 1
    return pd.DataFrame(rows)
