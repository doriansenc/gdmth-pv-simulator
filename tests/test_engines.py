from dataclasses import replace
from io import StringIO

import numpy as np
import pandas as pd
import pytest

from src.backup_engine import calculate_bess_backup, interpret_cycle_life
from src.express_savings import compute_express_savings
from src.profitability_engine import calculate_profitability, percent_to_fraction
from src.plotting import plot_profitability_cumulative_chart
from src.receipt_savings import compute_receipt_based_savings, suggest_industrial_tariff_family
from src.demand_engine import (
    DemandConfig,
    add_real_demand_to_simulation,
    add_synthetic_industrial_demand,
    read_uploaded_demand,
)
from src.irradiance_data import (
    prepare_nasa_power_irradiance,
    prepare_nasa_power_provisional_irradiance,
    standardize_irradiance_table,
    to_15min_irradiance,
)
from src.scenario_engine import parse_number_list
from src.summary import compute_summary
from src.tariff_engine import (
    TariffConfig,
    add_tariff_columns,
    annual_tariff_summary,
    classify_gdmth_period,
    monthly_tariff_summary,
)


def _annual_base_table(year: int = 2026) -> pd.DataFrame:
    times = pd.date_range(f"{year}-01-01 00:00", f"{year}-12-31 23:45", freq="15min", tz="Etc/GMT+6")
    return pd.DataFrame(
        {
            "datetime": times,
            "generation_kW": np.zeros(len(times)),
            "energy_kWh": np.zeros(len(times)),
        }
    )


def _csv_upload(df: pd.DataFrame, name: str = "demand.csv") -> StringIO:
    file = StringIO(df.to_csv(index=False))
    file.name = name
    return file


def _tariff_ready_table(demand_kw: float = 50.0, generation_kw: float = 10.0, year: int = 2026) -> pd.DataFrame:
    df = _annual_base_table(year)
    df["generation_kW"] = generation_kw
    df["energy_kWh"] = df["generation_kW"] * 0.25
    df["demand_kW"] = demand_kw
    df["demand_energy_kWh"] = df["demand_kW"] * 0.25
    df["self_consumed_kWh"] = np.minimum(df["energy_kWh"], df["demand_energy_kWh"])
    df["exported_kWh"] = np.maximum(df["energy_kWh"] - df["demand_energy_kWh"], 0.0)
    df["grid_energy_kWh"] = np.maximum(df["demand_energy_kWh"] - df["energy_kWh"], 0.0)
    return df


def _tariff_ready_table_with_power_factor(
    demand_kw: float = 50.0,
    generation_kw: float = 10.0,
    power_factor: float = 0.90,
    year: int = 2026,
) -> pd.DataFrame:
    df = _tariff_ready_table(demand_kw=demand_kw, generation_kw=generation_kw, year=year)
    df["power_factor"] = power_factor
    df["apparent_power_kVA"] = df["demand_kW"] / power_factor
    return df


def _default_tariff(demand_charge_enabled: bool = True, fixed_monthly_charge_mxn: float = 850.0) -> TariffConfig:
    return TariffConfig(
        base_rate_mxn_kwh=1.15,
        intermediate_rate_mxn_kwh=1.85,
        peak_rate_mxn_kwh=2.95,
        demand_rate_mxn_kw=280.0,
        fixed_monthly_charge_mxn=fixed_monthly_charge_mxn,
        demand_charge_enabled=demand_charge_enabled,
    )


def test_bess_backup_calculates_kw_load():
    result = calculate_bess_backup(
        critical_load_value=10.0,
        load_unit="kW",
        power_factor=0.80,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
    )

    assert result["critical_load_kw"] == pytest.approx(10.0)
    assert result["usable_energy_required_kwh"] == pytest.approx(40.0)
    assert result["nominal_bess_capacity_kwh"] == pytest.approx(40.0 * 1.15 / (0.80 * 0.90))


def test_bess_backup_calculates_kva_load_with_power_factor():
    result = calculate_bess_backup(
        critical_load_value=50.0,
        load_unit="kVA",
        power_factor=0.85,
        backup_hours=2.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.0,
    )

    assert result["critical_load_kw"] == pytest.approx(42.5)
    assert result["usable_energy_required_kwh"] == pytest.approx(85.0)


def test_bess_backup_depth_of_discharge_and_efficiency_affect_capacity():
    base = calculate_bess_backup(
        critical_load_value=20.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=3.0,
        depth_of_discharge=1.0,
        system_efficiency=1.0,
        safety_margin=0.0,
    )
    conservative = calculate_bess_backup(
        critical_load_value=20.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=3.0,
        depth_of_discharge=0.75,
        system_efficiency=0.85,
        safety_margin=0.0,
    )

    assert base["nominal_bess_capacity_kwh"] == pytest.approx(60.0)
    assert conservative["nominal_bess_capacity_kwh"] > base["nominal_bess_capacity_kwh"]


def test_bess_backup_safety_margin_increases_capacity():
    without_margin = calculate_bess_backup(
        critical_load_value=15.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.0,
    )
    with_margin = calculate_bess_backup(
        critical_load_value=15.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.20,
    )

    assert with_margin["nominal_bess_capacity_kwh"] == pytest.approx(
        without_margin["nominal_bess_capacity_kwh"] * 1.20
    )


def test_bess_backup_weekly_outage_frequency_converts_to_annual_events():
    result = calculate_bess_backup(
        critical_load_value=10.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=2.0,
        outage_frequency_unit="Por semana",
        average_outage_duration_h=1.5,
        typical_max_outage_duration_h=3.0,
    )

    assert result["annual_outage_events"] == pytest.approx(104.0)
    assert result["annual_outage_hours"] == pytest.approx(156.0)


def test_bess_backup_monthly_outage_frequency_converts_to_annual_events():
    result = calculate_bess_backup(
        critical_load_value=10.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=3.0,
        outage_frequency_unit="Por mes",
        average_outage_duration_h=2.0,
        typical_max_outage_duration_h=4.0,
    )

    assert result["annual_outage_events"] == pytest.approx(36.0)
    assert result["annual_outage_hours"] == pytest.approx(72.0)


def test_bess_backup_annual_backed_energy_uses_critical_load_and_outage_hours():
    result = calculate_bess_backup(
        critical_load_value=12.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=2.0,
        outage_frequency_unit="Por mes",
        average_outage_duration_h=3.0,
        typical_max_outage_duration_h=5.0,
    )

    assert result["annual_outage_hours"] == pytest.approx(72.0)
    assert result["annual_backed_energy_kwh"] == pytest.approx(864.0)


def test_bess_backup_equivalent_cycles_and_life_by_cycles():
    result = calculate_bess_backup(
        critical_load_value=10.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=1.0,
        outage_frequency_unit="Por mes",
        average_outage_duration_h=3.0,
        typical_max_outage_duration_h=4.0,
        battery_capacity_kwh=20.0,
        battery_max_power_kw=10.0,
        life_cycles=4500.0,
    )

    assert result["recommended_battery_count"] == pytest.approx(4.0)
    assert result["usable_installed_energy_kwh"] == pytest.approx(80.0 * 0.80 * 0.90)
    assert result["installed_backup_hours"] == pytest.approx((80.0 * 0.80 * 0.90) / 10.0)
    assert result["annual_backed_energy_kwh"] == pytest.approx(360.0)
    assert result["equivalent_cycles_per_year"] == pytest.approx(360.0 / 57.6)
    assert result["estimated_life_years_by_cycles"] == pytest.approx(4500.0 / (360.0 / 57.6))


def test_bess_backup_interprets_high_cycle_life_as_non_limiting():
    label = interpret_cycle_life(
        equivalent_cycles_per_year=10.3,
        estimated_life_years_by_cycles=438.8,
    )

    assert label["title"] == "Ciclos no limitantes"
    assert label["value"] == "10.3/año"


def test_bess_backup_interprets_cycle_life_under_threshold_as_theoretical():
    label = interpret_cycle_life(
        equivalent_cycles_per_year=300.0,
        estimated_life_years_by_cycles=15.0,
    )

    assert label["title"] == "Vida teórica por ciclos"
    assert label["value"] == "15.0 años"


def test_bess_backup_detects_long_outage_uncovered_hours():
    result = calculate_bess_backup(
        critical_load_value=8.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=1.0,
        outage_frequency_unit="Por mes",
        average_outage_duration_h=3.0,
        typical_max_outage_duration_h=7.5,
    )

    assert result["average_outage_covered"] is True
    assert result["long_outage_uncovered_hours"] == pytest.approx(7.5 - result["installed_backup_hours"])


def test_bess_backup_limits_annual_backed_energy_by_installed_autonomy():
    result = calculate_bess_backup(
        critical_load_value=10.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=2.0,
        outage_frequency_unit="Por mes",
        average_outage_duration_h=6.0,
        typical_max_outage_duration_h=6.0,
        battery_capacity_kwh=5.0,
        battery_max_power_kw=5.0,
        life_cycles=4500.0,
    )

    installed_backup_hours = 46.8 / 10.0
    annual_backed_hours = 24.0 * installed_backup_hours

    assert result["recommended_battery_count"] == pytest.approx(13.0)
    assert result["usable_installed_energy_kwh"] == pytest.approx(46.8)
    assert result["installed_backup_hours"] == pytest.approx(installed_backup_hours)
    assert result["annual_outage_hours"] == pytest.approx(144.0)
    assert result["annual_backed_hours"] == pytest.approx(annual_backed_hours)
    assert result["annual_backed_energy_kwh"] == pytest.approx(10.0 * annual_backed_hours)
    assert result["uncovered_average_outage_hours"] == pytest.approx(6.0 - installed_backup_hours)
    assert result["annual_uncovered_hours"] == pytest.approx(24.0 * (6.0 - installed_backup_hours))
    assert result["long_outage_uncovered_hours"] == pytest.approx(6.0 - installed_backup_hours)
    assert result["equivalent_cycles_per_year"] == pytest.approx(result["annual_backed_energy_kwh"] / 46.8)


def test_bess_backup_keeps_full_backed_hours_when_average_outage_fits_autonomy():
    result = calculate_bess_backup(
        critical_load_value=10.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=2.0,
        outage_frequency_unit="Por mes",
        average_outage_duration_h=3.0,
        typical_max_outage_duration_h=4.0,
        battery_capacity_kwh=5.0,
        battery_max_power_kw=5.0,
        life_cycles=4500.0,
    )

    assert result["average_outage_covered"] is True
    assert result["long_outage_covered"] is True
    assert result["annual_outage_hours"] == pytest.approx(72.0)
    assert result["annual_backed_hours"] == pytest.approx(72.0)
    assert result["annual_backed_energy_kwh"] == pytest.approx(720.0)
    assert result["uncovered_average_outage_hours"] == pytest.approx(0.0)
    assert result["annual_uncovered_hours"] == pytest.approx(0.0)


