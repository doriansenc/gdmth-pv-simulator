from __future__ import annotations

import pandas as pd


def compute_summary(df: pd.DataFrame, installed_power_kw: float, total_area_m2: float) -> dict[str, float]:
    total_generation = float(df["energy_kWh"].sum())
    total_demand = float(df["demand_energy_kWh"].sum())
    total_self_consumed = float(df["self_consumed_kWh"].sum())
    total_exported = float(df["exported_kWh"].sum())
    total_grid = float(df["grid_energy_kWh"].sum())
    peak_generation = float(df["generation_kW"].max())
    peak_demand = float(df["demand_kW"].max())
    coverage_percent = 100.0 * total_self_consumed / total_demand if total_demand > 0 else 0.0
    specific_yield = total_generation / installed_power_kw if installed_power_kw > 0 else 0.0
    installed_power_from_area_kw = (
        float(df["installed_power_from_area_kw"].iloc[0])
        if "installed_power_from_area_kw" in df.columns and not df.empty
        else installed_power_kw
    )

    return {
        "installed_power_kw": installed_power_kw,
        "installed_power_from_area_kw": installed_power_from_area_kw,
        "total_area_m2": total_area_m2,
        "total_generation_kwh": total_generation,
        "total_demand_kwh": total_demand,
        "self_consumed_kwh": total_self_consumed,
        "exported_kwh": total_exported,
        "grid_energy_kwh": total_grid,
        "coverage_percent": coverage_percent,
        "specific_yield_kwh_kwp": specific_yield,
        "peak_generation_kw": peak_generation,
        "peak_demand_kw": peak_demand,
    }


def summary_table(summary: dict[str, float]) -> pd.DataFrame:
    rows = [
        ("Potencia instalada", f"{summary['installed_power_kw']:.2f} kW"),
        ("Potencia nominal estimada por área y eficiencia (STC)", f"{summary['installed_power_from_area_kw']:.2f} kW"),
        ("Área total del sistema", f"{summary['total_area_m2']:.2f} m²"),
        ("Energía anual generada", f"{summary['total_generation_kwh']:,.2f} kWh"),
        ("Demanda anual", f"{summary['total_demand_kwh']:,.2f} kWh"),
        ("Autoconsumo", f"{summary['self_consumed_kwh']:,.2f} kWh"),
        ("Energía exportada", f"{summary['exported_kwh']:,.2f} kWh"),
        ("Energía tomada de la red", f"{summary['grid_energy_kwh']:,.2f} kWh"),
        ("Cobertura de demanda", f"{summary['coverage_percent']:.2f} %"),
        ("Rendimiento específico", f"{summary['specific_yield_kwh_kwp']:.2f} kWh/kWp"),
        ("Pico de generación", f"{summary['peak_generation_kw']:.2f} kW"),
        ("Pico de demanda", f"{summary['peak_demand_kw']:.2f} kW"),
    ]
    return pd.DataFrame(rows, columns=["Indicador", "Valor"])
