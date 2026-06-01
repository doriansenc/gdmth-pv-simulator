from dataclasses import replace
from io import StringIO

import numpy as np
import pandas as pd
import pytest

from src.demand_engine import (
    DemandConfig,
    add_real_demand_to_simulation,
    add_synthetic_industrial_demand,
    read_uploaded_demand,
)
from src.irradiance_data import standardize_irradiance_table, to_15min_irradiance
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