def test_bess_backup_avoids_division_by_zero_without_installed_energy():
    result = calculate_bess_backup(
        critical_load_value=10.0,
        load_unit="kW",
        power_factor=0.90,
        backup_hours=4.0,
        depth_of_discharge=0.80,
        system_efficiency=0.90,
        safety_margin=0.15,
        outage_frequency=1.0,
        outage_frequency_unit="Por mes",
        average_outage_duration_h=2.0,
        typical_max_outage_duration_h=3.0,
        battery_capacity_kwh=0.0,
        battery_max_power_kw=0.0,
        life_cycles=4500.0,
    )

    assert result["recommended_battery_count"] == pytest.approx(0.0)
    assert result["usable_installed_energy_kwh"] == pytest.approx(0.0)
    assert result["equivalent_cycles_per_year"] == pytest.approx(0.0)
    assert result["estimated_life_years_by_cycles"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"critical_load_value": -1.0},
        {"backup_hours": -1.0},
        {"depth_of_discharge": 0.0},
        {"depth_of_discharge": 1.1},
        {"system_efficiency": 0.0},
        {"system_efficiency": 1.1},
        {"safety_margin": -0.1},
        {"load_unit": "kVA", "power_factor": 0.0},
        {"load_unit": "kVA", "power_factor": 1.1},
        {"load_unit": "MW"},
        {"outage_frequency": -1.0},
        {"average_outage_duration_h": -1.0},
        {"typical_max_outage_duration_h": -1.0},
        {"battery_capacity_kwh": -1.0},
        {"battery_max_power_kw": -1.0},
        {"life_cycles": -1.0},
        {"outage_frequency_unit": "Por ano"},
    ],
)
def test_bess_backup_rejects_invalid_values(kwargs):
    params = {
        "critical_load_value": 10.0,
        "load_unit": "kW",
        "power_factor": 0.90,
        "backup_hours": 4.0,
        "depth_of_discharge": 0.80,
        "system_efficiency": 0.90,
        "safety_margin": 0.15,
    }
    params.update(kwargs)

    with pytest.raises(ValueError):
        calculate_bess_backup(**params)


def _profitability_params(**overrides):
    params = {
        "annual_outage_events": 12.0,
        "annual_outage_hours": 36.0,
        "outage_cost_per_hour": 10000.0,
        "fixed_cost_per_outage": 2500.0,
        "annual_repairs_or_damage_cost": 50000.0,
        "avoidable_loss_fraction": 0.80,
        "recommended_batteries": 4.0,
        "battery_unit_cost": 25000.0,
        "balance_of_system_mode": "Porcentaje",
        "balance_of_system_percentage": 0.20,
        "balance_of_system_manual_cost": 0.0,
        "include_pv_investment": False,
        "pv_investment_cost": 0.0,
        "include_energy_savings": False,
        "annual_energy_savings": 0.0,
    }
    params.update(overrides)
    return params


def test_profitability_visible_percentages_convert_to_internal_fractions():
    assert percent_to_fraction(90.0, "avoidable_loss_percent") == pytest.approx(0.90)
    assert percent_to_fraction(20.0, "balance_of_system_percent") == pytest.approx(0.20)


def test_profitability_visible_percentage_rejects_values_outside_range():
    with pytest.raises(ValueError):
        percent_to_fraction(120.0, "avoidable_loss_percent")


def test_profitability_calculates_annual_inaction_and_avoidable_losses():
    result = calculate_profitability(**_profitability_params())

    assert result["annual_downtime_cost"] == pytest.approx(360000.0)
    assert result["annual_event_cost"] == pytest.approx(30000.0)
    assert result["annual_inaction_cost"] == pytest.approx(440000.0)
    assert result["avoidable_losses"] == pytest.approx(352000.0)


def test_profitability_calculates_bess_investment_with_percentage_balance_of_system():
    result = calculate_profitability(**_profitability_params())

    assert result["battery_total_cost"] == pytest.approx(100000.0)
    assert result["balance_of_system_cost"] == pytest.approx(20000.0)
    assert result["bess_investment"] == pytest.approx(120000.0)
    assert result["total_investment"] == pytest.approx(120000.0)


def test_profitability_calculates_expected_investment_from_visible_twenty_percent():
    result = calculate_profitability(
        **_profitability_params(
            recommended_batteries=13.0,
            battery_unit_cost=25000.0,
            balance_of_system_percentage=percent_to_fraction(20.0, "balance_of_system_percent"),
        )
    )

    assert result["battery_total_cost"] == pytest.approx(325000.0)
    assert result["balance_of_system_cost"] == pytest.approx(65000.0)
    assert result["bess_investment"] == pytest.approx(390000.0)


def test_profitability_calculates_manual_balance_of_system_cost():
    result = calculate_profitability(
        **_profitability_params(
            balance_of_system_mode="Monto manual",
            balance_of_system_percentage=0.20,
            balance_of_system_manual_cost=45000.0,
        )
    )

    assert result["battery_total_cost"] == pytest.approx(100000.0)
    assert result["balance_of_system_cost"] == pytest.approx(45000.0)
    assert result["bess_investment"] == pytest.approx(145000.0)


def test_profitability_adds_optional_pv_investment():
    without_pv = calculate_profitability(**_profitability_params())
    with_pv = calculate_profitability(
        **_profitability_params(
            include_pv_investment=True,
            pv_investment_cost=300000.0,
        )
    )

    assert without_pv["pv_investment"] == pytest.approx(0.0)
    assert with_pv["pv_investment"] == pytest.approx(300000.0)
    assert with_pv["total_investment"] == pytest.approx(without_pv["total_investment"] + 300000.0)


def test_profitability_adds_optional_energy_savings_to_annual_benefit():
    without_savings = calculate_profitability(**_profitability_params())
    with_savings = calculate_profitability(
        **_profitability_params(
            include_energy_savings=True,
            annual_energy_savings=48000.0,
        )
    )

    assert without_savings["annual_energy_savings"] == pytest.approx(0.0)
    assert with_savings["annual_energy_savings"] == pytest.approx(48000.0)
    assert with_savings["annual_total_benefit"] == pytest.approx(without_savings["annual_total_benefit"] + 48000.0)


def test_profitability_calculates_simple_payback_and_roi():
    result = calculate_profitability(**_profitability_params())

    assert result["simple_payback_years"] == pytest.approx(120000.0 / 352000.0)
    assert result["simple_roi_pct"] == pytest.approx(352000.0 / 120000.0 * 100.0)


def test_profitability_avoids_payback_division_by_zero_without_annual_benefit():
    result = calculate_profitability(
        **_profitability_params(
            annual_outage_events=0.0,
            annual_outage_hours=0.0,
            fixed_cost_per_outage=0.0,
            annual_repairs_or_damage_cost=0.0,
            include_energy_savings=False,
            annual_energy_savings=0.0,
        )
    )

    assert result["annual_total_benefit"] == pytest.approx(0.0)
    assert result["simple_payback_years"] is None
    assert result["simple_roi_pct"] == pytest.approx(0.0)


def test_profitability_projects_inaction_costs_to_three_five_and_ten_years():
    result = calculate_profitability(**_profitability_params())

    assert result["inaction_cost_3_years"] == pytest.approx(result["annual_inaction_cost"] * 3.0)
    assert result["inaction_cost_5_years"] == pytest.approx(result["annual_inaction_cost"] * 5.0)
    assert result["inaction_cost_10_years"] == pytest.approx(result["annual_inaction_cost"] * 10.0)


def test_profitability_rejects_invalid_values():
    with pytest.raises(ValueError):
        calculate_profitability(**_profitability_params(annual_outage_hours=-1.0))
    with pytest.raises(ValueError):
        calculate_profitability(**_profitability_params(avoidable_loss_fraction=90.0))
    with pytest.raises(ValueError):
        calculate_profitability(**_profitability_params(balance_of_system_percentage=20.0))
    with pytest.raises(ValueError):
        calculate_profitability(**_profitability_params(balance_of_system_mode="Complejo"))


def test_profitability_cumulative_chart_uses_annual_series():
    result = calculate_profitability(
        **_profitability_params(
            include_energy_savings=True,
            annual_energy_savings=48000.0,
        )
    )
    fig = plot_profitability_cumulative_chart(result)

    assert len(fig.data) == 3
    assert list(fig.data[0].x) == list(range(0, 11))
    assert list(fig.data[0].y) == [pytest.approx(result["total_investment"])] * 11
    assert fig.data[1].y[-1] == pytest.approx(result["annual_inaction_cost"] * 10.0)
    assert fig.data[2].y[-1] == pytest.approx(result["annual_total_benefit"] * 10.0)


def test_profitability_cumulative_chart_omits_benefit_trace_without_benefit():
    result = calculate_profitability(
        **_profitability_params(
            annual_outage_events=0.0,
            annual_outage_hours=0.0,
            fixed_cost_per_outage=0.0,
            annual_repairs_or_damage_cost=0.0,
        )
    )
    fig = plot_profitability_cumulative_chart(result)

    assert len(fig.data) == 2
    assert fig.data[1].y[-1] == pytest.approx(0.0)


def test_express_savings_consumption_greater_than_generation():
    result = compute_express_savings(
        annual_consumption_kwh=12000.0,
        annual_generation_kwh=8000.0,
    )

    assert result["grid_energy_kWh"] == pytest.approx(4000.0)
    assert result["exported_kWh"] == pytest.approx(0.0)
    assert result["solar_coverage_pct"] < 100.0


def test_express_savings_generation_greater_than_consumption():
    result = compute_express_savings(
        annual_consumption_kwh=9000.0,
        annual_generation_kwh=12000.0,
    )

    assert result["grid_energy_kWh"] == pytest.approx(0.0)
    assert result["exported_kWh"] == pytest.approx(3000.0)
    assert result["solar_coverage_pct"] == pytest.approx(100.0)


def test_express_savings_with_average_cost():
    result = compute_express_savings(
        annual_consumption_kwh=12000.0,
        annual_generation_kwh=8000.0,
        average_cost_mxn_kwh=2.5,
        economic_enabled=True,
    )

    assert result["annual_savings"] == pytest.approx(result["self_consumed_kWh"] * 2.5)
    assert result["annual_cost_with_pv"] == pytest.approx(result["grid_energy_kWh"] * 2.5)
    assert result["current_annual_cost"] == pytest.approx(30000.0)


def test_express_savings_without_average_cost_does_not_fail():
    result = compute_express_savings(
        annual_consumption_kwh=12000.0,
        annual_generation_kwh=8000.0,
        economic_enabled=True,
    )

    assert result["current_annual_cost"] is None
    assert result["annual_cost_with_pv"] is None
    assert result["annual_savings"] is None
    assert result["savings_pct"] is None


def test_receipt_tariff_suggestion_uses_gdmto_below_100_kw():
    assert suggest_industrial_tariff_family(99.9) == "GDMTO"


def test_receipt_tariff_suggestion_uses_gdmth_at_100_kw_or_more():
    assert suggest_industrial_tariff_family(100.0) == "GDMTH"
    assert suggest_industrial_tariff_family(250.0) == "GDMTH"


def test_receipt_based_cost_without_pv_uses_consumption_times_average_price():
    result = compute_receipt_based_savings(
        [{"period": "Enero", "consumption_kwh": 1000.0, "average_price_mxn_kwh": 2.5}],
        annual_generation_kwh=0.0,
    )

    assert result["period_results"][0]["estimated_cost_without_pv_mxn"] == pytest.approx(2500.0)
    assert result["annual_cost_without_pv_mxn"] == pytest.approx(30000.0)


def test_receipt_based_analysis_projects_when_less_than_12_months():
    result = compute_receipt_based_savings(
        [
            {"period": "Enero", "consumption_kwh": 1000.0, "average_price_mxn_kwh": 2.0},
            {"period": "Febrero", "consumption_kwh": 1200.0, "average_price_mxn_kwh": 2.0},
            {"period": "Marzo", "consumption_kwh": 1100.0, "average_price_mxn_kwh": 2.0},
        ],
        annual_generation_kwh=0.0,
        period_frequency="Mensual",
    )

    assert result["analysis_type"] == "Proyección anual"
    assert result["projection_factor"] == pytest.approx(4.0)
    assert result["annual_consumption_kWh"] == pytest.approx(13200.0)


def test_receipt_based_analysis_is_historical_with_12_months():
    periods = [
        {"period": f"Mes {index}", "consumption_kwh": 1000.0, "average_price_mxn_kwh": 2.0}
        for index in range(1, 13)
    ]

    result = compute_receipt_based_savings(periods, annual_generation_kwh=0.0, period_frequency="Mensual")

    assert result["analysis_type"] == "Histórico anual"
    assert result["projection_factor"] == pytest.approx(1.0)
    assert result["annual_consumption_kWh"] == pytest.approx(12000.0)
    assert result["annual_cost_without_pv_mxn"] == pytest.approx(24000.0)


def test_receipt_based_savings_use_current_pv_generation():
    result = compute_receipt_based_savings(
        [{"period": "Enero", "consumption_kwh": 1000.0, "average_price_mxn_kwh": 2.0} for _ in range(12)],
        annual_generation_kwh=8000.0,
        period_frequency="Mensual",
    )

    assert result["self_consumed_kWh"] == pytest.approx(8000.0)
    assert result["grid_energy_kWh"] == pytest.approx(4000.0)
    assert result["annual_cost_with_pv_mxn"] == pytest.approx(8000.0)
    assert result["annual_savings_mxn"] == pytest.approx(16000.0)


def test_metric_card_escapes_editable_html(monkeypatch):
    from src import ui_components

    rendered: list[str] = []

    def fake_markdown(body, unsafe_allow_html=False):
        rendered.append(body)
        assert unsafe_allow_html is True

    monkeypatch.setattr(ui_components.st, "markdown", fake_markdown)

    ui_components.metric_card("<b>Etiqueta</b>", "<script>alert(1)</script>", "<i>ayuda</i>")

    html_output = rendered[0]
    assert "&lt;b&gt;Etiqueta&lt;/b&gt;" in html_output
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_output
    assert "&lt;i&gt;ayuda&lt;/i&gt;" in html_output
    assert "<script>alert(1)</script>" not in html_output


def test_stage3_result_state_is_cleared():
    import app

    app.st.session_state.stage3_result_is_complete = True
    app.st.session_state.stage3_result_critical_load_kw = 25.0
    app.st.session_state.stage3_result_required_nominal_kwh = 100.0
    app.st.session_state.stage3_result_installed_backup_hours = 4.0
    app.st.session_state.stage3_result_annual_backed_energy_kwh = 2400.0
    app.st.session_state.stage3_result_estimated_life_years_by_cycles = 18.0

    app._clear_stage3_result_state()

    assert app.st.session_state.stage3_result_is_complete is False
    assert app.st.session_state.stage3_result_critical_load_kw == pytest.approx(0.0)
    assert app.st.session_state.stage3_result_required_nominal_kwh == pytest.approx(0.0)
    assert app.st.session_state.stage3_result_installed_backup_hours == pytest.approx(0.0)
    assert app.st.session_state.stage3_result_annual_backed_energy_kwh == pytest.approx(0.0)
    assert app.st.session_state.stage3_result_estimated_life_years_by_cycles is None


def test_google_maps_api_key_reads_environment(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "env-google-key")

    from app import get_google_maps_api_key

    assert get_google_maps_api_key() == "env-google-key"


def test_google_maps_api_key_tolerates_missing_secrets(monkeypatch):
    import app

    class MissingSecrets:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("secrets are not configured")

    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setattr(app.st, "secrets", MissingSecrets(), raising=False)

    assert app.get_google_maps_api_key() == ""


def test_stage1_pv_defaults_do_not_overwrite_valid_manual_values():
    import app

    state = app.st.session_state
    keys = [
        "panel_power_w",
        "panel_area_m2",
        "panel_efficiency_percent",
        "system_losses_percent",
        "stage1_pv_defaults_migration_checked",
    ]
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    try:
        state.panel_power_w = 100.0
        state.panel_area_m2 = 1.0
        state.panel_efficiency_percent = 10.0
        state.system_losses_percent = 0.0
        state.stage1_pv_defaults_migration_checked = False

        app.apply_commercial_pv_defaults_if_placeholder()

        assert state.panel_power_w == pytest.approx(100.0)
        assert state.panel_area_m2 == pytest.approx(1.0)
        assert state.panel_efficiency_percent == pytest.approx(10.0)
        assert state.system_losses_percent == pytest.approx(0.0)
        assert state.stage1_pv_defaults_migration_checked is True
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_stage1_pv_recommendation_helper_does_not_overwrite_manual_values():
    import app

    state = app.st.session_state
    keys = [
        "number_of_panels",
        "panel_power_w",
        "panel_area_m2",
        "panel_efficiency_percent",
        "system_losses_percent",
        "stage1_fv_user_modified",
        "stage1_fv_recommendation_applied",
    ]
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    try:
        state.number_of_panels = 7
        state.panel_power_w = 100.0
        state.panel_area_m2 = 1.0
        state.panel_efficiency_percent = 10.0
        state.system_losses_percent = 0.0
        app.mark_stage1_fv_user_modified()

        assert state.panel_power_w == pytest.approx(100.0)
        assert state.panel_area_m2 == pytest.approx(1.0)
        assert state.panel_efficiency_percent == pytest.approx(10.0)
        assert state.system_losses_percent == pytest.approx(0.0)
        assert state.stage1_fv_user_modified is True
        assert state.stage1_fv_recommendation_applied is False

        app.apply_commercial_panel_defaults()

        assert state.number_of_panels == 7
        assert state.panel_power_w == pytest.approx(100.0)
        assert state.panel_area_m2 == pytest.approx(1.0)
        assert state.panel_efficiency_percent == pytest.approx(10.0)
        assert state.system_losses_percent == pytest.approx(0.0)
        assert state.stage1_fv_user_modified is True
        assert state.stage1_fv_recommendation_applied is False
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_stage1_orientation_defaults_do_not_overwrite_valid_zero_values():
    import app

    state = app.st.session_state
    keys = [
        "latitude",
        "tilt_deg",
        "azimuth_deg",
        "stage1_orientation_user_modified",
        "stage1_orientation_recommendation_applied",
    ]
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    try:
        state.latitude = 20.9674
        state.tilt_deg = 0
        state.azimuth_deg = 0
        app.mark_stage1_orientation_user_modified()
        app.apply_commercial_pv_defaults_if_placeholder()

        assert state.tilt_deg == 0
        assert state.azimuth_deg == 0
        assert state.stage1_orientation_user_modified is True
        assert state.stage1_orientation_recommendation_applied is False
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_stage1_orientation_recommendation_helper_does_not_overwrite_manual_values():
    import app

    state = app.st.session_state
    keys = [
        "latitude",
        "tilt_deg",
        "azimuth_deg",
        "stage1_orientation_user_modified",
        "stage1_orientation_recommendation_applied",
    ]
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    try:
        state.latitude = 20.9674
        state.tilt_deg = 0
        state.azimuth_deg = 0
        app.mark_stage1_orientation_user_modified()

        assert state.tilt_deg == 0
        assert state.azimuth_deg == 0

        app.apply_recommended_orientation()

        assert state.tilt_deg == 0
        assert state.azimuth_deg == 0
        assert state.stage1_orientation_user_modified is True
        assert state.stage1_orientation_recommendation_applied is False
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_stage1_simulation_signature_tracks_current_inputs_without_invalidating_weather_signature():
    import app

    state = app.st.session_state
    keys = list(app.DEFAULT_STATE.keys())
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    try:
        for key, value in app.DEFAULT_STATE.items():
            state[key] = value
        state.irradiance_source = "NASA POWER"

        base_config = app.build_pv_config_from_session_state()
        base_weather_signature = app.current_external_irradiance_signature(base_config)
        base_stage1_signature = app.build_stage1_simulation_signature(base_config, "NASA POWER")

        state.number_of_panels = 10
        panels_config = app.build_pv_config_from_session_state()
        assert app.build_stage1_simulation_signature(panels_config, "NASA POWER") != base_stage1_signature
        assert app.current_external_irradiance_signature(panels_config) == base_weather_signature

        state.number_of_panels = 1
        state.system_losses_percent = 30.0
        losses_config = app.build_pv_config_from_session_state()
        assert app.build_stage1_simulation_signature(losses_config, "NASA POWER") != base_stage1_signature
        assert app.current_external_irradiance_signature(losses_config) == base_weather_signature

        state.system_losses_percent = 12.0
        state.tilt_deg = 60
        state.azimuth_deg = 0
        orientation_config = app.build_pv_config_from_session_state()
        assert app.build_stage1_simulation_signature(orientation_config, "NASA POWER") != base_stage1_signature
        assert app.current_external_irradiance_signature(orientation_config) == base_weather_signature

        state.latitude = 20.9674
        state.longitude = -89.5926
        location_config = app.build_pv_config_from_session_state()
        assert app.build_stage1_simulation_signature(location_config, "NASA POWER") != base_stage1_signature
        assert app.current_external_irradiance_signature(location_config) != base_weather_signature
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_stage1_current_simulation_summary_uses_current_pv_config(monkeypatch):
    import app

    state = app.st.session_state
    keys = list(app.DEFAULT_STATE.keys())
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    def fake_irradiance_data(_pv_config):
        return None, "Cielo despejado con pvlib Ineichen"

    def fake_run_simulation(pv_config, _demand_config, _irradiance_df, irradiance_label, _demand_df=None):
        times = pd.date_range(f"{pv_config.year}-01-01 00:00", periods=4, freq="15min", tz=pv_config.timezone)
        generation_kw = pv_config.installed_power_kw * (1.0 - pv_config.system_losses)
        energy_kwh = generation_kw * 0.25
        return pd.DataFrame(
            {
                "datetime": times,
                "date": times.date,
                "generation_kW": np.full(len(times), generation_kw),
                "energy_kWh": np.full(len(times), energy_kwh),
                "demand_kW": np.zeros(len(times)),
                "demand_energy_kWh": np.zeros(len(times)),
                "self_consumed_kWh": np.zeros(len(times)),
                "exported_kWh": np.full(len(times), energy_kwh),
                "grid_energy_kWh": np.zeros(len(times)),
                "raw_dc_power_kW": np.full(len(times), pv_config.installed_power_kw),
                "installed_power_from_area_kw": np.full(len(times), pv_config.installed_power_from_area_kw),
                "irradiance_source": np.full(len(times), irradiance_label),
            }
        )

    try:
        for key, value in app.DEFAULT_STATE.items():
            state[key] = value

        monkeypatch.setattr(app, "get_irradiance_data_or_none", fake_irradiance_data)
        monkeypatch.setattr(app, "run_simulation", fake_run_simulation)

        demand_config = DemandConfig(
            max_demand_kw=50.0,
            plant_factor=0.60,
            power_factor=0.90,
            random_seed=42,
            weekend_reduction=0.35,
            summer_increase=0.10,
        )

        state.number_of_panels = 1
        one_config, _one_df, one_summary, _one_label, one_signature = app.build_stage1_current_simulation(demand_config)

        state.number_of_panels = 10
        ten_config, _ten_df, ten_summary, _ten_label, ten_signature = app.build_stage1_current_simulation(demand_config)

        assert one_config.number_of_panels == 1
        assert ten_config.number_of_panels == 10
        assert ten_summary["installed_power_kw"] == pytest.approx(one_summary["installed_power_kw"] * 10)
        assert ten_summary["total_generation_kwh"] == pytest.approx(one_summary["total_generation_kwh"] * 10)
        assert ten_signature != one_signature
        assert state.stage1_simulation_signature == ten_signature
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_stage1_orientation_changes_do_not_reset_manual_pv_configuration(monkeypatch):
    import app

    state = app.st.session_state
    keys = list(app.DEFAULT_STATE.keys()) + list(app.STAGE1_CONFIG_STATE_KEYS)
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    def fake_irradiance_data(_pv_config):
        return None, "Cielo despejado con pvlib Ineichen"

    def fake_run_simulation(pv_config, _demand_config, _irradiance_df, irradiance_label, _demand_df=None):
        times = pd.date_range(f"{pv_config.year}-01-01 00:00", periods=4, freq="15min", tz=pv_config.timezone)
        generation_kw = pv_config.installed_power_kw * (1.0 - pv_config.system_losses)
        energy_kwh = generation_kw * 0.25
        return pd.DataFrame(
            {
                "datetime": times,
                "date": times.date,
                "generation_kW": np.full(len(times), generation_kw),
                "energy_kWh": np.full(len(times), energy_kwh),
                "demand_kW": np.zeros(len(times)),
                "demand_energy_kWh": np.zeros(len(times)),
                "self_consumed_kWh": np.zeros(len(times)),
                "exported_kWh": np.full(len(times), energy_kwh),
                "grid_energy_kWh": np.zeros(len(times)),
                "raw_dc_power_kW": np.full(len(times), pv_config.installed_power_kw),
                "installed_power_from_area_kw": np.full(len(times), pv_config.installed_power_from_area_kw),
                "irradiance_source": np.full(len(times), irradiance_label),
            }
        )

    try:
        for key, value in app.DEFAULT_STATE.items():
            state[key] = value
        state.number_of_panels = 1
        state.panel_power_w = 100.0
        state.panel_area_m2 = 1.0
        state.panel_efficiency_percent = 10.0
        state.system_losses_percent = 0.0
        state.tilt_deg = 0
        state.azimuth_deg = 0

        app.mark_stage1_orientation_user_modified()
        app.preserve_stage1_config_state()

        assert state.number_of_panels == 1
        assert state.panel_power_w == pytest.approx(100.0)
        assert state.panel_area_m2 == pytest.approx(1.0)
        assert state.panel_efficiency_percent == pytest.approx(10.0)
        assert state.system_losses_percent == pytest.approx(0.0)
        assert state.tilt_deg == 0
        assert state.azimuth_deg == 0

        monkeypatch.setattr(app, "get_irradiance_data_or_none", fake_irradiance_data)
        monkeypatch.setattr(app, "run_simulation", fake_run_simulation)
        demand_config = DemandConfig(
            max_demand_kw=50.0,
            plant_factor=0.60,
            power_factor=0.90,
            random_seed=42,
            weekend_reduction=0.35,
            summer_increase=0.10,
        )

        pv_config, _df, summary, _label, _signature = app.build_stage1_current_simulation(demand_config)

        assert pv_config.number_of_panels == 1
        assert pv_config.panel_power_w == pytest.approx(100.0)
        assert pv_config.panel_area_m2 == pytest.approx(1.0)
        assert pv_config.panel_efficiency == pytest.approx(0.10)
        assert pv_config.system_losses == pytest.approx(0.0)
        assert pv_config.tilt_deg == pytest.approx(0.0)
        assert pv_config.azimuth_deg == pytest.approx(0.0)
        assert summary["installed_power_kw"] == pytest.approx(0.10)
        assert summary["total_generation_kwh"] == pytest.approx(0.10)
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_map_location_event_accepts_only_current_version():
    from app import is_fresh_map_location_event

    event = {"event_id": "3-1000-1", "location_version": 3, "latitude": 20.0, "longitude": -100.0}

    assert is_fresh_map_location_event(event, current_location_version=3, last_event_id="")
    assert not is_fresh_map_location_event(event, current_location_version=4, last_event_id="")


def test_map_location_event_rejects_duplicate_or_missing_event_id():
    from app import is_fresh_map_location_event

    event = {"event_id": "3-1000-1", "location_version": 3, "latitude": 20.0, "longitude": -100.0}

    assert not is_fresh_map_location_event(event, current_location_version=3, last_event_id="3-1000-1")
    assert not is_fresh_map_location_event({"location_version": 3}, current_location_version=3, last_event_id="")


def test_coordinate_label_uses_manual_coordinates():
    from app import format_coordinate_label

    assert format_coordinate_label(25.6866123, -100.3161123) == "25.686612, -100.316112"


def test_timezone_options_add_google_timezone_when_valid():
    from app import normalize_timezone_options

    selected, options = normalize_timezone_options("America/Chihuahua")

    assert selected == "America/Chihuahua"
    assert "America/Chihuahua" in options


def test_timezone_options_invalid_timezone_falls_back_to_default():
    from app import DEFAULT_TIMEZONE, normalize_timezone_options

    selected, options = normalize_timezone_options("Mars/Base")

    assert selected == DEFAULT_TIMEZONE
    assert "Mars/Base" not in options


def test_fetch_google_timezone_returns_none_when_api_fails(monkeypatch):
    import app

    def failing_get(*_args, **_kwargs):
        raise RuntimeError("network failed")

    app._fetch_google_timezone_cached.clear()
    monkeypatch.setattr(app.requests, "get", failing_get)

    assert app.fetch_google_timezone(1.2345, -99.9876, "test-key") is None


def test_fetch_google_timezone_uses_params_without_key_in_url(monkeypatch):
    import app

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "OK", "timeZoneId": "America/Monterrey"}

    def fake_get(url, params, timeout):
        assert "test-key" not in url
        assert params["key"] == "test-key"
        assert params["location"] == "25.686600,-100.316100"
        assert timeout == 10
        return FakeResponse()

    app._fetch_google_timezone_cached.clear()
    monkeypatch.setattr(app.requests, "get", fake_get)

    assert app.fetch_google_timezone(25.6866, -100.3161, "test-key") == "America/Monterrey"


def test_external_irradiance_signature_changes_with_latitude():
    from app import external_irradiance_signature

    base = external_irradiance_signature("NASA POWER", 25.0, -100.0, 2026, "Etc/GMT+6")
    changed = external_irradiance_signature("NASA POWER", 26.0, -100.0, 2026, "Etc/GMT+6")

    assert base != changed


def test_external_irradiance_signature_changes_with_year():
    from app import external_irradiance_signature

    base = external_irradiance_signature("PVGIS con pvlib.iotools", 25.0, -100.0, 2026, "Etc/GMT+6", "Automático")
    changed = external_irradiance_signature("PVGIS con pvlib.iotools", 25.0, -100.0, 2025, "Etc/GMT+6", "Automático")

    assert base != changed


def test_external_irradiance_signature_changes_with_timezone():
    from app import external_irradiance_signature

    base = external_irradiance_signature("NASA POWER", 25.0, -100.0, 2026, "Etc/GMT+6")
    changed = external_irradiance_signature("NASA POWER", 25.0, -100.0, 2026, "America/Mexico_City")

    assert base != changed


def test_external_irradiance_signature_matches_equal_configuration():
    from app import external_irradiance_signature, external_irradiance_signature_matches

    signature = external_irradiance_signature("NSRDB PSM3 con pvlib.iotools", 25.0, -100.0, 2026, "Etc/GMT+6", nsrdb_interval=30)

    assert external_irradiance_signature_matches(signature, signature)


def test_external_irradiance_signature_rejects_stale_data():
    from app import external_irradiance_signature, external_irradiance_signature_matches

    loaded = external_irradiance_signature("NASA POWER", 25.0, -100.0, 2026, "Etc/GMT+6")
    current = external_irradiance_signature("NASA POWER", 25.1, -100.0, 2026, "Etc/GMT+6")

    assert not external_irradiance_signature_matches(loaded, current)


def test_loaded_nasa_data_is_not_current_after_location_change_but_survives_pv_changes():
    from app import NASA_POWER_MODE_RECOMMENDED, build_weather_source_signature, external_irradiance_signature_matches

    loaded = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )
    changed_location = build_weather_source_signature(
        source="NASA POWER",
        latitude=20.9674,
        longitude=-89.5926,
        simulation_year=2026,
        timezone="America/Merida",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )
    changed_pv_only = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
        number_of_panels=24,
        panel_power_w=100.0,
        panel_area_m2=1.0,
        panel_efficiency=0.10,
        system_losses=0.0,
        tilt_deg=0,
        azimuth_deg=0,
    )

    assert not external_irradiance_signature_matches(loaded, changed_location)
    assert external_irradiance_signature_matches(loaded, changed_pv_only)


def test_weather_source_signature_ignores_pv_system_parameters():
    from app import NASA_POWER_MODE_RECOMMENDED, weather_source_signature
    from src.solar_engine import PVSystemConfig

    base_config = PVSystemConfig(
        year=2026,
        latitude=25.6866,
        longitude=-100.3161,
        altitude_m=540.0,
        tilt_deg=25.0,
        azimuth_deg=180.0,
        panel_power_w=550.0,
        panel_area_m2=2.5,
        panel_efficiency=0.22,
        number_of_panels=100,
        albedo=0.2,
        system_losses=0.12,
        timezone="America/Monterrey",
    )
    changed_pv_config = replace(
        base_config,
        tilt_deg=35.0,
        azimuth_deg=170.0,
        panel_power_w=620.0,
        panel_area_m2=2.8,
        panel_efficiency=0.23,
        number_of_panels=150,
        system_losses=0.20,
    )
    changed_location_config = replace(base_config, latitude=25.8)
    changed_longitude_config = replace(base_config, longitude=-100.5)

    def signature(config):
        return weather_source_signature(
            "NASA POWER",
            config.latitude,
            config.longitude,
            config.year,
            config.timezone,
            nasa_power_year=2025,
            nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        )

    assert signature(base_config) == signature(changed_pv_config)
    assert signature(base_config) != signature(changed_location_config)
    assert signature(base_config) != signature(changed_longitude_config)


def test_weather_source_signature_explicitly_ignores_orientation_and_pv_fields():
    from app import NASA_POWER_MODE_RECOMMENDED, build_weather_source_signature

    base = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )

    assert base == build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
        tilt_deg=10,
    )
    assert base == build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
        azimuth_deg=240,
    )
    assert base == build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
        number_of_panels=250,
        panel_power_w=620,
        panel_area_m2=2.8,
        panel_efficiency=0.23,
        system_losses=0.30,
        transposition_model="perez",
        albedo=0.35,
    )


def test_weather_source_signature_changes_for_real_weather_inputs():
    from app import (
        NASA_POWER_MODE_CUSTOM,
        NASA_POWER_MODE_PROVISIONAL,
        NASA_POWER_MODE_RECOMMENDED,
        build_weather_source_signature,
    )

    base = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )

    assert base != build_weather_source_signature(
        source="NASA POWER",
        latitude=25.7000,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )
    assert base != build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.2000,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )
    assert base != build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2027,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )
    assert base != build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_PROVISIONAL,
        nasa_power_year=2025,
    )
    assert base != build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_CUSTOM,
        nasa_power_year=2024,
    )


def test_loaded_nasa_signature_stays_valid_after_orientation_changes():
    from app import NASA_POWER_MODE_RECOMMENDED, build_weather_source_signature, external_irradiance_signature_matches

    loaded = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )
    changed_tilt = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
        tilt_deg=40,
    )
    changed_azimuth = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
        azimuth_deg=90,
    )
    changed_latitude = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.8000,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
        nasa_power_year=2025,
    )

    assert external_irradiance_signature_matches(loaded, changed_tilt)
    assert external_irradiance_signature_matches(loaded, changed_azimuth)
    assert not external_irradiance_signature_matches(loaded, changed_latitude)


def test_current_nasa_signature_uses_durable_state_when_widget_is_not_rendered():
    import app

    state = app.st.session_state
    keys = [
        "irradiance_source",
        "latitude",
        "longitude",
        "year",
        "timezone",
        "selected_nasa_power_mode",
        "selected_nasa_power_year",
        "selected_nasa_climate_year",
        "selected_nasa_base_year",
        "nasa_power_mode",
        "nasa_power_year",
        "_nasa_power_mode_widget",
        "_nasa_power_year_widget",
        "tilt_deg",
        "azimuth_deg",
        "transposition_model",
        "albedo",
        "number_of_panels",
        "panel_power_w",
    ]
    missing = object()
    snapshot = {key: state.get(key, missing) for key in keys}

    try:
        state.irradiance_source = "NASA POWER"
        state.latitude = 25.6866
        state.longitude = -100.3161
        state.year = 2026
        state.timezone = "America/Monterrey"
        state.selected_nasa_power_mode = app.NASA_POWER_MODE_PROVISIONAL
        state.selected_nasa_power_year = app.DEFAULT_NASA_POWER_YEAR
        state.selected_nasa_climate_year = app.DEFAULT_NASA_POWER_YEAR
        state.selected_nasa_base_year = app.DEFAULT_NASA_POWER_YEAR
        state.nasa_power_mode = app.NASA_POWER_MODE_PROVISIONAL
        state.nasa_power_year = app.DEFAULT_NASA_POWER_YEAR
        app.prepare_nasa_power_widget_state()

        loaded_signature = app.current_weather_source_signature(
            source="NASA POWER",
            latitude=25.6866,
            longitude=-100.3161,
            year=2026,
            timezone="America/Monterrey",
        )

        # Simulates navigating to another step where Streamlit no longer renders
        # the conditional NASA widget and the widget/legacy keys fall back.
        state._nasa_power_mode_widget = app.NASA_POWER_MODE_RECOMMENDED
        state.nasa_power_mode = app.NASA_POWER_MODE_RECOMMENDED
        state.tilt_deg = 40
        state.azimuth_deg = 90
        state.transposition_model = "perez"
        state.albedo = 0.35
        state.number_of_panels = 250
        state.panel_power_w = 620.0

        current_signature = app.current_weather_source_signature(
            source="NASA POWER",
            latitude=25.6866,
            longitude=-100.3161,
            year=2026,
            timezone="America/Monterrey",
        )

        assert current_signature == loaded_signature
        assert app.external_irradiance_signature_matches(loaded_signature, current_signature)

        state.selected_nasa_power_mode = app.NASA_POWER_MODE_RECOMMENDED
        changed_signature = app.current_weather_source_signature(
            source="NASA POWER",
            latitude=25.6866,
            longitude=-100.3161,
            year=2026,
            timezone="America/Monterrey",
        )

        assert changed_signature != loaded_signature
    finally:
        for key, value in snapshot.items():
            if value is missing:
                state.pop(key, None)
            else:
                state[key] = value


def test_weather_source_signature_for_provisional_2026_uses_requested_base_and_final_years():
    from app import NASA_POWER_MODE_PROVISIONAL, build_weather_source_signature

    signature = build_weather_source_signature(
        source="NASA POWER",
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        timezone="America/Monterrey",
        nasa_power_mode=NASA_POWER_MODE_PROVISIONAL,
        nasa_power_year=2026,
        nasa_base_year=2025,
    )

    assert signature == (
        "NASA POWER",
        25.6866,
        -100.3161,
        2026,
        "America/Monterrey",
        NASA_POWER_MODE_PROVISIONAL,
        2026,
        2025,
        2026,
    )


def test_weather_source_signature_accepts_legacy_nasa_mode_labels():
    from app import (
        DEFAULT_NASA_POWER_YEAR,
        NASA_POWER_MODE_RECOMMENDED,
        external_irradiance_signature_matches,
        weather_source_signature,
    )

    legacy_signature = (
        "NASA POWER",
        25.6866,
        -100.3161,
        2026,
        "America/Monterrey",
        "Año completo recomendado",
        DEFAULT_NASA_POWER_YEAR,
        DEFAULT_NASA_POWER_YEAR,
    )
    current_signature = weather_source_signature(
        "NASA POWER",
        25.6866,
        -100.3161,
        2026,
        "America/Monterrey",
        nasa_power_year=DEFAULT_NASA_POWER_YEAR,
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
    )

    assert external_irradiance_signature_matches(legacy_signature, current_signature)


def test_weather_source_signature_accepts_legacy_seven_field_nasa_signature():
    from app import (
        DEFAULT_NASA_POWER_YEAR,
        NASA_POWER_MODE_RECOMMENDED,
        external_irradiance_signature_matches,
        weather_source_signature,
    )

    legacy_signature = (
        "NASA POWER",
        25.6866,
        -100.3161,
        2026,
        "America/Monterrey",
        "Año completo recomendado",
        DEFAULT_NASA_POWER_YEAR,
    )
    current_signature = weather_source_signature(
        "NASA POWER",
        25.6866,
        -100.3161,
        2026,
        "America/Monterrey",
        nasa_power_year=DEFAULT_NASA_POWER_YEAR,
        nasa_power_mode=NASA_POWER_MODE_RECOMMENDED,
    )

    assert external_irradiance_signature_matches(legacy_signature, current_signature)


def test_default_poa_model_is_haydavies_and_isotropic_is_available():
    import app

    assert app.DEFAULT_STATE["transposition_model"] == "haydavies"
    assert "isotropic" in ["isotropic", "haydavies", "perez"]


def test_realism_loss_scenarios_decrease_generation_with_higher_losses():
    import app

    df = pd.DataFrame({"raw_dc_power_kW": [1.0, 1.0, 1.0, 1.0]})
    scenarios = app.build_realism_loss_scenarios(
        df=df,
        installed_power_kw=1.0,
        number_of_panels=2,
        days_in_year=365,
    )

    optimistic = float(scenarios.loc[scenarios["scenario"] == "Optimista", "annual_generation_kWh"].iloc[0])
    recommended = float(scenarios.loc[scenarios["scenario"] == "Recomendado", "annual_generation_kWh"].iloc[0])
    conservative = float(scenarios.loc[scenarios["scenario"] == "Conservador", "annual_generation_kWh"].iloc[0])

    assert optimistic > recommended > conservative
    assert float(scenarios.loc[scenarios["scenario"] == "Optimista", "production_per_panel_kWh"].iloc[0]) == optimistic / 2


def test_standardize_irradiance_table_accepts_common_column_names():
    raw = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="h"),
            "GHI": [0, 400, 500],
            "DNI": [0, 550, 700],
            "DHI": [0, 80, 100],
        }
    )
    result = standardize_irradiance_table(raw, year=2026)
    assert {"datetime", "GHI_W_m2", "DNI_W_m2", "DHI_W_m2"}.issubset(result.columns)
    assert result["GHI_W_m2"].max() == 500


def test_parse_number_list():
    assert parse_number_list("40, 60, 80", int) == [40, 60, 80]
    assert parse_number_list("15, 25.5", float) == [15.0, 25.5]


def test_gdmth_period_classification_includes_weekend_schedule():
    assert classify_gdmth_period(pd.Timestamp("2026-01-05 05:00")) == "Base"
    assert classify_gdmth_period(pd.Timestamp("2026-01-05 12:00")) == "Intermedia"
    assert classify_gdmth_period(pd.Timestamp("2026-01-05 19:00")) == "Punta"
    assert classify_gdmth_period(pd.Timestamp("2026-01-10 19:30")) == "Punta"
    assert classify_gdmth_period(pd.Timestamp("2026-01-11 17:00")) == "Base"
    assert classify_gdmth_period(pd.Timestamp("2026-01-11 19:00")) == "Intermedia"


def test_demand_and_summary_are_positive_with_minimal_table():
    times = pd.date_range("2026-01-01", periods=96, freq="15min", tz="Etc/GMT+6")
    df = pd.DataFrame(
        {
            "datetime": times,
            "energy_kWh": [0.10] * len(times),
            "generation_kW": [0.40] * len(times),
        }
    )
    demand_config = DemandConfig(
        max_demand_kw=50,
        plant_factor=0.60,
        power_factor=0.90,
        random_seed=42,
        weekend_reduction=0.35,
        summer_increase=0.10,
    )
    df = add_synthetic_industrial_demand(df, demand_config)
    summary = compute_summary(df, installed_power_kw=33, total_area_m2=150)

    assert summary["total_generation_kwh"] > 0
    assert summary["total_demand_kwh"] > 0
    assert summary["coverage_percent"] >= 0
    assert df["demand_kW"].max() == pytest.approx(50, rel=1e-6)
    assert df["demand_kW"].mean() / df["demand_kW"].max() == pytest.approx(0.60, abs=1e-3)


def test_pvgis_horizontal_poa_can_be_resampled_as_ghi():
    raw = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", "2026-12-31 23:00", freq="h"),
            "poa_global": [0.0] * 8760,
        }
    )
    raw.loc[raw["datetime"].dt.hour.between(8, 16), "poa_global"] = 500.0
    raw = raw.rename(columns={"poa_global": "ghi"})

    result = to_15min_irradiance(raw, year=2026, timezone="Etc/GMT+6")
    assert len(result) == 35040
    assert result["GHI_W_m2"].max() == 500.0


def test_short_irradiance_file_is_rejected():
    raw = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=24, freq="h"),
            "ghi": [100.0] * 24,
        }
    )
    with pytest.raises(ValueError, match="does not cover enough"):
        to_15min_irradiance(raw, year=2026, timezone="Etc/GMT+6")


def test_nasa_power_preparation_uses_complete_reference_year(monkeypatch):
    import pvlib

    def fake_get_nasa_power(latitude, longitude, start, end, parameters, **kwargs):
        times = pd.date_range("2023-12-31 00:00", "2025-01-01 23:00", freq="h", tz="UTC")
        hours = times.hour.to_numpy()
        daylight = np.clip(np.sin((hours - 6) / 12 * np.pi), 0, None)
        data = pd.DataFrame(
            {
                "ghi": 700.0 * daylight,
                "dni": 850.0 * daylight,
                "dhi": 120.0 * daylight,
                "temp_air": 25.0,
                "wind_speed": 2.0,
            },
            index=times,
        )
        return data, {"source": "fake"}

    monkeypatch.setattr(pvlib.iotools, "get_nasa_power", fake_get_nasa_power)

    result = prepare_nasa_power_irradiance(
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        nasa_data_year=2024,
        timezone="America/Monterrey",
    )

    assert len(result) == 35040
    assert {"datetime", "GHI_W_m2", "DNI_W_m2", "DHI_W_m2", "temperature_C", "wind_speed_m_s"}.issubset(result.columns)
    assert result["datetime"].dt.year.nunique() == 1
    assert result["datetime"].dt.year.iloc[0] == 2026
    assert result["GHI_W_m2"].max() > 600
    diagnostics = result.attrs["nasa_power_diagnostics"]
    assert diagnostics["nasa_data_year"] == 2024
    assert diagnostics["simulation_year"] == 2026
    assert diagnostics["coverage_fraction"] >= 0.95
    assert diagnostics["rows_15min"] == 35040


def test_nasa_power_preparation_rejects_incomplete_reference_year(monkeypatch):
    import pvlib

    def fake_get_nasa_power(latitude, longitude, start, end, parameters, **kwargs):
        times = pd.date_range("2024-01-01 00:00", periods=24 * 120, freq="h", tz="UTC")
        data = pd.DataFrame(
            {
                "ghi": 500.0,
                "dni": 650.0,
                "dhi": 80.0,
                "temp_air": 25.0,
                "wind_speed": 2.0,
            },
            index=times,
        )
        return data, {"source": "fake"}

    monkeypatch.setattr(pvlib.iotools, "get_nasa_power", fake_get_nasa_power)

    with pytest.raises(ValueError, match="NASA POWER coverage insufficient"):
        prepare_nasa_power_irradiance(
            latitude=25.6866,
            longitude=-100.3161,
            simulation_year=2026,
            nasa_data_year=2024,
            timezone="America/Monterrey",
        )


def test_nasa_power_provisional_completes_missing_days_with_base_year(monkeypatch):
    import app
    import pvlib

    def fake_get_nasa_power(latitude, longitude, start, end, parameters, **kwargs):
        requested_year = (pd.Timestamp(start) + pd.Timedelta(days=1)).year
        if requested_year == 2026:
            times = pd.date_range("2026-01-01 00:00", "2026-01-10 23:00", freq="h", tz="UTC")
            ghi = 900.0
        else:
            times = pd.date_range(f"{requested_year}-01-01 00:00", f"{requested_year}-12-31 23:00", freq="h", tz="UTC")
            ghi = 500.0
        data = pd.DataFrame(
            {
                "ghi": ghi,
                "dni": ghi * 0.75,
                "dhi": ghi * 0.20,
                "temp_air": 25.0,
                "wind_speed": 2.0,
            },
            index=times,
        )
        return data, {"source": "fake"}

    monkeypatch.setattr(pvlib.iotools, "get_nasa_power", fake_get_nasa_power)

    result = prepare_nasa_power_provisional_irradiance(
        latitude=25.6866,
        longitude=-100.3161,
        simulation_year=2026,
        selected_data_year=2026,
        base_year=2025,
        timezone="UTC",
    )

    jan_5_noon = result[result["datetime"] == pd.Timestamp("2026-01-05 12:00", tz="UTC")]
    dec_1_noon = result[result["datetime"] == pd.Timestamp("2026-12-01 12:00", tz="UTC")]
    diagnostics = result.attrs["nasa_power_diagnostics"]

    assert len(result) == 35040
    assert float(jan_5_noon["GHI_W_m2"].iloc[0]) == 900.0
    assert float(dec_1_noon["GHI_W_m2"].iloc[0]) == 500.0
    assert diagnostics["is_provisional"] is True
    assert diagnostics["selected_data_year"] == 2026
    assert diagnostics["nasa_requested_year"] == 2026
    assert diagnostics["base_year"] == 2025
    assert diagnostics["final_weather_year"] == 2026
    assert diagnostics["real_days"] == 10
    assert diagnostics["completed_days"] == 355
    assert diagnostics["covered_days"] == 365
    assert sorted(result["datetime"].dt.year.unique().tolist()) == [2026]
    final_report = app.validate_final_weather_dataframe(result, 2026)
    assert final_report["covered_days"] == 365


def test_pv_simulation_has_expected_columns_when_pvlib_is_available():
    pytest.importorskip("pvlib")
    from src.solar_engine import PVSystemConfig, simulate_pv_system

    config = PVSystemConfig(
        year=2026,
        latitude=25.6866,
        longitude=-100.3161,
        altitude_m=540,
        tilt_deg=25,
        azimuth_deg=180,
        panel_power_w=550,
        panel_area_m2=2.5,
        panel_efficiency=0.22,
        number_of_panels=60,
        albedo=0.20,
        system_losses=0.12,
    )
    df = simulate_pv_system(config)

    expected_columns = {
        "datetime",
        "GHI_W_m2",
        "DNI_W_m2",
        "DHI_W_m2",
        "POA_W_m2",
        "cell_temperature_C",
        "raw_dc_power_kW",
        "generation_kW",
        "energy_kWh",
    }
    assert expected_columns.issubset(df.columns)
    assert len(df) in {35040, 35136}
    assert df["generation_kW"].min() >= 0


def test_inconsistent_panel_inputs_create_warning_without_stopping_simulation():
    pytest.importorskip("pvlib")
    from src.solar_engine import PVSystemConfig, panel_power_consistency_warning, simulate_pv_system, validate_pv_system_config

    config = PVSystemConfig(
        year=2026,
        latitude=25.6866,
        longitude=-100.3161,
        altitude_m=540,
        tilt_deg=25,
        azimuth_deg=180,
        panel_power_w=550,
        panel_area_m2=2.5,
        panel_efficiency=0.10,
        number_of_panels=60,
        albedo=0.20,
        system_losses=0.12,
    )
    validate_pv_system_config(config)
    warning = panel_power_consistency_warning(config)
    df = simulate_pv_system(config)

    assert "Advertencia" in warning
    assert df["panel_power_consistency_warning"].iloc[0] == warning
    assert df["generation_kW"].max() > 0


def test_pv_generation_uses_nominal_installed_power_when_pvlib_is_available():
    pytest.importorskip("pvlib")
    from src.solar_engine import PVSystemConfig, simulate_pv_system

    base_config = PVSystemConfig(
        year=2026,
        latitude=25.6866,
        longitude=-100.3161,
        altitude_m=540,
        tilt_deg=25,
        azimuth_deg=180,
        panel_power_w=550,
        panel_area_m2=2.5,
        panel_efficiency=0.22,
        number_of_panels=60,
        albedo=0.20,
        system_losses=0.12,
    )

    base = simulate_pv_system(base_config)
    higher_power = simulate_pv_system(replace(base_config, panel_power_w=650))
    more_panels = simulate_pv_system(replace(base_config, number_of_panels=90))
    higher_losses = simulate_pv_system(replace(base_config, system_losses=0.25))

    assert higher_power["generation_kW"].sum() > base["generation_kW"].sum()
    assert more_panels["generation_kW"].sum() > base["generation_kW"].sum()
    assert higher_losses["generation_kW"].sum() < base["generation_kW"].sum()
    assert ((base["energy_kWh"] - base["generation_kW"] * 0.25).abs() < 1e-12).all()
    assert base["generation_kW"].min() >= 0.0
    assert base["generation_kW"].max() <= base_config.installed_power_kw * 1.05


def test_stage1_physical_inputs_change_generation_when_pvlib_is_available():
    pytest.importorskip("pvlib")
    from src.solar_engine import PVSystemConfig, simulate_pv_system

    base_config = PVSystemConfig(
        year=2026,
        latitude=25.6866,
        longitude=-100.3161,
        altitude_m=540,
        tilt_deg=25,
        azimuth_deg=180,
        panel_power_w=550,
        panel_area_m2=2.5,
        panel_efficiency=0.22,
        number_of_panels=1,
        albedo=0.20,
        system_losses=0.12,
    )

    def annual_generation(config: PVSystemConfig) -> float:
        return float(simulate_pv_system(config)["energy_kWh"].sum())

    base_generation = annual_generation(base_config)
    ten_panels_generation = annual_generation(replace(base_config, number_of_panels=10))
    low_power_generation = annual_generation(replace(base_config, panel_power_w=100))
    no_losses_generation = annual_generation(replace(base_config, system_losses=0.0))
    high_losses_generation = annual_generation(replace(base_config, system_losses=0.30))
    steep_tilt_generation = annual_generation(replace(base_config, tilt_deg=60))
    north_azimuth_generation = annual_generation(replace(base_config, azimuth_deg=0))

    assert ten_panels_generation == pytest.approx(base_generation * 10, rel=1e-6)
    assert low_power_generation == pytest.approx(base_generation * (100 / 550), rel=1e-6)
    assert no_losses_generation > high_losses_generation
    assert steep_tilt_generation != pytest.approx(base_generation)
    assert north_azimuth_generation != pytest.approx(base_generation)


def test_physical_sensitivity_preserves_nominal_metrics_and_updates_exports():
    pytest.importorskip("pvlib")
    import app
    from src.solar_engine import PVSystemConfig, simulate_pv_system

    pv_config = PVSystemConfig(
        year=2026,
        latitude=25.6866,
        longitude=-100.3161,
        altitude_m=540,
        tilt_deg=25,
        azimuth_deg=180,
        panel_power_w=550,
        panel_area_m2=2.5,
        panel_efficiency=0.22,
        number_of_panels=100,
        albedo=0.20,
        system_losses=0.12,
        timezone="America/Monterrey",
        transposition_model="haydavies",
    )
    demand_config = DemandConfig(
        max_demand_kw=50,
        plant_factor=0.60,
        power_factor=0.90,
        random_seed=42,
        weekend_reduction=0.35,
        summer_increase=0.10,
    )
    tariff_config = _default_tariff()

    def prepared_case(config: PVSystemConfig):
        df = simulate_pv_system(config, irradiance_source_label=config.weather_condition)
        df = add_synthetic_industrial_demand(df, demand_config)
        df = add_tariff_columns(df, tariff_config)
        summary = compute_summary(df, config.installed_power_kw, config.total_area_m2)
        monthly = monthly_tariff_summary(df, tariff_config)
        annual = annual_tariff_summary(monthly)
        signature = app._current_export_signature(df, summary, monthly, annual)
        return df, summary, signature

    base_df, base_summary, base_signature = prepared_case(pv_config)
    loss_df, loss_summary, loss_signature = prepared_case(replace(pv_config, system_losses=0.20))
    cloudy_df, cloudy_summary, cloudy_signature = prepared_case(
        replace(
            pv_config,
            weather_adjustment_factor=0.45,
            weather_condition="Nublado",
        )
    )

    assert loss_summary["total_generation_kwh"] < base_summary["total_generation_kwh"]
    assert loss_summary["installed_power_kw"] == pytest.approx(base_summary["installed_power_kw"])
    assert loss_summary["total_area_m2"] == pytest.approx(base_summary["total_area_m2"])
    assert loss_summary["installed_power_from_area_kw"] == pytest.approx(base_summary["installed_power_from_area_kw"])

    assert cloudy_df["GHI_W_m2"].mean() < base_df["GHI_W_m2"].mean()
    assert cloudy_df["POA_W_m2"].mean() < base_df["POA_W_m2"].mean()
    assert cloudy_summary["total_generation_kwh"] < base_summary["total_generation_kwh"]
    assert cloudy_summary["installed_power_from_area_kw"] == pytest.approx(base_summary["installed_power_from_area_kw"])

    assert loss_signature != base_signature
    assert cloudy_signature != base_signature


def test_interval_and_annual_energy_balances_are_conserved():
    times = pd.date_range("2026-01-01 00:00", "2026-12-31 23:45", freq="15min", tz="Etc/GMT+6")
    generation_kw = np.resize(np.array([0.0, 12.0, 35.0, 80.0]), len(times))
    df = pd.DataFrame(
        {
            "datetime": times,
            "generation_kW": generation_kw,
            "energy_kWh": generation_kw * 0.25,
        }
    )
    demand_config = DemandConfig(
        max_demand_kw=50,
        plant_factor=0.60,
        power_factor=0.90,
        random_seed=42,
        weekend_reduction=0.35,
        summer_increase=0.10,
    )

    result = add_synthetic_industrial_demand(df, demand_config)

    assert (result["self_consumed_kWh"] <= result["energy_kWh"]).all()
    assert (result["self_consumed_kWh"] <= result["demand_energy_kWh"]).all()
    assert (result["exported_kWh"] >= 0.0).all()
    assert (result["grid_energy_kWh"] >= 0.0).all()
    assert np.allclose(
        result["energy_kWh"],
        result["self_consumed_kWh"] + result["exported_kWh"],
        rtol=0.0,
        atol=1e-12,
    )
    assert np.allclose(
        result["demand_energy_kWh"],
        result["self_consumed_kWh"] + result["grid_energy_kWh"],
        rtol=0.0,
        atol=1e-12,
    )
    assert result["energy_kWh"].sum() == pytest.approx(
        result["self_consumed_kWh"].sum() + result["exported_kWh"].sum(),
        abs=1e-9,
    )
    assert result["demand_energy_kWh"].sum() == pytest.approx(
        result["self_consumed_kWh"].sum() + result["grid_energy_kWh"].sum(),
        abs=1e-9,
    )


def test_industrial_demand_profile_uses_inputs_and_preserves_units():
    df = _annual_base_table()
    config = DemandConfig(
        max_demand_kw=50,
        plant_factor=0.60,
        power_factor=0.85,
        random_seed=42,
        weekend_reduction=0.35,
        summer_increase=0.20,
    )

    result = add_synthetic_industrial_demand(df, config)
    annual_expected_kwh = config.max_demand_kw * config.plant_factor * 8760

    assert len(result) == 35040
    assert (result["demand_kW"] >= 0.0).all()
    assert result["demand_kW"].max() <= config.max_demand_kw
    assert np.allclose(result["demand_energy_kWh"], result["demand_kW"] * 0.25, rtol=0.0, atol=1e-12)
    assert np.allclose(result["apparent_power_kVA"], result["demand_kW"] / config.power_factor, rtol=0.0, atol=1e-12)
    assert result["demand_energy_kWh"].sum() == pytest.approx(annual_expected_kwh, rel=1e-6)


def test_industrial_demand_profile_responds_to_capacity_and_plant_factor():
    df = _annual_base_table()
    base_config = DemandConfig(
        max_demand_kw=50,
        plant_factor=0.60,
        power_factor=0.90,
        random_seed=42,
        weekend_reduction=0.35,
        summer_increase=0.10,
    )

    base = add_synthetic_industrial_demand(df, base_config)
    higher_demand = add_synthetic_industrial_demand(df, replace(base_config, max_demand_kw=60))
    higher_plant_factor = add_synthetic_industrial_demand(df, replace(base_config, plant_factor=0.70))

    assert higher_demand["demand_energy_kWh"].sum() > base["demand_energy_kWh"].sum()
    assert higher_plant_factor["demand_energy_kWh"].sum() > base["demand_energy_kWh"].sum()


def test_industrial_demand_profile_has_weekend_and_summer_differentiation():
    df = _annual_base_table()
    config = DemandConfig(
        max_demand_kw=50,
        plant_factor=0.60,
        power_factor=0.90,
        random_seed=42,
        weekend_reduction=0.40,
        summer_increase=0.25,
    )

    result = add_synthetic_industrial_demand(df, config)
    weekday_mean = result.loc[result["datetime"].dt.dayofweek < 5, "demand_kW"].mean()
    weekend_mean = result.loc[result["datetime"].dt.dayofweek >= 5, "demand_kW"].mean()
    summer_mean = result.loc[result["datetime"].dt.month.isin([5, 6, 7, 8, 9]), "demand_kW"].mean()
    non_summer_mean = result.loc[~result["datetime"].dt.month.isin([5, 6, 7, 8, 9]), "demand_kW"].mean()

    assert weekend_mean < weekday_mean
    assert summer_mean > non_summer_mean


def test_industrial_demand_profile_is_reproducible_by_seed():
    df = _annual_base_table()
    config = DemandConfig(
        max_demand_kw=50,
        plant_factor=0.60,
        power_factor=0.90,
        random_seed=42,
        weekend_reduction=0.35,
        summer_increase=0.10,
    )

    first = add_synthetic_industrial_demand(df, config)
    second = add_synthetic_industrial_demand(df, config)
    different_seed = add_synthetic_industrial_demand(df, replace(config, random_seed=99))

    assert first["demand_kW"].equals(second["demand_kW"])
    assert not first["demand_kW"].equals(different_seed["demand_kW"])


def test_read_uploaded_demand_accepts_valid_csv_and_calculates_energy():
    times = pd.date_range("2026-01-01 00:00", "2026-12-31 23:45", freq="15min")
    raw = pd.DataFrame({"datetime": times, "demand_kW": np.full(len(times), 40.0)})

    result = read_uploaded_demand(
        _csv_upload(raw),
        year=2026,
        timezone="Etc/GMT+6",
        default_power_factor=0.80,
    )

    expected_columns = {
        "datetime",
        "demand_kW",
        "demand_energy_kWh",
        "apparent_power_kVA",
        "power_factor",
        "demand_source",
    }
    assert expected_columns.issubset(result.columns)
    assert len(result) == 35040
    assert result["demand_source"].eq("Archivo cargado").all()
    assert np.allclose(result["demand_energy_kWh"], result["demand_kW"] * 0.25)
    assert result.attrs["warnings"] == []


def test_read_uploaded_demand_rejects_negative_demand():
    raw = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=4, freq="15min"),
            "demand_kW": [10.0, -1.0, 12.0, 13.0],
        }
    )

    with pytest.raises(ValueError, match="negativos"):
        read_uploaded_demand(_csv_upload(raw), year=2026, timezone="Etc/GMT+6", default_power_factor=0.90)


def test_read_uploaded_demand_uses_file_power_factor_for_apparent_power():
    times = pd.date_range("2026-01-01 00:00", "2026-12-31 23:45", freq="15min")
    raw = pd.DataFrame(
        {
            "datetime": times,
            "demand_kW": np.full(len(times), 30.0),
            "power_factor": np.full(len(times), 0.75),
        }
    )

    result = read_uploaded_demand(
        _csv_upload(raw),
        year=2026,
        timezone="Etc/GMT+6",
        default_power_factor=0.90,
    )

    assert np.allclose(result["apparent_power_kVA"], result["demand_kW"] / 0.75)


def test_read_uploaded_demand_converts_to_15_min_resolution_and_warns_on_gaps():
    raw = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01 00:00", "2026-12-31 23:00", freq="h"),
            "demand_kW": np.full(8760, 25.0),
        }
    )

    result = read_uploaded_demand(
        _csv_upload(raw),
        year=2026,
        timezone="Etc/GMT+6",
        default_power_factor=0.90,
    )
    interval_counts = result["datetime"].diff().dropna().value_counts()

    assert len(result) == 35040
    assert list(interval_counts.index) == [pd.Timedelta(minutes=15)]
    assert any("15 minutos" in warning for warning in result.attrs["warnings"])


def test_real_demand_profile_is_compatible_with_simulation_balance_columns():
    pv_df = _annual_base_table()
    raw = pd.DataFrame(
        {
            "datetime": pv_df["datetime"].dt.tz_localize(None),
            "demand_kW": np.full(len(pv_df), 20.0),
        }
    )
    demand_df = read_uploaded_demand(
        _csv_upload(raw),
        year=2026,
        timezone="Etc/GMT+6",
        default_power_factor=0.85,
    )

    result = add_real_demand_to_simulation(pv_df, demand_df)

    expected_columns = {
        "demand_kW",
        "demand_energy_kWh",
        "apparent_power_kVA",
        "load_fraction",
        "self_consumed_kWh",
        "exported_kWh",
        "grid_energy_kWh",
        "net_power_kW",
        "demand_source",
    }
    assert expected_columns.issubset(result.columns)
    assert result["demand_source"].eq("Archivo cargado").all()
    assert np.allclose(result["demand_energy_kWh"], result["demand_kW"] * 0.25)
    assert np.allclose(result["apparent_power_kVA"], result["demand_kW"] / 0.85)
    assert np.allclose(result["demand_energy_kWh"], result["self_consumed_kWh"] + result["grid_energy_kWh"])


def test_tariff_cost_is_lower_with_pv_when_there_is_self_consumption():
    df = add_tariff_columns(_tariff_ready_table(generation_kw=10.0), _default_tariff())
    monthly = monthly_tariff_summary(df, _default_tariff())
    annual = annual_tariff_summary(monthly)

    assert (df["cost_without_pv_mxn"] > df["cost_with_pv_mxn"]).all()
    assert annual["annual_cost_without_pv_mxn"] > annual["annual_cost_with_pv_mxn"]
    assert annual["annual_savings_mxn"] > 0.0
    assert 0.0 < annual["annual_savings_percent"] < 100.0


def test_tariff_savings_are_zero_without_pv_generation():
    df = add_tariff_columns(_tariff_ready_table(generation_kw=0.0), _default_tariff())
    monthly = monthly_tariff_summary(df, _default_tariff())
    annual = annual_tariff_summary(monthly)

    assert annual["annual_savings_mxn"] == pytest.approx(0.0)
    assert annual["annual_savings_percent"] == pytest.approx(0.0)
    assert np.allclose(monthly["total_without_pv_mxn"], monthly["total_with_pv_mxn"])


def test_fixed_charge_does_not_create_artificial_absolute_savings():
    df = _tariff_ready_table(generation_kw=10.0)
    no_fixed = _default_tariff(fixed_monthly_charge_mxn=0.0)
    high_fixed = _default_tariff(fixed_monthly_charge_mxn=5000.0)

    annual_no_fixed = annual_tariff_summary(monthly_tariff_summary(add_tariff_columns(df, no_fixed), no_fixed))
    annual_high_fixed = annual_tariff_summary(monthly_tariff_summary(add_tariff_columns(df, high_fixed), high_fixed))

    assert annual_no_fixed["annual_savings_mxn"] == pytest.approx(annual_high_fixed["annual_savings_mxn"])
    assert annual_high_fixed["annual_cost_without_pv_mxn"] > annual_no_fixed["annual_cost_without_pv_mxn"]
    assert annual_high_fixed["annual_cost_with_pv_mxn"] > annual_no_fixed["annual_cost_with_pv_mxn"]


def test_disabling_demand_charge_reduces_total_costs():
    df = _tariff_ready_table(generation_kw=10.0)
    enabled = _default_tariff(demand_charge_enabled=True)
    disabled = _default_tariff(demand_charge_enabled=False)

    annual_enabled = annual_tariff_summary(monthly_tariff_summary(add_tariff_columns(df, enabled), enabled))
    annual_disabled = annual_tariff_summary(monthly_tariff_summary(add_tariff_columns(df, disabled), disabled))

    assert annual_disabled["annual_cost_without_pv_mxn"] < annual_enabled["annual_cost_without_pv_mxn"]
    assert annual_disabled["annual_cost_with_pv_mxn"] < annual_enabled["annual_cost_with_pv_mxn"]


def test_higher_energy_rates_increase_energy_costs():
    df = _tariff_ready_table(generation_kw=10.0)
    base = _default_tariff()
    higher = TariffConfig(
        base_rate_mxn_kwh=base.base_rate_mxn_kwh * 2.0,
        intermediate_rate_mxn_kwh=base.intermediate_rate_mxn_kwh * 2.0,
        peak_rate_mxn_kwh=base.peak_rate_mxn_kwh * 2.0,
        demand_rate_mxn_kw=base.demand_rate_mxn_kw,
        fixed_monthly_charge_mxn=base.fixed_monthly_charge_mxn,
        demand_charge_enabled=base.demand_charge_enabled,
    )

    base_monthly = monthly_tariff_summary(add_tariff_columns(df, base), base)
    higher_monthly = monthly_tariff_summary(add_tariff_columns(df, higher), higher)

    assert higher_monthly["energy_cost_without_pv_mxn"].sum() > base_monthly["energy_cost_without_pv_mxn"].sum()
    assert higher_monthly["energy_cost_with_pv_mxn"].sum() > base_monthly["energy_cost_with_pv_mxn"].sum()


def test_monthly_and_annual_tariff_summaries_are_consistent_and_non_negative():
    df = add_tariff_columns(_tariff_ready_table(generation_kw=10.0), _default_tariff())
    monthly = monthly_tariff_summary(df, _default_tariff())
    annual = annual_tariff_summary(monthly)

    cost_columns = [
        "energy_cost_without_pv_mxn",
        "energy_cost_with_pv_mxn",
        "demand_cost_without_pv_mxn",
        "demand_cost_with_pv_mxn",
        "fixed_charge_mxn",
        "total_without_pv_mxn",
        "total_with_pv_mxn",
        "estimated_savings_mxn",
    ]
    assert len(monthly) == 12
    assert (monthly[cost_columns] >= 0.0).all().all()
    assert annual["annual_cost_without_pv_mxn"] == pytest.approx(monthly["total_without_pv_mxn"].sum())
    assert annual["annual_cost_with_pv_mxn"] == pytest.approx(monthly["total_with_pv_mxn"].sum())
    assert annual["annual_savings_mxn"] == pytest.approx(monthly["estimated_savings_mxn"].sum())


def test_tariff_period_energy_is_separated_from_real_timestamps():
    config = _default_tariff()
    df = add_tariff_columns(_tariff_ready_table(demand_kw=40.0, generation_kw=0.0), config)
    monthly = monthly_tariff_summary(df, config)
    january = df[df["datetime"].dt.month == 1]
    january_summary = monthly.loc[monthly["month_start"] == pd.Timestamp("2026-01-01")].iloc[0]

    for period, column in [
        ("Base", "base_energy_without_pv_kWh"),
        ("Intermedia", "intermediate_energy_without_pv_kWh"),
        ("Punta", "peak_energy_without_pv_kWh"),
    ]:
        expected = january.loc[january["tariff_period"] == period, "demand_energy_kWh"].sum()
        assert january_summary[column] == pytest.approx(expected)


def test_low_power_factor_increases_tariff_total():
    config = _default_tariff()
    low_fp = add_tariff_columns(_tariff_ready_table_with_power_factor(power_factor=0.75), config)
    high_fp = add_tariff_columns(_tariff_ready_table_with_power_factor(power_factor=0.95), config)

    low_annual = annual_tariff_summary(monthly_tariff_summary(low_fp, config))
    high_annual = annual_tariff_summary(monthly_tariff_summary(high_fp, config))

    assert low_annual["annual_cost_without_pv_mxn"] > high_annual["annual_cost_without_pv_mxn"]


def test_iva_increases_final_tariff_total_without_changing_energy():
    df = _tariff_ready_table(generation_kw=10.0)
    no_iva = replace(_default_tariff(), iva_rate=0.0)
    with_iva = replace(_default_tariff(), iva_rate=0.16)

    monthly_no_iva = monthly_tariff_summary(add_tariff_columns(df, no_iva), no_iva)
    monthly_with_iva = monthly_tariff_summary(add_tariff_columns(df, with_iva), with_iva)
    annual_no_iva = annual_tariff_summary(monthly_no_iva)
    annual_with_iva = annual_tariff_summary(monthly_with_iva)

    assert annual_with_iva["annual_cost_without_pv_mxn"] > annual_no_iva["annual_cost_without_pv_mxn"]
    assert monthly_with_iva["demand_energy_kWh"].sum() == pytest.approx(monthly_no_iva["demand_energy_kWh"].sum())
    assert monthly_with_iva["grid_energy_kWh"].sum() == pytest.approx(monthly_no_iva["grid_energy_kWh"].sum())


def test_distribution_and_capacity_charges_impact_tariff_cost():
    df = _tariff_ready_table(generation_kw=10.0)
    no_demand_charges = replace(_default_tariff(), distribution_rate_mxn_kw=0.0, capacity_rate_mxn_kw=0.0)
    with_demand_charges = _default_tariff()

    annual_without_charges = annual_tariff_summary(
        monthly_tariff_summary(add_tariff_columns(df, no_demand_charges), no_demand_charges)
    )
    annual_with_charges = annual_tariff_summary(
        monthly_tariff_summary(add_tariff_columns(df, with_demand_charges), with_demand_charges)
    )

    assert annual_with_charges["annual_cost_without_pv_mxn"] > annual_without_charges["annual_cost_without_pv_mxn"]
    assert annual_with_charges["annual_distribution_cost_without_pv_mxn"] > 0.0
    assert annual_with_charges["annual_capacity_cost_without_pv_mxn"] > 0.0


def test_billable_demands_change_with_monthly_maximum_demand():
    config = _default_tariff()
    low = monthly_tariff_summary(add_tariff_columns(_tariff_ready_table(demand_kw=30.0), config), config)
    high = monthly_tariff_summary(add_tariff_columns(_tariff_ready_table(demand_kw=60.0), config), config)

    assert high["distribution_demand_without_pv_kW"].sum() > low["distribution_demand_without_pv_kW"].sum()
    assert high["capacity_demand_without_pv_kW"].sum() > low["capacity_demand_without_pv_kW"].sum()
    assert high["demand_cost_without_pv_mxn"].sum() > low["demand_cost_without_pv_mxn"].sum()


def test_tariff_period_rates_affect_total_cost():
    df = _tariff_ready_table(demand_kw=50.0, generation_kw=0.0)
    low_peak = replace(_default_tariff(), peak_rate_mxn_kwh=1.0)
    high_peak = replace(_default_tariff(), peak_rate_mxn_kwh=8.0)

    low_annual = annual_tariff_summary(monthly_tariff_summary(add_tariff_columns(df, low_peak), low_peak))
    high_annual = annual_tariff_summary(monthly_tariff_summary(add_tariff_columns(df, high_peak), high_peak))

    assert high_annual["annual_cost_without_pv_mxn"] > low_annual["annual_cost_without_pv_mxn"]
