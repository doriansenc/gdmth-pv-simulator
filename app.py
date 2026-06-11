from __future__ import annotations

import hashlib
import html
import os
import textwrap
import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from src.demand_engine import (
    DemandConfig,
    add_real_demand_to_simulation,
    add_synthetic_industrial_demand,
    read_uploaded_demand,
)
from src.exporting import build_excel_export, build_pdf_report
from src.express_savings import compute_express_savings
from src.backup_engine import calculate_bess_backup, interpret_cycle_life
from src.profitability_engine import calculate_profitability, percent_to_fraction
from src.receipt_savings import compute_receipt_based_savings, suggest_industrial_tariff_family
from src.irradiance_data import (
    annual_coverage_report,
    fetch_nsrdb_psm3,
    fetch_pvgis_hourly,
    prepare_nasa_power_irradiance,
    prepare_nasa_power_provisional_irradiance,
    read_uploaded_irradiance,
    to_15min_irradiance,
)
from src.plotting import (
    plot_daily_generation_vs_demand,
    plot_daily_ghi_dni_dhi,
    plot_hourly_average,
    plot_monthly_energy,
    plot_monthly_energy_balance,
    plot_monthly_tariff_savings,
    plot_net_energy_flow,
    plot_poa_components,
    plot_profitability_cumulative_chart,
    plot_receipt_period_savings,
    plot_scenario_coverage,
    plot_scenario_generation,
    plot_tariff_component_breakdown,
    plot_tariff_energy_by_period,
)
from src.scenario_engine import compare_scenarios, parse_number_list
from src.solar_engine import PVSystemConfig, simulate_pv_system, validate_pv_system_config
from src.summary import compute_summary, summary_table
from src.tariff_engine import TariffConfig, add_tariff_columns, annual_tariff_summary, monthly_tariff_summary
from src.ui_components import app_header, info_panel, load_css, metric_card, section_header


GOOGLE_MAP_PICKER = components.declare_component(
    "google_map_picker",
    path=str(Path(__file__).resolve().parent / "components" / "google_map_picker"),
)


st.set_page_config(
    page_title="FVoltData",
    layout="wide",
    initial_sidebar_state="collapsed",
)

load_css()


def get_google_maps_api_key() -> str:
    """Return the Google Maps API key from environment or Streamlit secrets."""
    env_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if env_key:
        return env_key

    try:
        return str(st.secrets.get("GOOGLE_MAPS_API_KEY", "")).strip()
    except Exception:
        return ""


PRIMARY_IRRADIANCE_SOURCES = [
    "Cielo despejado con pvlib Ineichen",
    "Escenario climático simple",
    "CSV propio",
]

ADVANCED_IRRADIANCE_SOURCES = [
    "PVGIS con pvlib.iotools",
    "NASA POWER",
    "NSRDB PSM3 con pvlib.iotools",
]

IRRADIANCE_SOURCES = PRIMARY_IRRADIANCE_SOURCES + ADVANCED_IRRADIANCE_SOURCES

ADVANCED_IRRADIANCE_LABELS = {
    "PVGIS con pvlib.iotools": "PVGIS avanzado: requiere cargar datos externos",
    "NASA POWER": "NASA POWER avanzado: requiere cargar datos externos",
    "NSRDB PSM3 con pvlib.iotools": "NSRDB avanzado: requiere API key/correo y cargar datos externos",
}

IRRADIANCE_SOURCE_GROUPS = [
    "Fuente principal del MVP",
    "Fuente solar externa avanzada",
]

IRRADIANCE_SOURCE_GROUP_BY_SOURCE = {
    **{source: "Fuente principal del MVP" for source in PRIMARY_IRRADIANCE_SOURCES},
    **{source: "Fuente solar externa avanzada" for source in ADVANCED_IRRADIANCE_SOURCES},
}

DEFAULT_IRRADIANCE_SOURCE = "Cielo despejado con pvlib Ineichen"

EXTERNAL_IRRADIANCE_SOURCES = set(ADVANCED_IRRADIANCE_SOURCES)

CLIMATE_FACTORS = {
    "Despejado": 1.00,
    "Parcialmente nublado": 0.75,
    "Nublado": 0.45,
    "Lluvia o muy cubierto": 0.25,
    "Personalizado": None,
}

DEFAULT_TIMEZONE = "America/Monterrey"
NASA_POWER_MIN_YEAR = 2001
DEFAULT_NASA_POWER_YEAR = max(2018, pd.Timestamp.utcnow().year - 1)
NASA_POWER_MODE_RECOMMENDED = "Último año completo disponible"
NASA_POWER_MODE_PROVISIONAL = "Año actual provisional"
NASA_POWER_MODE_CUSTOM = "Año histórico personalizado"
NASA_POWER_MODES = [
    NASA_POWER_MODE_RECOMMENDED,
    NASA_POWER_MODE_PROVISIONAL,
    NASA_POWER_MODE_CUSTOM,
]
NASA_POWER_MODE_ALIASES = {
    "Año completo recomendado": NASA_POWER_MODE_RECOMMENDED,
    "Año seleccionado provisional": NASA_POWER_MODE_PROVISIONAL,
}
REALISM_LOSS_SCENARIOS = {
    "Optimista": {
        "losses": 0.12,
        "description": "Sistema limpio, buena instalación y pocas pérdidas adicionales.",
    },
    "Recomendado": {
        "losses": 0.20,
        "description": "Escenario realista con suciedad moderada, pérdidas eléctricas, temperatura, variabilidad operativa y condiciones no ideales.",
    },
    "Conservador": {
        "losses": 0.30,
        "description": "Escenario precautorio para polvo, mantenimiento irregular, orientación no ideal, sombreado parcial o pérdidas operativas mayores.",
    },
}
TIMEZONE_OPTIONS = [
    "America/Monterrey",
    "America/Mexico_City",
    "America/Tijuana",
    "Etc/GMT+6",
]

DEFAULT_STATE = {
    "latitude": 25.6866,
    "longitude": -100.3161,
    "altitude_m": 540.0,
    "location_search_query": "Monterrey, Nuevo Leon, Mexico",
    "selected_location_label": "Monterrey, Nuevo Leon, Mexico",
    "location_version": 0,
    "last_map_event_id": "",
    "auto_altitude": True,
    "auto_timezone": True,
    "timezone_update_requested": False,
    "dynamic_timezone_options": [],
    "timezone_status_message": "",
    "timezone_status_level": "info",
    "stage1_step": "ubicacion",
    "stage1_fv_user_modified": False,
    "stage1_fv_recommendation_applied": False,
    "stage1_orientation_user_modified": False,
    "stage1_orientation_recommendation_applied": False,
    "stage1_pv_defaults_migration_checked": True,
    "stage2_step": "consumo",
    "year": 2026,
    "panel_power_w": 550.0,
    "panel_area_m2": 2.5,
    "panel_efficiency_percent": 22.0,
    "number_of_panels": 1,
    "tilt_deg": 25,
    "azimuth_deg": 180,
    "albedo": 0.20,
    "system_losses_percent": 12.0,
    "max_demand_kw": 50.0,
    "demand_mode": "Demanda sintética",
    "plant_factor": 0.60,
    "power_factor": 0.90,
    "random_seed": 42,
    "weekend_reduction": 0.35,
    "summer_increase": 0.10,
    "irradiance_source": DEFAULT_IRRADIANCE_SOURCE,
    "irradiance_source_group": "Fuente principal del MVP",
    "climate_condition": "Parcialmente nublado",
    "custom_weather_factor": 0.70,
    "pvgis_database": "Automático",
    "nsrdb_interval": 30,
    "nsrdb_api_key": os.getenv("NSRDB_API_KEY", ""),
    "nsrdb_email": os.getenv("NSRDB_EMAIL", ""),
    "external_irradiance_df": None,
    "external_irradiance_signature": None,
    "external_irradiance_label": "",
    "external_irradiance_status": "",
    "external_irradiance_error_detail": "",
    "external_irradiance_diagnostics": {},
    "active_irradiance_source": "",
    "selected_irradiance_source": DEFAULT_IRRADIANCE_SOURCE,
    "nasa_requested_year": DEFAULT_NASA_POWER_YEAR,
    "nasa_base_year": DEFAULT_NASA_POWER_YEAR,
    "selected_nasa_power_mode": NASA_POWER_MODE_RECOMMENDED,
    "selected_nasa_power_year": DEFAULT_NASA_POWER_YEAR,
    "selected_nasa_climate_year": DEFAULT_NASA_POWER_YEAR,
    "selected_nasa_base_year": DEFAULT_NASA_POWER_YEAR,
    "weather_source_signature": None,
    "stage1_simulation_signature": None,
    "stage1_results_signature": None,
    "load_external_irradiance_requested": False,
    # Legacy compatibility fields; durable NASA state lives in selected_nasa_*.
    "nasa_power_mode": NASA_POWER_MODE_RECOMMENDED,
    "nasa_power_year": DEFAULT_NASA_POWER_YEAR,
    "timezone": DEFAULT_TIMEZONE,
    "transposition_model": "haydavies",
    "base_rate_mxn_kwh": 1.15,
    "intermediate_rate_mxn_kwh": 1.85,
    "peak_rate_mxn_kwh": 2.95,
    # Legacy compatibility field. The current GDMTH estimate uses distribution
    # and capacity charges instead of this older single demand-rate input.
    "demand_rate_mxn_kw": 280.0,
    "distribution_rate_mxn_kw": 57.74,
    "capacity_rate_mxn_kw": 398.22,
    "fixed_monthly_charge_mxn": 850.0,
    "iva_rate_percent": 16.0,
    "demand_charge_enabled": True,
    "stage2_monthly_consumption_kwh": 1000.0,
    "stage2_annual_consumption_kwh": 12000.0,
    "stage2_consumption_input_mode": "Mensual",
    "stage2_express_enabled": False,
    "stage2_avg_kwh_cost_mxn": 2.50,
    "stage2_advanced_billing_mode": "Sin análisis formal",
    "stage2_receipt_service_type": "Industrial",
    "stage2_receipt_period_frequency": "Mensual",
    "stage2_receipt_contracted_demand_kw": 50.0,
    "stage2_receipt_tariff_label": "",
    "stage2_receipt_confirmed_tariff": "GDMTO",
    "stage2_receipt_residential_tariff": "1A",
    "stage2_receipt_periods_df": None,
    "stage2_receipt_periods_initialized": False,
    "stage3_step": "carga",
    "stage3_load_value": 10.0,
    "stage3_load_unit": "kW",
    "stage3_power_factor": 0.90,
    "stage3_backup_hours": 4.0,
    "stage3_outage_frequency": 2.0,
    "stage3_outage_frequency_unit": "Por mes",
    "stage3_average_outage_duration_h": 2.0,
    "stage3_typical_max_outage_duration_h": 6.0,
    "stage3_battery_technology": "LiFePO4",
    "stage3_battery_capacity_kwh": 5.0,
    "stage3_battery_max_power_kw": 5.0,
    "stage3_depth_of_discharge": 0.80,
    "stage3_system_efficiency": 0.90,
    "stage3_safety_margin": 0.15,
    "stage3_life_cycles": 4500.0,
    "stage3_result_critical_load_kw": 0.0,
    "stage3_result_backup_hours": 0.0,
    "stage3_result_required_usable_kwh": 0.0,
    "stage3_result_required_nominal_kwh": 0.0,
    "stage3_result_required_bess_capacity_kwh": 0.0,
    "stage3_result_installed_backup_hours": 0.0,
    "stage3_result_annual_outage_events": 0.0,
    "stage3_result_annual_outage_hours": 0.0,
    "stage3_result_annual_backed_hours": 0.0,
    "stage3_result_annual_backed_energy_kwh": 0.0,
    "stage3_result_uncovered_average_outage_hours": 0.0,
    "stage3_result_annual_uncovered_hours": 0.0,
    "stage3_result_equivalent_cycles_per_year": 0.0,
    "stage3_result_estimated_life_years_by_cycles": None,
    "stage3_result_long_outage_uncovered_hours": 0.0,
    "stage3_result_long_outage_covered": False,
    "stage3_result_recommended_battery_count": 0.0,
    "stage3_result_recommended_batteries": 0.0,
    "stage3_result_total_installed_capacity_kwh": 0.0,
    "stage3_result_usable_installed_energy_kwh": 0.0,
    "stage3_result_is_complete": False,
    "stage4_step": "inaccion",
    "stage4_annual_outage_events": 0.0,
    "stage4_annual_outage_hours": 0.0,
    "stage4_outage_cost_per_hour_mxn": 10000.0,
    "stage4_fixed_cost_per_outage_mxn": 0.0,
    "stage4_annual_repairs_or_damage_cost_mxn": 0.0,
    "stage4_avoidable_loss_fraction": 0.90,
    "stage4_recommended_batteries": 0.0,
    "stage4_battery_unit_cost_mxn": 25000.0,
    "stage4_balance_of_system_mode": "Porcentaje",
    "stage4_balance_of_system_percentage": 0.20,
    "stage4_balance_of_system_manual_cost_mxn": 0.0,
    "stage4_include_pv_investment": False,
    "stage4_pv_investment_cost_mxn": 0.0,
    "stage4_include_energy_savings": False,
    "stage4_annual_energy_savings_mxn": 0.0,
    "stage4_result_annual_inaction_cost": 0.0,
    "stage4_result_avoidable_losses": 0.0,
    "stage4_result_total_investment": 0.0,
    "stage4_result_annual_total_benefit": 0.0,
    "stage4_result_simple_payback_years": None,
    "stage4_result_simple_roi_pct": None,
    "stage4_result_is_complete": False,
}


STAGE1_CONFIG_STATE_KEYS = (
    "number_of_panels",
    "panel_power_w",
    "panel_area_m2",
    "panel_efficiency_percent",
    "system_losses_percent",
    "tilt_deg",
    "azimuth_deg",
    "albedo",
    "transposition_model",
    "poa_model",
)


def preserve_stage1_config_state() -> None:
    """Keep conditional Stage 1 widget values durable across wizard steps."""
    for key in STAGE1_CONFIG_STATE_KEYS:
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


for key, value in DEFAULT_STATE.items():
    st.session_state.setdefault(key, value)
preserve_stage1_config_state()


def apply_commercial_pv_defaults_if_placeholder() -> None:
    """Mark legacy PV defaults as checked without changing current user inputs."""
    st.session_state.stage1_pv_defaults_migration_checked = True


def initialize_nasa_power_year() -> None:
    """Keep NASA POWER on the latest complete data year by default."""
    try:
        current_year = int(st.session_state.get("selected_nasa_power_year", st.session_state.get("nasa_power_year", DEFAULT_NASA_POWER_YEAR)))
    except (TypeError, ValueError):
        current_year = DEFAULT_NASA_POWER_YEAR

    if current_year <= NASA_POWER_MIN_YEAR or current_year > DEFAULT_NASA_POWER_YEAR:
        current_year = DEFAULT_NASA_POWER_YEAR
    st.session_state.selected_nasa_power_year = current_year
    st.session_state.selected_nasa_climate_year = current_year
    st.session_state.selected_nasa_base_year = int(st.session_state.get("selected_nasa_base_year", DEFAULT_NASA_POWER_YEAR) or DEFAULT_NASA_POWER_YEAR)
    if not st.session_state.get("selected_nasa_power_mode"):
        st.session_state.selected_nasa_power_mode = NASA_POWER_MODE_RECOMMENDED
    st.session_state.nasa_power_year = current_year
    st.session_state.nasa_power_mode = st.session_state.selected_nasa_power_mode
    st.session_state.nasa_power_year_initialized = True


initialize_nasa_power_year()


def normalize_nasa_power_mode(mode: str | None) -> str:
    clean_mode = str(mode or NASA_POWER_MODE_RECOMMENDED)
    clean_mode = NASA_POWER_MODE_ALIASES.get(clean_mode, clean_mode)
    return clean_mode if clean_mode in NASA_POWER_MODES else NASA_POWER_MODE_RECOMMENDED


def effective_nasa_power_year(
    nasa_power_mode: str,
    simulation_year: int,
    custom_year: int | None = None,
) -> int:
    nasa_power_mode = normalize_nasa_power_mode(nasa_power_mode)
    if nasa_power_mode == NASA_POWER_MODE_PROVISIONAL:
        return int(simulation_year)
    if nasa_power_mode == NASA_POWER_MODE_CUSTOM:
        return int(custom_year or DEFAULT_NASA_POWER_YEAR)
    return DEFAULT_NASA_POWER_YEAR


def selected_nasa_power_mode() -> str:
    """Return durable NASA mode; never read conditional widget keys here."""
    mode = normalize_nasa_power_mode(
        st.session_state.get("selected_nasa_power_mode", st.session_state.get("nasa_power_mode", NASA_POWER_MODE_RECOMMENDED))
    )
    st.session_state.selected_nasa_power_mode = mode
    st.session_state.nasa_power_mode = mode
    return mode


def selected_nasa_power_year() -> int:
    """Return durable custom NASA climate year, clamped to complete historical years."""
    try:
        year = int(st.session_state.get("selected_nasa_power_year", st.session_state.get("nasa_power_year", DEFAULT_NASA_POWER_YEAR)))
    except (TypeError, ValueError):
        year = DEFAULT_NASA_POWER_YEAR
    if year < NASA_POWER_MIN_YEAR or year > DEFAULT_NASA_POWER_YEAR:
        year = DEFAULT_NASA_POWER_YEAR
    st.session_state.selected_nasa_power_year = year
    st.session_state.selected_nasa_climate_year = year
    st.session_state.nasa_power_year = year
    return year


def selected_nasa_base_year() -> int:
    try:
        year = int(st.session_state.get("selected_nasa_base_year", DEFAULT_NASA_POWER_YEAR))
    except (TypeError, ValueError):
        year = DEFAULT_NASA_POWER_YEAR
    if year < NASA_POWER_MIN_YEAR or year > DEFAULT_NASA_POWER_YEAR:
        year = DEFAULT_NASA_POWER_YEAR
    st.session_state.selected_nasa_base_year = year
    st.session_state.nasa_base_year = year
    return year


def sync_nasa_power_mode_widget() -> None:
    mode = normalize_nasa_power_mode(st.session_state.get("_nasa_power_mode_widget", selected_nasa_power_mode()))
    st.session_state.selected_nasa_power_mode = mode
    st.session_state.nasa_power_mode = mode


def sync_nasa_power_year_widget() -> None:
    try:
        year = int(st.session_state.get("_nasa_power_year_widget", selected_nasa_power_year()))
    except (TypeError, ValueError):
        year = DEFAULT_NASA_POWER_YEAR
    if year < NASA_POWER_MIN_YEAR or year > DEFAULT_NASA_POWER_YEAR:
        year = DEFAULT_NASA_POWER_YEAR
    st.session_state.selected_nasa_power_year = year
    st.session_state.selected_nasa_climate_year = year
    st.session_state.nasa_power_year = year


def prepare_nasa_power_widget_state() -> None:
    """Seed conditional widget keys from durable NASA state before rendering widgets."""
    st.session_state["_nasa_power_mode_widget"] = selected_nasa_power_mode()
    st.session_state["_nasa_power_year_widget"] = selected_nasa_power_year()


def apply_commercial_panel_defaults() -> None:
    """Legacy no-op: recommendations must never overwrite manual PV values."""
    st.session_state.stage1_fv_recommendation_applied = False


def apply_recommended_orientation() -> None:
    """Legacy no-op: orientation recommendations are informational only."""
    st.session_state.stage1_orientation_recommendation_applied = False


def mark_stage1_fv_user_modified() -> None:
    st.session_state.stage1_fv_user_modified = True
    st.session_state.stage1_fv_recommendation_applied = False


def mark_stage1_orientation_user_modified() -> None:
    st.session_state.stage1_orientation_user_modified = True
    st.session_state.stage1_orientation_recommendation_applied = False


def format_coordinate_label(latitude: float, longitude: float) -> str:
    return f"{float(latitude):.6f}, {float(longitude):.6f}"


def is_valid_timezone_id(timezone_id: str) -> bool:
    """Return True when timezone_id is a valid IANA timezone name."""
    if not timezone_id or not isinstance(timezone_id, str):
        return False
    try:
        ZoneInfo(timezone_id.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def normalize_timezone_options(
    selected_timezone: str | None,
    extra_timezones: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, list[str]]:
    """Return a valid selected timezone and selectbox options including dynamic Google results."""
    options = list(TIMEZONE_OPTIONS)
    for timezone_id in extra_timezones or []:
        clean_timezone = str(timezone_id).strip()
        if is_valid_timezone_id(clean_timezone) and clean_timezone not in options:
            options.append(clean_timezone)

    clean_selected = str(selected_timezone or "").strip()
    if is_valid_timezone_id(clean_selected) and clean_selected not in options:
        options.append(clean_selected)

    if clean_selected not in options:
        clean_selected = DEFAULT_TIMEZONE
    return clean_selected, options


def get_timezone_select_options() -> list[str]:
    selected_timezone, options = normalize_timezone_options(
        str(st.session_state.get("timezone", DEFAULT_TIMEZONE)),
        tuple(st.session_state.get("dynamic_timezone_options", [])),
    )
    st.session_state.timezone = selected_timezone
    st.session_state.dynamic_timezone_options = [timezone_id for timezone_id in options if timezone_id not in TIMEZONE_OPTIONS]
    return options


@st.cache_data(show_spinner=False, ttl=24 * 60 * 60)
def _fetch_google_timezone_cached(
    latitude: float,
    longitude: float,
    timestamp: int,
    _api_key: str,
) -> str | None:
    response = requests.get(
        "https://maps.googleapis.com/maps/api/timezone/json",
        params={
            "location": f"{latitude:.6f},{longitude:.6f}",
            "timestamp": int(timestamp),
            "key": _api_key,
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "OK":
        return None
    timezone_id = str(payload.get("timeZoneId", "")).strip()
    return timezone_id if is_valid_timezone_id(timezone_id) else None


def fetch_google_timezone(latitude: float, longitude: float, api_key: str) -> str | None:
    """Fetch the IANA timezone id for a location using Google Time Zone API."""
    if not api_key:
        return None
    try:
        rounded_latitude = round(float(latitude), 4)
        rounded_longitude = round(float(longitude), 4)
        current_day_timestamp = int(time.time() // 86400 * 86400)
        return _fetch_google_timezone_cached(
            rounded_latitude,
            rounded_longitude,
            current_day_timestamp,
            _api_key=api_key,
        )
    except Exception:
        return None


def request_auto_timezone_update() -> None:
    st.session_state.timezone_update_requested = True


def handle_auto_timezone_toggle() -> None:
    """Clear stale timezone status when automatic updates are disabled."""
    if not bool(st.session_state.get("auto_timezone", True)):
        st.session_state.timezone_update_requested = False
        st.session_state.timezone_status_message = ""
        st.session_state.timezone_status_level = "info"


def apply_auto_timezone_update() -> None:
    """Update timezone after a location change while preserving manual fallback."""
    if not bool(st.session_state.get("timezone_update_requested", False)):
        return

    st.session_state.timezone_update_requested = False
    if not bool(st.session_state.get("auto_timezone", True)):
        return

    api_key = get_google_maps_api_key()
    timezone_id = fetch_google_timezone(
        float(st.session_state.latitude),
        float(st.session_state.longitude),
        api_key,
    )
    if timezone_id:
        selected_timezone, options = normalize_timezone_options(
            timezone_id,
            tuple(st.session_state.get("dynamic_timezone_options", [])),
        )
        st.session_state.timezone = selected_timezone
        st.session_state.dynamic_timezone_options = [option for option in options if option not in TIMEZONE_OPTIONS]
        st.session_state.timezone_status_message = f"Zona horaria actualizada automáticamente: {selected_timezone}"
        st.session_state.timezone_status_level = "success"
        return

    st.session_state.timezone_status_message = (
        "No se pudo actualizar automáticamente la zona horaria; se conserva la selección manual."
    )
    st.session_state.timezone_status_level = "warning"


def _clear_pending_location_update() -> None:
    for key in (
        "pending_latitude",
        "pending_longitude",
        "pending_altitude_m",
        "pending_location_label",
        "pending_map_event_id",
    ):
        st.session_state.pop(key, None)


def _increment_location_version() -> None:
    st.session_state.location_version = int(st.session_state.get("location_version", 0)) + 1


def register_manual_location_change(update_label: bool = True) -> None:
    _clear_pending_location_update()
    _increment_location_version()
    if update_label:
        label = format_coordinate_label(st.session_state.latitude, st.session_state.longitude)
        st.session_state.selected_location_label = label
        st.session_state.location_search_query = label
        st.session_state.location_search_results = []
        request_auto_timezone_update()


def is_fresh_map_location_event(map_result: dict, current_location_version: int, last_event_id: str) -> bool:
    event_id = str(map_result.get("event_id") or "").strip()
    if not event_id:
        return False

    try:
        event_location_version = int(map_result.get("location_version"))
    except (TypeError, ValueError):
        return False

    return event_location_version == int(current_location_version) and event_id != str(last_event_id or "")


def build_weather_source_signature(
    source: str,
    latitude: float,
    longitude: float,
    year: int | None = None,
    timezone: str | None = None,
    pvgis_database: str | None = None,
    nsrdb_interval: int | None = None,
    nasa_power_year: int | None = None,
    nasa_power_mode: str | None = None,
    nasa_base_year: int | None = None,
    csv_identifier: str | None = None,
    simulation_year: int | None = None,
    final_weather_year: int | None = None,
    **_ignored_non_weather_fields,
) -> tuple:
    """Signature for downloaded weather data only, not for PV system settings.

    This intentionally excludes panel count, module power, area, efficiency,
    losses, tilt, azimuth, albedo, demand and tariff inputs. Those parameters
    should recalculate results with the same weather table instead of invalidating
    NASA POWER/PVGIS/NSRDB data.
    """
    resolved_year = int(simulation_year if simulation_year is not None else year)
    signature: tuple = (
        str(source),
        round(float(latitude), 5),
        round(float(longitude), 5),
        resolved_year,
        str(timezone),
    )
    if source == "PVGIS con pvlib.iotools":
        return signature + (str(pvgis_database or "Automático"),)
    if source == "NASA POWER":
        mode = normalize_nasa_power_mode(nasa_power_mode)
        effective_year = effective_nasa_power_year(mode, resolved_year, nasa_power_year)
        return signature + (
            mode,
            int(effective_year),
            int(nasa_base_year or DEFAULT_NASA_POWER_YEAR),
            int(final_weather_year or resolved_year),
        )
    if source == "NSRDB PSM3 con pvlib.iotools":
        return signature + (int(nsrdb_interval or 30),)
    if source == "CSV propio":
        return signature + (str(csv_identifier or ""),)
    return signature


def weather_source_signature(*args, **kwargs) -> tuple:
    """Backward-compatible alias for the canonical weather-source signature."""
    return build_weather_source_signature(*args, **kwargs)


def external_irradiance_signature(*args, **kwargs) -> tuple:
    """Backward-compatible alias for the weather-source signature."""
    return build_weather_source_signature(*args, **kwargs)


def current_weather_source_signature(
    source: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    year: int | None = None,
    timezone: str | None = None,
    pvgis_database: str | None = None,
    nsrdb_interval: int | None = None,
    nasa_power_year: int | None = None,
    nasa_power_mode: str | None = None,
) -> tuple:
    selected_source = str(source or st.session_state.irradiance_source)
    return build_weather_source_signature(
        source=selected_source,
        latitude=float(latitude if latitude is not None else st.session_state.latitude),
        longitude=float(longitude if longitude is not None else st.session_state.longitude),
        year=int(year if year is not None else st.session_state.year),
        timezone=str(timezone if timezone is not None else st.session_state.timezone),
        pvgis_database=str(pvgis_database if pvgis_database is not None else st.session_state.get("pvgis_database", "Automático")),
        nsrdb_interval=int(nsrdb_interval if nsrdb_interval is not None else st.session_state.get("nsrdb_interval", 30)),
        nasa_power_year=int(nasa_power_year if nasa_power_year is not None else selected_nasa_power_year()),
        nasa_power_mode=normalize_nasa_power_mode(nasa_power_mode or selected_nasa_power_mode()),
        nasa_base_year=selected_nasa_base_year(),
        csv_identifier=str(st.session_state.get("uploaded_irradiance_file_id", "")),
    )


def current_external_irradiance_signature(pv_config: PVSystemConfig) -> tuple:
    return current_weather_source_signature(
        source=str(st.session_state.irradiance_source),
        latitude=pv_config.latitude,
        longitude=pv_config.longitude,
        year=pv_config.year,
        timezone=pv_config.timezone,
        pvgis_database=str(st.session_state.get("pvgis_database", "Automático")),
    )


def _normalize_external_signature(signature: tuple | None) -> tuple | None:
    if signature is None:
        return None
    normalized = list(tuple(signature))
    if len(normalized) >= 3:
        try:
            normalized[1] = round(float(normalized[1]), 5)
            normalized[2] = round(float(normalized[2]), 5)
        except (TypeError, ValueError):
            return tuple(normalized)

    if normalized and normalized[0] in {"NASA POWER", "NASA POWER provisional"}:
        normalized[0] = "NASA POWER"
        if len(normalized) == 6 and isinstance(normalized[5], (int, float)):
            climate_year = int(normalized[5])
            normalized = normalized[:5] + [
                NASA_POWER_MODE_RECOMMENDED,
                climate_year,
                DEFAULT_NASA_POWER_YEAR,
                int(normalized[3]),
            ]
        elif len(normalized) == 7:
            normalized.append(DEFAULT_NASA_POWER_YEAR)
            normalized.append(int(normalized[3]))
        elif len(normalized) == 8:
            normalized.append(int(normalized[3]))
        if len(normalized) >= 6:
            normalized[5] = normalize_nasa_power_mode(normalized[5])
    return tuple(normalized)


def external_irradiance_signature_matches(loaded_signature: tuple | None, current_signature: tuple) -> bool:
    return _normalize_external_signature(loaded_signature) == _normalize_external_signature(current_signature)


def validate_final_weather_dataframe(df: pd.DataFrame, simulation_year: int) -> dict:
    """Validate the final weather table used by the simulation, after any remapping/completion."""
    report = annual_coverage_report(df, int(simulation_year))
    years_present: list[int] = []
    if isinstance(df, pd.DataFrame) and not df.empty and "datetime" in df.columns:
        timestamps = pd.to_datetime(df["datetime"], errors="coerce").dropna()
        if not timestamps.empty:
            years_present = sorted(int(year) for year in timestamps.dt.year.dropna().unique())
    if years_present and years_present != [int(simulation_year)]:
        raise ValueError(
            "NASA POWER final table year mismatch. "
            f"Expected {int(simulation_year)}, found {years_present}."
        )
    if float(report["coverage_fraction"]) < 0.95:
        raise ValueError(
            "NASA POWER final table coverage insufficient. "
            f"Covered {report['covered_days']} of {report['days_in_year']} days "
            f"({100 * float(report['coverage_fraction']):.1f}%)."
        )
    return report


def log_weather_signature_mismatch(
    selected_source: str,
    current_signature: tuple,
    loaded_signature: tuple | None,
    loaded_data: object,
) -> None:
    """Print safe development diagnostics for weather-signature mismatches."""
    simulation_year = int(st.session_state.get("year", DEFAULT_NASA_POWER_YEAR))
    report = annual_coverage_report(loaded_data, simulation_year) if isinstance(loaded_data, pd.DataFrame) else {}
    years_present: list[int] = []
    if isinstance(loaded_data, pd.DataFrame) and not loaded_data.empty and "datetime" in loaded_data.columns:
        timestamps = pd.to_datetime(loaded_data["datetime"], errors="coerce").dropna()
        if not timestamps.empty:
            years_present = sorted(int(year) for year in timestamps.dt.year.dropna().unique())
    print("[weather-signature-mismatch] selected_source:", selected_source)
    print("[weather-signature-mismatch] active_source:", st.session_state.get("external_irradiance_label", ""))
    print("[weather-signature-mismatch] simulation_year:", simulation_year)
    print("[weather-signature-mismatch] nasa_mode:", selected_nasa_power_mode())
    print("[weather-signature-mismatch] nasa_climate_year:", selected_nasa_power_year())
    print("[weather-signature-mismatch] nasa_base_year:", selected_nasa_base_year())
    print("[weather-signature-mismatch] saved_weather_signature:", _normalize_external_signature(loaded_signature))
    print("[weather-signature-mismatch] current_weather_signature:", _normalize_external_signature(current_signature))
    print("[weather-signature-mismatch] final_df_first_timestamp:", report.get("first_timestamp", ""))
    print("[weather-signature-mismatch] final_df_last_timestamp:", report.get("last_timestamp", ""))
    print("[weather-signature-mismatch] final_df_years_present:", years_present)
    print("[weather-signature-mismatch] final_df_rows:", report.get("rows", 0))
    print("[weather-signature-mismatch] final_df_covered_days:", report.get("covered_days", 0))


def apply_pending_location_update() -> None:
    """Apply map-click updates before latitude/longitude widgets are created.

    Streamlit does not allow changing st.session_state values that are already
    bound to instantiated widgets during the same script run. The map tab stores
    clicked coordinates in temporary keys and this function applies them at the
    beginning of the next rerun, before the sidebar widgets are rendered.
    """
    if "pending_latitude" not in st.session_state or "pending_longitude" not in st.session_state:
        return

    st.session_state.latitude = float(st.session_state.pop("pending_latitude"))
    st.session_state.longitude = float(st.session_state.pop("pending_longitude"))
    if "pending_altitude_m" in st.session_state:
        st.session_state.altitude_m = float(st.session_state.pop("pending_altitude_m"))
    if "pending_location_label" in st.session_state:
        label = str(st.session_state.pop("pending_location_label"))
        st.session_state.selected_location_label = label
        st.session_state.location_search_query = label
        st.session_state.location_search_results = []
    if "pending_map_event_id" in st.session_state:
        st.session_state.last_map_event_id = str(st.session_state.pop("pending_map_event_id"))
    _increment_location_version()
    request_auto_timezone_update()


@st.cache_data(show_spinner=False)
def load_nasa_irradiance(
    latitude: float,
    longitude: float,
    simulation_year: int,
    nasa_data_year: int,
    timezone: str,
    nasa_power_mode: str,
    nasa_base_year: int,
) -> pd.DataFrame:
    nasa_power_mode = normalize_nasa_power_mode(nasa_power_mode)
    if nasa_power_mode == NASA_POWER_MODE_PROVISIONAL:
        return prepare_nasa_power_provisional_irradiance(
            latitude=latitude,
            longitude=longitude,
            simulation_year=simulation_year,
            selected_data_year=simulation_year,
            base_year=int(nasa_base_year),
            timezone=timezone,
        )

    reference_year = DEFAULT_NASA_POWER_YEAR if nasa_power_mode == NASA_POWER_MODE_RECOMMENDED else nasa_data_year
    return prepare_nasa_power_irradiance(
        latitude=latitude,
        longitude=longitude,
        simulation_year=simulation_year,
        nasa_data_year=reference_year,
        timezone=timezone,
    )


@st.cache_data(show_spinner=False)
def load_pvgis_irradiance(latitude: float, longitude: float, year: int, database: str, timezone: str) -> pd.DataFrame:
    hourly = fetch_pvgis_hourly(latitude=latitude, longitude=longitude, year=year, raddatabase=database)
    return to_15min_irradiance(hourly, year=year, timezone=timezone)


@st.cache_data(show_spinner=False)
def load_nsrdb_irradiance(
    latitude: float,
    longitude: float,
    year: int,
    api_key: str,
    email: str,
    interval: int,
    timezone: str,
) -> pd.DataFrame:
    data = fetch_nsrdb_psm3(
        latitude=latitude,
        longitude=longitude,
        year=year,
        api_key=api_key,
        email=email,
        interval=interval,
    )
    return to_15min_irradiance(data, year=year, timezone=timezone)


@st.cache_data(show_spinner=False)
def run_simulation(
    pv_config: PVSystemConfig,
    demand_config: DemandConfig,
    irradiance_df: pd.DataFrame | None,
    irradiance_label: str,
    demand_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    pv_data = simulate_pv_system(
        pv_config,
        irradiance_df=irradiance_df,
        irradiance_source_label=irradiance_label,
    )
    if demand_df is not None:
        return add_real_demand_to_simulation(pv_data, demand_df)
    return add_synthetic_industrial_demand(pv_data, demand_config)


@st.cache_data(show_spinner=False)
def run_scenario_grid(
    pv_config: PVSystemConfig,
    demand_config: DemandConfig,
    panel_counts: tuple[int, ...],
    tilts: tuple[float, ...],
    azimuths: tuple[float, ...],
    irradiance_df: pd.DataFrame | None,
) -> pd.DataFrame:
    return compare_scenarios(
        base_config=pv_config,
        demand_config=demand_config,
        panel_counts=list(panel_counts),
        tilts=list(tilts),
        azimuths=list(azimuths),
        irradiance_df=irradiance_df,
    )


def get_weather_adjustment() -> tuple[float, str]:
    source = st.session_state.irradiance_source
    if source != "Escenario climático simple":
        return 1.0, "No aplica"

    condition = st.session_state.climate_condition
    preset = CLIMATE_FACTORS.get(condition)
    if preset is None:
        return float(st.session_state.custom_weather_factor), "Escenario personalizado"
    return float(preset), condition


def build_pv_config_from_session_state() -> PVSystemConfig:
    weather_factor, weather_condition = get_weather_adjustment()
    return PVSystemConfig(
        year=int(st.session_state.year),
        latitude=float(st.session_state.latitude),
        longitude=float(st.session_state.longitude),
        altitude_m=float(st.session_state.altitude_m),
        tilt_deg=float(st.session_state.tilt_deg),
        azimuth_deg=float(st.session_state.azimuth_deg),
        panel_power_w=float(st.session_state.panel_power_w),
        panel_area_m2=float(st.session_state.panel_area_m2),
        panel_efficiency=float(st.session_state.panel_efficiency_percent) / 100.0,
        number_of_panels=int(st.session_state.number_of_panels),
        albedo=float(st.session_state.albedo),
        system_losses=float(st.session_state.system_losses_percent) / 100.0,
        timezone=str(st.session_state.timezone),
        transposition_model=str(st.session_state.transposition_model),
        weather_adjustment_factor=weather_factor,
        weather_condition=weather_condition,
    )


def build_stage1_simulation_signature(pv_config: PVSystemConfig, irradiance_label: str) -> tuple:
    return (
        "stage1",
        "selected_source",
        str(st.session_state.get("irradiance_source", DEFAULT_IRRADIANCE_SOURCE)),
        "used_source",
        str(irradiance_label),
        "weather_signature",
        current_external_irradiance_signature(pv_config),
        "nasa_mode",
        selected_nasa_power_mode(),
        "nasa_year",
        selected_nasa_power_year(),
        "nasa_base_year",
        selected_nasa_base_year(),
        "year",
        int(pv_config.year),
        "latitude",
        round(float(pv_config.latitude), 6),
        "longitude",
        round(float(pv_config.longitude), 6),
        "altitude_m",
        round(float(pv_config.altitude_m), 3),
        "timezone",
        str(pv_config.timezone),
        "number_of_panels",
        int(pv_config.number_of_panels),
        "panel_power_w",
        round(float(pv_config.panel_power_w), 6),
        "panel_area_m2",
        round(float(pv_config.panel_area_m2), 6),
        "panel_efficiency",
        round(float(pv_config.panel_efficiency), 8),
        "system_losses",
        round(float(pv_config.system_losses), 8),
        "tilt_deg",
        round(float(pv_config.tilt_deg), 6),
        "azimuth_deg",
        round(float(pv_config.azimuth_deg), 6),
        "albedo",
        round(float(pv_config.albedo), 8),
        "transposition_model",
        str(pv_config.transposition_model),
        "weather_adjustment_factor",
        round(float(pv_config.weather_adjustment_factor), 8),
        "weather_condition",
        str(pv_config.weather_condition),
    )


def stage1_signature_digest(signature: tuple) -> str:
    return hashlib.sha1(repr(signature).encode("utf-8")).hexdigest()[:12]


def build_stage1_current_simulation(
    demand_config: DemandConfig,
    demand_df: pd.DataFrame | None = None,
) -> tuple[PVSystemConfig, pd.DataFrame, dict[str, float], str, tuple]:
    pv_config = build_pv_config_from_session_state()
    validate_pv_system_config(pv_config)
    irradiance_df, irradiance_label = get_irradiance_data_or_none(pv_config)
    df = run_simulation(pv_config, demand_config, irradiance_df, irradiance_label, demand_df)
    summary = compute_summary(df=df, installed_power_kw=pv_config.installed_power_kw, total_area_m2=pv_config.total_area_m2)
    signature = build_stage1_simulation_signature(pv_config, irradiance_label)
    st.session_state.stage1_simulation_signature = signature
    return pv_config, df, summary, irradiance_label, signature


def build_sidebar() -> tuple[PVSystemConfig, DemandConfig, TariffConfig]:
    st.sidebar.title("FVoltData")
    st.sidebar.caption("Accesos rápidos")
    st.sidebar.button("Inicio", disabled=True, use_container_width=True)
    st.sidebar.button("Guía de uso", disabled=True, use_container_width=True)
    st.sidebar.button("Resumen", disabled=True, use_container_width=True)
    st.sidebar.caption("La configuración principal está dentro de las pestañas de trabajo.")

    pv_config = build_pv_config_from_session_state()
    try:
        validate_pv_system_config(pv_config)
    except ValueError as exc:
        st.sidebar.error(str(exc))
        st.stop()

    demand_config = DemandConfig(
        max_demand_kw=float(st.session_state.max_demand_kw),
        plant_factor=float(st.session_state.plant_factor),
        power_factor=float(st.session_state.power_factor),
        random_seed=int(st.session_state.random_seed),
        weekend_reduction=float(st.session_state.weekend_reduction),
        summer_increase=float(st.session_state.summer_increase),
    )

    tariff_config = TariffConfig(
        base_rate_mxn_kwh=float(st.session_state.base_rate_mxn_kwh),
        intermediate_rate_mxn_kwh=float(st.session_state.intermediate_rate_mxn_kwh),
        peak_rate_mxn_kwh=float(st.session_state.peak_rate_mxn_kwh),
        demand_rate_mxn_kw=float(st.session_state.demand_rate_mxn_kw),
        fixed_monthly_charge_mxn=float(st.session_state.fixed_monthly_charge_mxn),
        demand_charge_enabled=bool(st.session_state.demand_charge_enabled),
        distribution_rate_mxn_kw=float(st.session_state.distribution_rate_mxn_kw),
        capacity_rate_mxn_kw=float(st.session_state.capacity_rate_mxn_kw),
        iva_rate=float(st.session_state.iva_rate_percent) / 100.0,
    )

    return pv_config, demand_config, tariff_config


def get_irradiance_data_or_none(pv_config: PVSystemConfig) -> tuple[pd.DataFrame | None, str]:
    source = st.session_state.irradiance_source

    if source in {"Cielo despejado con pvlib Ineichen", "Escenario climático simple"}:
        return None, source

    if source in EXTERNAL_IRRADIANCE_SOURCES:
        current_signature = current_external_irradiance_signature(pv_config)
        load_requested = bool(st.session_state.pop("load_external_irradiance_requested", False))

        if load_requested:
            try:
                if source == "PVGIS con pvlib.iotools":
                    with st.spinner("Descargando irradiancia de PVGIS mediante pvlib.iotools..."):
                        data = load_pvgis_irradiance(
                            pv_config.latitude,
                            pv_config.longitude,
                            pv_config.year,
                            str(st.session_state.pvgis_database),
                            pv_config.timezone,
                        )
                    label = "PVGIS con pvlib.iotools"

                elif source == "NSRDB PSM3 con pvlib.iotools":
                    api_key = str(st.session_state.nsrdb_api_key).strip()
                    email = str(st.session_state.nsrdb_email).strip()
                    if not api_key or not email:
                        st.warning("Para cargar NSRDB debes indicar API key y correo registrado. Se usa cielo despejado temporalmente.")
                        return None, "Cielo despejado con pvlib Ineichen"

                    with st.spinner("Descargando irradiancia NSRDB PSM3 mediante pvlib.iotools..."):
                        data = load_nsrdb_irradiance(
                            pv_config.latitude,
                            pv_config.longitude,
                            pv_config.year,
                            api_key,
                            email,
                            int(st.session_state.nsrdb_interval),
                            pv_config.timezone,
                        )
                    label = "NSRDB PSM3 con pvlib.iotools"

                else:
                    with st.spinner("Descargando irradiancia de NASA POWER..."):
                        nasa_mode = selected_nasa_power_mode()
                        data = load_nasa_irradiance(
                            pv_config.latitude,
                            pv_config.longitude,
                            pv_config.year,
                            effective_nasa_power_year(
                                nasa_mode,
                                pv_config.year,
                                selected_nasa_power_year(),
                            ),
                            pv_config.timezone,
                            nasa_mode,
                            selected_nasa_base_year(),
                        )
                    diagnostics = data.attrs.get("nasa_power_diagnostics", {})
                    label = "NASA POWER provisional" if diagnostics.get("is_provisional") else "NASA POWER"
                    final_report = validate_final_weather_dataframe(data, pv_config.year)
                    diagnostics = {**diagnostics, **final_report}
                    data.attrs["nasa_power_diagnostics"] = diagnostics

                st.session_state.external_irradiance_df = data
                st.session_state.external_irradiance_signature = current_signature
                st.session_state.external_irradiance_label = label
                st.session_state.active_irradiance_source = label
                st.session_state.selected_irradiance_source = source
                st.session_state.weather_source_signature = current_signature
                st.session_state.external_irradiance_status = (
                    f"modo provisional {pv_config.year}" if label == "NASA POWER provisional" else "cargada correctamente"
                )
                st.session_state.external_irradiance_error_detail = ""
                if label in {"NASA POWER", "NASA POWER provisional"}:
                    st.session_state.external_irradiance_diagnostics = data.attrs.get("nasa_power_diagnostics", {})
                    st.session_state.nasa_requested_year = int(st.session_state.external_irradiance_diagnostics.get("selected_data_year", pv_config.year))
                    st.session_state.nasa_base_year = int(st.session_state.external_irradiance_diagnostics.get("base_year", DEFAULT_NASA_POWER_YEAR))
                st.success(f"Datos solares externos cargados: {label}")
                return data, label
            except Exception as exc:
                st.session_state.external_irradiance_df = None
                st.session_state.external_irradiance_signature = None
                st.session_state.external_irradiance_label = ""
                error_detail = str(exc)
                st.session_state.external_irradiance_error_detail = error_detail
                st.session_state.external_irradiance_diagnostics = {}
                if source == "NASA POWER" and (
                    "coverage insufficient" in error_detail or "does not cover enough" in error_detail
                ):
                    st.session_state.external_irradiance_status = "datos incompletos para el año seleccionado"
                    st.warning(
                        "NASA POWER no tiene datos completos para el año seleccionado. "
                        "Se mantiene cielo despejado temporalmente. Prueba con un año completo anterior."
                    )
                else:
                    st.session_state.external_irradiance_status = "error de carga"
                    st.warning(
                        "No se pudo cargar la fuente externa seleccionada. "
                        "Se mantiene cielo despejado temporalmente."
                    )
                return None, "Cielo despejado con pvlib Ineichen"

        loaded_data = st.session_state.get("external_irradiance_df")
        loaded_signature = st.session_state.get("external_irradiance_signature")
        if isinstance(loaded_data, pd.DataFrame) and external_irradiance_signature_matches(
            loaded_signature,
            current_signature,
        ):
            loaded_label = str(st.session_state.get("external_irradiance_label", source))
            if loaded_label in {"NASA POWER", "NASA POWER provisional"}:
                try:
                    validate_final_weather_dataframe(loaded_data, pv_config.year)
                except Exception as exc:
                    st.session_state.external_irradiance_status = "tabla final inválida"
                    st.session_state.external_irradiance_error_detail = str(exc)
                    st.warning("NASA POWER cargado no cubre correctamente el año de simulación. Recarga la fuente externa.")
                    return None, "Cielo despejado con pvlib Ineichen"
            return loaded_data, loaded_label

        if loaded_signature is not None:
            log_weather_signature_mismatch(source, current_signature, loaded_signature, loaded_data)
            if source == "NASA POWER":
                st.warning(
                    "Los datos NASA POWER cargados corresponden a una configuración anterior. "
                    "Para usar NASA en la ubicación actual, vuelve a cargar los datos climáticos. "
                    "Mientras tanto, se usa cielo despejado temporalmente."
                )
            else:
                st.warning("Los datos externos cargados no coinciden con la configuración actual; se usa cielo despejado temporalmente.")
        else:
            st.info("Aún no se han cargado datos externos para esta configuración; se usa cielo despejado temporalmente.")
        return None, "Cielo despejado con pvlib Ineichen"

    try:
        if source == "CSV propio":
            uploaded_file = st.session_state.get("uploaded_irradiance_file")
            if uploaded_file is None:
                st.info("Carga un CSV o Excel de irradiancia. Mientras tanto se usará cielo despejado con pvlib Ineichen.")
                return None, "Cielo despejado con pvlib Ineichen"
            data = read_uploaded_irradiance(uploaded_file, year=pv_config.year)
            data = to_15min_irradiance(data, year=pv_config.year, timezone=pv_config.timezone)
            return data, "CSV propio"

    except Exception as exc:
        st.error(f"No se pudo obtener la fuente seleccionada. Corrige la configuración o cambia de fuente. Detalle: {exc}")
        st.stop()

    return None, "Cielo despejado con pvlib Ineichen"


def get_demand_data_or_none(pv_config: PVSystemConfig, demand_config: DemandConfig) -> pd.DataFrame | None:
    if st.session_state.demand_mode != "Demanda cargada por archivo":
        return None

    uploaded_file = st.session_state.get("uploaded_demand_file")
    if uploaded_file is None:
        st.info("Carga un CSV o Excel de demanda. Mientras tanto se usará la demanda sintética validada.")
        return None

    try:
        demand_df = read_uploaded_demand(
            uploaded_file,
            year=pv_config.year,
            timezone=pv_config.timezone,
            default_power_factor=demand_config.power_factor,
        )
    except Exception as exc:
        st.error(f"No se pudo leer la demanda cargada. Detalle: {exc}")
        st.stop()

    for warning in demand_df.attrs.get("warnings", []):
        st.warning(warning)
    return demand_df


def render_data_source_tab(df: pd.DataFrame) -> None:
    section_header(
        "Recurso solar usado por el modelo",
        "Resumen de la fuente de irradiancia que alimenta el cálculo POA y la generación fotovoltaica.",
        icon_name="sun",
    )

    first = df.iloc[0]
    info_panel(
        title="Fuente activa",
        body=(
            f"Fuente: {first['irradiance_source']}. Detalle del procesamiento: {first['weather_model_detail']}. "
            f"Modelo de transposición: {first['transposition_model']}."
        ),
        icon_name="settings",
    )

    st.markdown(
        """
        Esta sección muestra la irradiancia que realmente está usando la simulación. Si seleccionas
        una fuente externa o CSV propio y no hay datos cargados válidos, la app usa cielo despejado
        temporalmente y lo indica en la fuente activa.
        """
    )

    st.subheader("Vista previa del recurso solar usado por el modelo")
    st.caption(
        "Se muestran las primeras 96 filas, equivalentes al primer día simulado en intervalos de 15 minutos."
    )
    cols = ["datetime", "irradiance_source", "weather_model_detail", "GHI_W_m2", "DNI_W_m2", "DHI_W_m2", "POA_W_m2"]
    st.dataframe(df[cols].head(96), use_container_width=True, height=320)

    st.divider()
    section_header(
        "CSV propio de irradiancia",
        "Plantilla opcional para cargar una fuente de irradiancia preparada por el usuario.",
        icon_name="file-spreadsheet",
    )
    st.markdown(
        """
        Esta plantilla sirve solo si seleccionas **CSV propio** como fuente de irradiancia en la barra lateral.
        No descarga los resultados de la simulación; descarga un archivo de ejemplo con el formato esperado.

        Columnas obligatorias: `datetime`, `ghi`.

        Columnas opcionales: `dni`, `dhi`, `temp_air`, `wind_speed`.

        La carga del archivo se realiza en **Configuración > Fuente de irradiancia y POA > CSV propio**.
        """
    )

    sample = pd.DataFrame(
        {
            "datetime": pd.date_range(f"{int(st.session_state.year)}-01-01", periods=4, freq="15min"),
            "ghi": [0, 0, 12, 25],
            "dni": [0, 0, 0, 10],
            "dhi": [0, 0, 12, 15],
            "temp_air": [18, 18, 18.2, 18.4],
            "wind_speed": [1.2, 1.1, 1.3, 1.4],
        }
    )
    st.download_button(
        "Descargar plantilla CSV de irradiancia",
        data=sample.to_csv(index=False).encode("utf-8"),
        file_name="plantilla_irradiancia.csv",
        mime="text/csv",
    )


def _queue_location_update(
    latitude: float,
    longitude: float,
    label: str | None = None,
    altitude_m: float | None = None,
    event_id: str | None = None,
) -> None:
    st.session_state.pending_latitude = float(latitude)
    st.session_state.pending_longitude = float(longitude)

    if label:
        st.session_state.pending_location_label = label

    if bool(st.session_state.get("auto_altitude", True)) and altitude_m is not None:
        st.session_state.pending_altitude_m = max(0.0, float(altitude_m))

    if event_id:
        st.session_state.pending_map_event_id = str(event_id)


def render_location_tab() -> None:
    section_header(
        "Selección geográfica",
        "Busca un lugar con Google Places o haz click en el mapa para definir la ubicación de la simulación.",
        icon_name="map",
    )

    info_panel(
        title="Ubicación activa",
        body=(
            f"Latitud {st.session_state.latitude:.6f}, longitud {st.session_state.longitude:.6f}, "
            f"altitud {st.session_state.altitude_m:.0f} m. Zona horaria {st.session_state.timezone}."
        ),
        icon_name="map",
    )

    api_key = get_google_maps_api_key()
    if not api_key:
        st.info(
            "El mapa interactivo no está configurado. Puedes usar latitud, longitud y altitud manualmente."
        )
        return

    map_result = GOOGLE_MAP_PICKER(
        api_key=api_key,
        latitude=float(st.session_state.latitude),
        longitude=float(st.session_state.longitude),
        altitude_m=float(st.session_state.altitude_m),
        label=str(st.session_state.get("selected_location_label", "")),
        location_version=int(st.session_state.get("location_version", 0)),
        auto_altitude=bool(st.session_state.get("auto_altitude", True)),
        height=560,
        key="google_location_map",
        default=None,
    )

    if isinstance(map_result, dict) and map_result.get("latitude") is not None and map_result.get("longitude") is not None:
        if not is_fresh_map_location_event(
            map_result,
            int(st.session_state.get("location_version", 0)),
            str(st.session_state.get("last_map_event_id", "")),
        ):
            return
        selected_lat = float(map_result["latitude"])
        selected_lon = float(map_result["longitude"])
        label = str(map_result.get("label") or format_coordinate_label(selected_lat, selected_lon))
        altitude = map_result.get("altitude_m")
        changed = (
            abs(selected_lat - float(st.session_state.latitude)) > 1e-6
            or abs(selected_lon - float(st.session_state.longitude)) > 1e-6
            or label != str(st.session_state.get("selected_location_label", ""))
            or (altitude is not None and abs(float(altitude) - float(st.session_state.altitude_m)) > 0.5)
        )
        if changed:
            _queue_location_update(
                selected_lat,
                selected_lon,
                label,
                float(altitude) if altitude is not None else None,
                str(map_result.get("event_id", "")),
            )
            st.rerun()
        else:
            st.session_state.last_map_event_id = str(map_result.get("event_id", ""))

    st.caption(
        "Mapa con Google Maps JavaScript API. Búsqueda con Places Autocomplete y altitud con Elevation API."
    )


STAGE1_STEPS = [
    ("ubicacion", "Ubicación"),
    ("fuente_solar", "Fuente solar"),
    ("sistema_fv", "Sistema FV"),
    ("orientacion", "Orientación"),
    ("resultados", "Resultados"),
]


def _stage1_step_ids() -> list[str]:
    return [step_id for step_id, _label in STAGE1_STEPS]


def _set_stage1_step(step_id: str) -> None:
    if step_id in _stage1_step_ids():
        st.session_state.stage1_step = step_id
        st.session_state.stage1_scroll_to_top = True


def _select_irradiance_source(source: str) -> None:
    st.session_state.irradiance_source = source
    st.session_state.selected_irradiance_source = source
    st.session_state.irradiance_source_group = IRRADIANCE_SOURCE_GROUP_BY_SOURCE.get(
        source,
        "Fuente principal del MVP",
    )


def _recommended_tilt(latitude: float) -> int:
    return int(round(min(max(abs(float(latitude)), 5.0), 40.0)))


def render_stage1_progress() -> None:
    active_step = str(st.session_state.get("stage1_step", "ubicacion"))
    if active_step not in _stage1_step_ids():
        active_step = "ubicacion"
        st.session_state.stage1_step = active_step
    active_index = _stage1_step_ids().index(active_step)

    cols = st.columns(len(STAGE1_STEPS))
    for index, (step_id, label) in enumerate(STAGE1_STEPS):
        if index < active_index:
            status = "Listo"
        elif index == active_index:
            status = "Actual"
        else:
            status = ""
        with cols[index]:
            button_type = "primary" if index == active_index else "secondary"
            if st.button(label, key=f"stage1_step_button_{step_id}", use_container_width=True, type=button_type):
                _set_stage1_step(step_id)
                st.rerun()
            if status:
                st.caption(status)


def render_stage1_navigation() -> None:
    step_ids = _stage1_step_ids()
    active_step = str(st.session_state.get("stage1_step", "ubicacion"))
    if active_step not in step_ids:
        active_step = "ubicacion"
    index = step_ids.index(active_step)
    left, _middle, right = st.columns([1, 3, 1])
    if index > 0:
        previous_id, previous_label = STAGE1_STEPS[index - 1]
        if left.button(previous_label, key=f"stage1_previous_{active_step}", use_container_width=True):
            _set_stage1_step(previous_id)
            st.rerun()
    if index < len(STAGE1_STEPS) - 1:
        next_id, next_label = STAGE1_STEPS[index + 1]
        if right.button(next_label, key=f"stage1_next_{active_step}", use_container_width=True):
            _set_stage1_step(next_id)
            st.rerun()


def render_stage1_context(summary: dict[str, float], source_label: str | None = None) -> None:
    source = source_label or str(st.session_state.get("irradiance_source", DEFAULT_IRRADIANCE_SOURCE))
    label = str(st.session_state.get("selected_location_label", "")).strip()
    if not label:
        label = format_coordinate_label(float(st.session_state.latitude), float(st.session_state.longitude))
    installed_kwp = int(st.session_state.number_of_panels) * float(st.session_state.panel_power_w) / 1000.0
    with st.container(border=True):
        st.caption(
            f"Ubicación: {label} · Fuente: {source} · Sistema: {int(st.session_state.number_of_panels)} paneles, "
            f"{installed_kwp:.2f} kWp · Orientación: tilt {float(st.session_state.tilt_deg):.0f}°, "
            f"azimuth {float(st.session_state.azimuth_deg):.0f}°"
        )


def render_stage1_location_step() -> None:
    section_header(
        "Ubicación",
        "La ubicación permite calcular la posición del Sol, la irradiancia disponible y la orientación recomendada del panel.",
        icon_name="map",
    )
    col1, col2, col3, col4 = st.columns(4)
    col1.number_input("Año de simulación", min_value=2018, max_value=2035, step=1, key="year")
    col2.number_input("Latitud", format="%.6f", key="latitude", on_change=register_manual_location_change)
    col3.number_input("Longitud", format="%.6f", key="longitude", on_change=register_manual_location_change)
    col4.number_input(
        "Altitud [m]",
        min_value=0.0,
        max_value=5000.0,
        step=10.0,
        key="altitude_m",
        on_change=register_manual_location_change,
        args=(False,),
    )

    col5, col6 = st.columns(2)
    col5.checkbox("Actualizar altitud al cambiar ubicación", key="auto_altitude")
    col6.checkbox(
        "Actualizar zona horaria automáticamente al cambiar ubicación",
        key="auto_timezone",
        on_change=handle_auto_timezone_toggle,
        help="Usa Google Time Zone API con la API key local. Si falla, se conserva la zona horaria manual.",
    )

    timezone_message = str(st.session_state.get("timezone_status_message", ""))
    if timezone_message:
        if st.session_state.get("timezone_status_level") == "success":
            st.success(timezone_message)
        else:
            st.warning(timezone_message)

    timezone_options = get_timezone_select_options()
    st.selectbox(
        "Zona horaria",
        options=timezone_options,
        key="timezone",
        help="La zona horaria afecta posición solar, demanda real y periodos tarifarios.",
    )

    with st.expander("Mostrar mapa interactivo", expanded=True):
        render_location_tab()


def _nasa_variables_label(diagnostics: dict) -> str:
    columns_present = set(diagnostics.get("columns_present", []))
    labels = []
    for column, label in [
        ("GHI_W_m2", "GHI"),
        ("DNI_W_m2", "DNI"),
        ("DHI_W_m2", "DHI"),
        ("temperature_C", "temperatura"),
        ("wind_speed_m_s", "viento"),
    ]:
        if column in columns_present:
            labels.append(label)
    return ", ".join(labels) if labels else "GHI, DNI, DHI, temperatura y viento"


def render_nasa_power_status_card(diagnostics: dict, source_used: str) -> None:
    """Render a human-readable NASA POWER status without exposing raw diagnostics."""
    if not isinstance(diagnostics, dict) or not diagnostics:
        st.success("NASA POWER cargado correctamente.")
        st.caption(f"Fuente usada por el modelo: {source_used}.")
        return

    is_provisional = bool(diagnostics.get("is_provisional", False))
    simulation_year = int(diagnostics.get("simulation_year", st.session_state.get("year", 0)))
    base_year = int(diagnostics.get("base_year", DEFAULT_NASA_POWER_YEAR))
    data_year = int(diagnostics.get("selected_data_year", diagnostics.get("nasa_data_year", base_year)))
    covered_days = int(diagnostics.get("covered_days", 0))
    days_in_year = int(diagnostics.get("days_in_year", 365))
    real_days = int(diagnostics.get("real_days", covered_days))
    completed_days = int(diagnostics.get("completed_days", max(days_in_year - real_days, 0)))

    if is_provisional:
        st.success("NASA POWER provisional cargado correctamente.")
        st.caption(
            f"Año de simulación: {simulation_year}. Datos disponibles usados: {data_year}. "
            f"Complemento histórico: {base_year}. Cobertura final: {covered_days} de {days_in_year} días. "
            f"Fuente usada por el modelo: {source_used}."
        )
    else:
        st.success("NASA POWER cargado correctamente.")
        st.caption(
            f"NASA POWER usa datos climáticos completos de {base_year} como referencia "
            f"para la simulación {simulation_year}."
        )

    col1, col2, col3 = st.columns(3)
    col1.metric("Fuente usada por el modelo", source_used)
    col2.metric("Año de simulación", f"{simulation_year}")
    col3.metric("Año climático usado", f"{data_year if is_provisional else base_year}")

    col4, col5, col6 = st.columns(3)
    if is_provisional:
        col4.metric("Datos reales disponibles", f"{real_days} días")
        col5.metric(f"Días completados con {base_year}", f"{completed_days} días")
    else:
        col4.metric("Datos reales disponibles", f"{covered_days} días")
        col5.metric("Días completados", "0 días")
    col6.metric("Cobertura final", f"{covered_days} de {days_in_year} días")

    st.caption("Resolución usada por el modelo: 15 minutos.")
    st.caption(f"Variables disponibles: {_nasa_variables_label(diagnostics)}.")


def render_stage1_source_step(df: pd.DataFrame) -> None:
    first = df.iloc[0]
    section_header(
        "Fuente solar",
        "Elige de dónde sale la irradiancia que alimenta el cálculo POA y la producción fotovoltaica.",
        icon_name="sun",
    )
    selected_source = str(st.session_state.irradiance_source)
    source_used = str(first["irradiance_source"])
    status = "cargada" if selected_source == source_used else "se usa fallback temporal"
    if selected_source == "NASA POWER":
        prepare_nasa_power_widget_state()
        st.radio(
            "Modo de datos NASA POWER",
            options=NASA_POWER_MODES,
            key="_nasa_power_mode_widget",
            on_change=sync_nasa_power_mode_widget,
            help=(
                "El modo recomendado usa el último año completo disponible. El modo provisional usa el año de simulación "
                "y completa faltantes con el último año completo."
            ),
        )
        nasa_mode = selected_nasa_power_mode()
        if nasa_mode == NASA_POWER_MODE_CUSTOM:
            st.number_input(
                "Año histórico NASA POWER",
                min_value=NASA_POWER_MIN_YEAR,
                max_value=DEFAULT_NASA_POWER_YEAR,
                step=1,
                key="_nasa_power_year_widget",
                on_change=sync_nasa_power_year_widget,
                help="Elige un año completo anterior soportado por NASA POWER.",
            )
        elif nasa_mode == NASA_POWER_MODE_PROVISIONAL:
            st.info(
                f"NASA POWER provisional: se usan los datos disponibles de {int(st.session_state.year)} "
                f"y los días faltantes se completan con el patrón climático de {selected_nasa_base_year()}."
            )
        else:
            st.info(
                f"NASA POWER usa datos climáticos completos de {selected_nasa_base_year()} "
                f"como referencia para la simulación {int(st.session_state.year)}."
            )
        loaded_signature = st.session_state.get("external_irradiance_signature")
        current_signature = current_weather_source_signature(
            source=selected_source,
            latitude=float(st.session_state.latitude),
            longitude=float(st.session_state.longitude),
            year=int(st.session_state.year),
            timezone=str(st.session_state.timezone),
            pvgis_database=str(st.session_state.get("pvgis_database", "Automático")),
            nsrdb_interval=int(st.session_state.get("nsrdb_interval", 30)),
            nasa_power_mode=nasa_mode,
        )
        if external_irradiance_signature_matches(loaded_signature, current_signature):
            status = "modo provisional" if source_used == "NASA POWER provisional" else "cargada correctamente"
        else:
            status = str(st.session_state.get("external_irradiance_status", "") or "no cargada")
    if selected_source == "CSV propio" and st.session_state.get("uploaded_irradiance_file") is None:
        status = "no cargada"

    source_status_labels = {
        "Cielo despejado con pvlib Ineichen": "Cielo despejado",
        "NASA POWER provisional": "NASA POWER",
        "PVGIS con pvlib.iotools": "PVGIS",
        "NSRDB PSM3 con pvlib.iotools": "NSRDB PSM3",
    }
    selected_source_status = source_status_labels.get(selected_source, selected_source)
    source_used_status = source_status_labels.get(source_used, source_used)
    source_status_notes = []
    if selected_source_status != selected_source:
        source_status_notes.append(f"Fuente seleccionada completa: {selected_source}.")
    if source_used == "NASA POWER provisional":
        source_status_notes.append("Fuente usada por el modelo: NASA POWER, modo provisional.")
    elif source_used_status != source_used:
        source_status_notes.append(f"Fuente usada por el modelo: {source_used}.")

    col_status1, col_status2, col_status3 = st.columns(3)
    col_status1.metric("Fuente seleccionada", selected_source_status)
    col_status2.metric("Estado", status)
    col_status3.metric("Fuente usada", source_used_status)
    for note in source_status_notes:
        st.caption(note)
    st.caption(f"Detalle del procesamiento: {first['weather_model_detail']}.")

    main_sources = [
        (
            "Cielo despejado con pvlib Ineichen",
            "Cielo despejado",
            "Estimación rápida sin nubosidad para comparar ubicación y orientación.",
        ),
        (
            "NASA POWER",
            "NASA POWER",
            "Datos históricos de irradiancia, temperatura y viento de la zona.",
        ),
        (
            "CSV propio",
            "CSV propio",
            "Datos medidos o proporcionados por una fuente externa.",
        ),
    ]

    cols = st.columns(3)
    for col, (source, title, description) in zip(cols, main_sources):
        with col.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(description)
            active = selected_source == source
            st.caption("Activa" if active else "Disponible")
            if st.button(f"Usar {title}", key=f"use_source_{source}", use_container_width=True, disabled=active):
                _select_irradiance_source(source)
                st.rerun()

    source = str(st.session_state.irradiance_source)
    if source == "NASA POWER":
        nasa_mode = selected_nasa_power_mode()
        current_signature = current_weather_source_signature(
            source=source,
            latitude=float(st.session_state.latitude),
            longitude=float(st.session_state.longitude),
            year=int(st.session_state.year),
            timezone=str(st.session_state.timezone),
            pvgis_database=str(st.session_state.get("pvgis_database", "Automático")),
            nsrdb_interval=int(st.session_state.get("nsrdb_interval", 30)),
            nasa_power_mode=nasa_mode,
        )
        loaded_signature = st.session_state.get("external_irradiance_signature")
        if external_irradiance_signature_matches(loaded_signature, current_signature):
            diagnostics = st.session_state.get("external_irradiance_diagnostics", {})
            render_nasa_power_status_card(
                diagnostics if isinstance(diagnostics, dict) else {},
                str(st.session_state.get("external_irradiance_label", "NASA POWER")),
            )
        elif loaded_signature is not None:
            log_weather_signature_mismatch(source, current_signature, loaded_signature, st.session_state.get("external_irradiance_df"))
            st.warning(
                "Los datos NASA POWER cargados corresponden a una configuración anterior. "
                "Para usar NASA en la ubicación actual, vuelve a cargar los datos climáticos. "
                "Mientras tanto, se usa cielo despejado temporalmente."
            )
        else:
            nasa_status = str(st.session_state.get("external_irradiance_status", ""))
            if nasa_status == "datos incompletos para el año seleccionado":
                st.warning(
                    "NASA POWER no tiene datos completos para el año seleccionado. "
                    "Se mantiene cielo despejado temporalmente. Prueba con un año completo anterior."
                )
                detail = str(st.session_state.get("external_irradiance_error_detail", ""))
                if detail:
                    with st.expander("Ver detalle técnico"):
                        st.caption(detail)
            else:
                st.info("NASA POWER no cargado. Se usa cielo despejado temporalmente hasta presionar Cargar datos NASA POWER.")
        if st.button("Cargar datos NASA POWER", key="stage1_load_nasa_power", use_container_width=True):
            st.session_state.load_external_irradiance_requested = True
            st.rerun()

    if source == "CSV propio":
        st.file_uploader(
            "Archivo CSV o Excel de irradiancia",
            type=["csv", "xlsx", "xls"],
            key="uploaded_irradiance_file",
            help="Columnas mínimas: datetime y ghi. Opcionales: dni, dhi, temp_air, wind_speed.",
        )
        if st.session_state.get("uploaded_irradiance_file") is None:
            st.info("CSV propio no cargado. Se usa cielo despejado temporalmente hasta cargar un archivo válido.")

    if source not in {"Cielo despejado con pvlib Ineichen", "NASA POWER", "CSV propio"}:
        st.warning("Hay una fuente avanzada activa. Puedes gestionarla en la pestaña Avanzado o elegir una fuente principal arriba.")


def render_stage1_system_step(summary: dict[str, float]) -> None:
    section_header(
        "Sistema FV",
        "Define el tamaño del sistema fotovoltaico para estimar producción anual.",
        icon_name="settings",
    )
    installed_kwp = int(st.session_state.number_of_panels) * float(st.session_state.panel_power_w) / 1000.0
    col1, col2, col3 = st.columns(3)
    col1.number_input("Número de paneles", min_value=1, max_value=2000, step=1, key="number_of_panels", on_change=mark_stage1_fv_user_modified)
    col2.number_input("Potencia por panel [W]", min_value=100.0, max_value=800.0, step=10.0, key="panel_power_w", on_change=mark_stage1_fv_user_modified)
    col3.metric("Potencia instalada", f"{installed_kwp:.2f} kWp")

    with st.expander("Configuración avanzada del panel"):
        st.number_input("Área por panel [m2]", min_value=1.0, max_value=4.0, step=0.1, key="panel_area_m2", on_change=mark_stage1_fv_user_modified)
        st.slider("Eficiencia del panel [%]", min_value=10.0, max_value=25.0, step=0.1, key="panel_efficiency_percent", on_change=mark_stage1_fv_user_modified)
        st.slider(
            "Pérdidas del sistema [%]",
            min_value=0.0,
            max_value=30.0,
            step=0.5,
            key="system_losses_percent",
            on_change=mark_stage1_fv_user_modified,
            help="Pérdidas agregadas por inversor, cableado, suciedad, mismatch, disponibilidad y otros efectos.",
        )
    st.caption("La potencia instalada se calcula con número de paneles y potencia nominal por panel.")


def render_stage1_orientation_step(summary: dict[str, float]) -> None:
    section_header(
        "Orientación",
        "Ajusta inclinación y dirección del arreglo fotovoltaico.",
        icon_name="settings",
    )
    recommended_tilt = _recommended_tilt(float(st.session_state.latitude))
    col1, col2, col3 = st.columns(3)
    col1.metric("Tilt recomendado aproximado", f"{recommended_tilt}°")
    col2.metric("Azimuth recomendado", "180°")
    col3.metric("Producción anual actual", f"{summary['total_generation_kwh']:,.0f} kWh")

    col4, col5 = st.columns(2)
    col4.slider("Tilt [deg]", min_value=0, max_value=60, step=1, key="tilt_deg", on_change=mark_stage1_orientation_user_modified)
    col5.slider("Azimuth [deg]", min_value=0, max_value=360, step=5, key="azimuth_deg", on_change=mark_stage1_orientation_user_modified)

    st.caption(
        "El tilt define qué tan inclinado está el panel respecto al suelo. El azimuth define hacia dónde apunta. "
        "En México, orientar hacia el sur, 180 grados, es un punto de partida recomendado."
    )
    st.caption(
        "La recomendación usa la latitud del proyecto como punto de partida geométrico. "
        "La producción se calcula con la fuente solar seleccionada."
    )


def _coerce_plot_date_for_year(raw_date: object, simulation_year: int) -> object:
    min_date = pd.to_datetime(f"{simulation_year}-01-01").date()
    max_date = pd.to_datetime(f"{simulation_year}-12-31").date()
    default_date = pd.to_datetime(f"{simulation_year}-06-21").date()
    try:
        selected_date = pd.to_datetime(raw_date).date()
    except Exception:
        selected_date = default_date
    if selected_date < min_date or selected_date > max_date:
        selected_date = default_date
    return selected_date


def _solar_plot_context_caption(selected_date: object, source_used: str, diagnostics: dict) -> str:
    simulation_year = int(st.session_state.get("year", pd.to_datetime(selected_date).year))
    source = str(source_used)
    date_label = pd.to_datetime(selected_date).strftime("%Y-%m-%d")

    if source == "NASA POWER provisional":
        selected_year = int(diagnostics.get("selected_data_year", simulation_year)) if isinstance(diagnostics, dict) else simulation_year
        base_year = int(diagnostics.get("base_year", DEFAULT_NASA_POWER_YEAR)) if isinstance(diagnostics, dict) else DEFAULT_NASA_POWER_YEAR
        return (
            f"Fecha simulada: {date_label}. Datos climáticos usados: NASA POWER {selected_year} "
            f"si existen; días faltantes completados con {base_year}."
        )

    if source == "NASA POWER":
        climate_year = (
            int(diagnostics.get("base_year", diagnostics.get("nasa_data_year", DEFAULT_NASA_POWER_YEAR)))
            if isinstance(diagnostics, dict)
            else DEFAULT_NASA_POWER_YEAR
        )
        return (
            f"Fecha simulada: {date_label}. Datos climáticos usados: NASA POWER {climate_year} "
            f"remapeado a {simulation_year}."
        )

    if source == "CSV propio":
        return f"Fecha simulada: {date_label}. Datos usados desde el CSV cargado."

    if "NASA POWER" in source:
        return f"Fecha simulada: {date_label}. Datos climáticos usados: {source}."

    if "Cielo despejado" in source or "Ineichen" in source:
        return f"Fecha simulada: {date_label}. Datos estimados con cielo despejado."

    return f"Fecha simulada: {date_label}. Datos usados desde la fuente solar activa: {source}."


def render_solar_result_cards(
    summary: dict[str, float],
    production_per_panel: float,
    installed_kwp: float,
    pvout_daily: float,
) -> None:
    cards = [
        (
            "Producción anual estimada",
            f"{summary['total_generation_kwh']:,.0f} kWh/año",
            "Energía FV anual con pérdidas actuales",
        ),
        (
            "Producción por panel",
            f"{production_per_panel:,.0f} kWh/año",
            "Promedio anual por módulo",
        ),
        (
            "Potencia instalada",
            f"{installed_kwp:.2f} kWp",
            "Capacidad nominal del arreglo",
        ),
        (
            "PVOUT diario",
            f"{pvout_daily:.2f} kWh/kWp/día",
            "Producción diaria específica",
        ),
        (
            "Rendimiento específico",
            f"{summary['specific_yield_kwh_kwp']:,.0f} kWh/kWp/año",
            "Producción anual por kWp instalado",
        ),
    ]
    html_cards = []
    for label, value, subtext in cards:
        html_cards.append(
            (
                '<div class="solar-result-card">'
                f'<p class="label">{html.escape(label)}</p>'
                f'<div class="value">{html.escape(value)}</div>'
                f'<p class="subtext">{html.escape(subtext)}</p>'
                "</div>"
            )
        )
    st.markdown(f"<div class='solar-results-grid'>{''.join(html_cards)}</div>", unsafe_allow_html=True)


def render_results_interpretation_expander(df: pd.DataFrame) -> None:
    poa_model_used = (
        str(df["transposition_model"].iloc[0])
        if "transposition_model" in df.columns and not df.empty
        else str(st.session_state.transposition_model)
    )
    poa_model_name = poa_model_used.strip() or "modelo configurado"
    if poa_model_used.lower() == "haydavies":
        poa_model_text = (
            "Hay-Davies considera la componente directa y una distribución anisotrópica de la radiación difusa. "
            "Es una buena opción cuando el modelo cuenta con GHI, DNI y DHI."
        )
    elif poa_model_used.lower() == "isotropic":
        poa_model_text = (
            "El modelo isotrópico es una aproximación simple para distribuir la radiación difusa del cielo "
            "sobre el plano inclinado del panel."
        )
    else:
        poa_model_text = (
            f"Se usa {poa_model_name}. Este modelo transforma la irradiancia horizontal al plano real del arreglo."
        )

    source_used = str(df["irradiance_source"].iloc[0]) if "irradiance_source" in df.columns and not df.empty else ""
    if "NASA POWER" in source_used:
        source_text = (
            "NASA POWER aporta datos climáticos históricos de irradiancia, temperatura y viento. "
            "Ayuda a representar condiciones más realistas que cielo despejado, aunque no sustituye mediciones en sitio."
        )
    elif "Cielo despejado" in source_used or "Ineichen" in source_used:
        source_text = (
            "Cielo despejado con pvlib Ineichen es una referencia sin nubosidad. Sirve para comparar ubicación, "
            "inclinación y orientación, pero no debe leerse como producción garantizada."
        )
    else:
        source_text = (
            f"La fuente activa es {source_used or 'la fuente seleccionada'}. El modelo usa esa irradiancia para calcular POA y generación."
        )

    blocks = [
        (
            "POA",
            "POA es la irradiancia que llega al plano del panel. Considera la inclinación, la orientación y la posición del Sol.",
        ),
        ("Modelo POA usado", f"{poa_model_name}: {poa_model_text}"),
        ("Fuente solar", source_text),
        (
            "Lectura correcta",
            "Un pico instantáneo de POA no representa la producción anual. Para decisiones reales conviene revisar producción anual, pérdidas y escenarios.",
        ),
    ]
    block_html = []
    for title, body in blocks:
        block_html.append(
            (
                '<div class="interpretation-block">'
                f"<h4>{html.escape(title)}</h4>"
                f"<p>{html.escape(body)}</p>"
                "</div>"
            )
        )
    with st.expander("Cómo interpretar estos resultados"):
        st.markdown(f"<div class='interpretation-grid'>{''.join(block_html)}</div>", unsafe_allow_html=True)


def build_realism_loss_scenarios(
    df: pd.DataFrame,
    installed_power_kw: float,
    number_of_panels: int,
    days_in_year: int,
) -> pd.DataFrame:
    if df.empty or "raw_dc_power_kW" not in df.columns:
        return pd.DataFrame()

    rows = []
    safe_panels = max(int(number_of_panels), 1)
    for scenario, config in REALISM_LOSS_SCENARIOS.items():
        losses = float(config["losses"])
        annual_generation = float((df["raw_dc_power_kW"] * max(0.0, 1.0 - losses) * 0.25).sum())
        specific_yield = annual_generation / installed_power_kw if installed_power_kw > 0 else 0.0
        rows.append(
            {
                "scenario": scenario,
                "losses": losses,
                "losses_percent": 100.0 * losses,
                "annual_generation_kWh": annual_generation,
                "production_per_panel_kWh": annual_generation / safe_panels,
                "specific_yield_kWh_kWp": specific_yield,
                "pvout_daily_kWh_kWp_day": specific_yield / days_in_year if days_in_year else 0.0,
                "description": str(config["description"]),
            }
        )

    scenarios = pd.DataFrame(rows)
    recommended = scenarios.loc[scenarios["scenario"] == "Recomendado", "annual_generation_kWh"]
    recommended_value = float(recommended.iloc[0]) if not recommended.empty else 0.0
    scenarios["delta_vs_recommended_kWh"] = scenarios["annual_generation_kWh"] - recommended_value
    return scenarios


def render_realism_loss_scenarios(df: pd.DataFrame, summary: dict[str, float], days_in_year: int) -> None:
    scenarios = build_realism_loss_scenarios(
        df=df,
        installed_power_kw=float(summary["installed_power_kw"]),
        number_of_panels=int(st.session_state.number_of_panels),
        days_in_year=days_in_year,
    )
    if scenarios.empty:
        return

    st.subheader("Escenarios de producción")
    st.markdown(
        "<p class='dashboard-caption'>Comparación rápida de producción anual bajo distintos niveles de pérdidas del sistema.</p>",
        unsafe_allow_html=True,
    )

    st.caption("Los escenarios comparan niveles de pÃ©rdidas de referencia; no sustituyen la configuraciÃ³n actual del sistema.")

    scenario_cards = []
    for row in scenarios.to_dict("records"):
        scenario_name = str(row["scenario"])
        delta = float(row["delta_vs_recommended_kWh"])
        if abs(delta) < 1e-9:
            delta_label = "Referencia"
            delta_class = "neutral"
        elif delta > 0:
            delta_label = f"+{delta:,.0f} kWh contra recomendado"
            delta_class = "positive"
        else:
            delta_label = f"{delta:,.0f} kWh contra recomendado"
            delta_class = "negative"

        css_name = scenario_name.lower().replace(" ", "-")
        stats = [
            ("Pérdidas", f"{float(row['losses_percent']):.0f} %"),
            ("Por panel", f"{float(row['production_per_panel_kWh']):,.0f} kWh/año"),
            ("Rendimiento", f"{float(row['specific_yield_kWh_kWp']):,.0f} kWh/kWp/año"),
            ("PVOUT diario", f"{float(row['pvout_daily_kWh_kWp_day']):.2f} kWh/kWp/día"),
        ]
        stats_html = "".join(
            (
                '<div class="scenario-stat">'
                f"<span>{html.escape(label)}</span>"
                f"<strong>{html.escape(value)}</strong>"
                "</div>"
            )
            for label, value in stats
        )
        scenario_cards.append(
            (
                f'<div class="scenario-card {html.escape(css_name)}">'
                f"<h3>{html.escape(scenario_name)}</h3>"
                '<p class="label">Producción anual</p>'
                f'<div class="main-value">{float(row["annual_generation_kWh"]):,.0f} kWh/año</div>'
                f'<span class="delta {delta_class}">{html.escape(delta_label)}</span>'
                f'<div class="scenario-stats">{stats_html}</div>'
                f'<p class="interpretation"><strong>Interpretación:</strong> {html.escape(str(row["description"]))}</p>'
                "</div>"
            )
        )

    st.markdown(f"<div class='scenario-grid'>{''.join(scenario_cards)}</div>", unsafe_allow_html=True)

    with st.expander("Cómo se construyen estos escenarios"):
        st.markdown(
            textwrap.dedent(
                """
            <div class="interpretation-grid">
                <div class="interpretation-block">
                    <h4>Base común</h4>
                    <p>Todos los escenarios usan la misma ubicación, fuente solar, paneles, tilt y azimuth.</p>
                </div>
                <div class="interpretation-block">
                    <h4>Variable que cambia</h4>
                    <p>Solo cambia el porcentaje de pérdidas aplicado a la potencia fotovoltaica simulada.</p>
                </div>
                <div class="interpretation-block">
                    <h4>Qué representan las pérdidas</h4>
                    <p>Incluyen suciedad, cableado, inversor, desajustes entre paneles, mantenimiento y condiciones no ideales.</p>
                </div>
                <div class="interpretation-block">
                    <h4>Alcance climático</h4>
                    <p>NASA POWER puede incluir variabilidad climática histórica, pero no reemplaza un estudio técnico en sitio.</p>
                </div>
            </div>
            """
            ).strip(),
            unsafe_allow_html=True,
        )


def render_poa_peak_validation(df: pd.DataFrame) -> None:
    if df.empty or "POA_W_m2" not in df.columns:
        return

    peak_idx = df["POA_W_m2"].idxmax()
    peak = df.loc[peak_idx]
    with st.expander("Validación del pico POA"):
        st.caption(
            "Este valor ayuda a revisar si el pico de irradiancia sobre el panel es razonable. "
            "Los picos instantáneos pueden ser altos, pero no representan la producción anual."
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Fecha y hora", pd.to_datetime(peak["datetime"]).strftime("%Y-%m-%d %H:%M"))
        col2.metric("POA máximo", f"{float(peak['POA_W_m2']):,.0f} W/m²")
        col3.metric("Generación instantánea", f"{float(peak['generation_kW']):.3f} kW")

        values = [
            ("GHI", "GHI_W_m2", "W/m²"),
            ("DNI", "DNI_W_m2", "W/m²"),
            ("DHI", "DHI_W_m2", "W/m²"),
            ("Tilt", None, "°"),
            ("Azimuth", None, "°"),
            ("Zenith solar", "solar_zenith_deg", "°"),
            ("Azimuth solar", "solar_azimuth_deg", "°"),
            ("Temperatura ambiente", "temperature_C", "°C"),
            ("Temperatura de celda", "cell_temperature_C", "°C"),
        ]
        rows = []
        for label, column, unit in values:
            if column is None and label == "Tilt":
                value = float(st.session_state.tilt_deg)
            elif column is None and label == "Azimuth":
                value = float(st.session_state.azimuth_deg)
            elif column in df.columns:
                value = float(peak[column])
            else:
                continue
            rows.append({"Variable": label, "Valor": f"{value:,.2f} {unit}"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if float(peak["POA_W_m2"]) > 1200:
            st.caption(
                "El POA máximo es alto. Puede ocurrir por geometría favorable y componentes directas/difusas elevadas. "
                "Revise la producción anual y los escenarios de pérdidas para una lectura más realista."
            )


def render_stage1_results_step(
    df: pd.DataFrame,
    summary: dict[str, float],
    pv_config: PVSystemConfig,
    simulation_signature: tuple,
) -> None:
    section_header(
        "Resultados",
        "Diagnóstico rápido con los resultados actuales del motor de simulación.",
        icon_name="bolt",
    )
    number_of_panels = max(int(pv_config.number_of_panels), 1)
    production_per_panel = float(summary["total_generation_kwh"]) / number_of_panels
    installed_kwp = float(summary["installed_power_kw"])
    days_in_year = 366 if pd.Timestamp(year=int(pv_config.year), month=12, day=31).dayofyear == 366 else 365
    pvout_daily = float(summary["specific_yield_kwh_kwp"]) / days_in_year if days_in_year else 0.0
    st.session_state.stage1_results_signature = simulation_signature

    st.subheader("Resumen numérico principal")
    render_solar_result_cards(summary, production_per_panel, installed_kwp, pvout_daily)
    render_results_interpretation_expander(df)

    year = int(pv_config.year)
    min_plot_date = pd.to_datetime(f"{year}-01-01").date()
    max_plot_date = pd.to_datetime(f"{year}-12-31").date()
    st.subheader("Gráfica solar diaria")
    st.markdown(
        "<p class='dashboard-caption'>Selecciona un día para revisar el comportamiento de GHI, DNI y DHI usado por el modelo.</p>",
        unsafe_allow_html=True,
    )
    st.session_state.diagnostico_selected_date = _coerce_plot_date_for_year(
        st.session_state.get("diagnostico_selected_date"),
        year,
    )
    selected_date = st.date_input(
        "Día para gráfica solar",
        min_value=min_plot_date,
        max_value=max_plot_date,
        key="diagnostico_selected_date",
        help="La gráfica usa el DataFrame final de simulación, con la fuente solar actualmente usada por el modelo.",
    )
    df_day = df[df["date"] == selected_date]
    if df_day.empty:
        st.warning("No hay datos disponibles para el día seleccionado con la fuente actual.")
    else:
        source_used = str(df_day["irradiance_source"].iloc[0])
        diagnostics = st.session_state.get("external_irradiance_diagnostics", {})
        st.caption(_solar_plot_context_caption(selected_date, source_used, diagnostics if isinstance(diagnostics, dict) else {}))
        st.caption(f"Fuente usada por el modelo para este día: {source_used}.")
        chart_key = f"diagnostico_ghi_dni_dhi_{stage1_signature_digest(simulation_signature)}"
        st.plotly_chart(plot_daily_ghi_dni_dhi(df_day), use_container_width=True, key=chart_key)

    render_realism_loss_scenarios(df, summary, days_in_year)

    info_panel(
        title="¿Quieres calcular tu ahorro con tu consumo eléctrico?",
        body=(
            "Continúa a Consumo y ahorro para agregar demanda, recibo CFE o consumo mensual y estimar cuánto pagarías "
            "con y sin sistema fotovoltaico."
        ),
        icon_name="bolt",
    )
    if st.button("Ir a Consumo y ahorro", key="stage1_go_to_savings", use_container_width=True):
        st.info("Selecciona la pestaña Consumo y ahorro para continuar con demanda, tarifa y costos.")


def render_quick_solar_diagnosis_tab(
    df: pd.DataFrame,
    summary: dict[str, float],
    demand_config: DemandConfig,
    demand_df: pd.DataFrame | None,
) -> None:
    st.markdown("<a id='diagnostico-solar-top'></a>", unsafe_allow_html=True)
    if bool(st.session_state.pop("stage1_scroll_to_top", False)):
        components.html(
            """
            <script>
              const parentWindow = window.parent || window;
              parentWindow.scrollTo({ top: 0, behavior: "smooth" });
            </script>
            """,
            height=0,
        )
    section_header(
        "Diagnóstico solar",
        "Selecciona una ubicación y obtén una estimación rápida del potencial solar, la orientación recomendada y la producción aproximada.",
        icon_name="sun",
    )
    render_stage1_progress()

    active_step = str(st.session_state.get("stage1_step", "ubicacion"))
    context_df = df
    context_summary = summary
    if active_step == "ubicacion":
        render_stage1_location_step()
    elif active_step == "fuente_solar":
        render_stage1_source_step(df)
    elif active_step == "sistema_fv":
        render_stage1_system_step(summary)
    elif active_step == "orientacion":
        render_stage1_orientation_step(summary)
    else:
        stage1_pv_config, stage1_df, stage1_summary, _stage1_irradiance_label, stage1_signature = build_stage1_current_simulation(
            demand_config=demand_config,
            demand_df=demand_df,
        )
        context_df = stage1_df
        context_summary = stage1_summary
        render_stage1_results_step(stage1_df, stage1_summary, stage1_pv_config, stage1_signature)

    st.divider()
    render_stage1_navigation()
    render_stage1_context(context_summary, str(context_df.iloc[0]["irradiance_source"]))


STAGE2_STEPS = [
    ("consumo", "Consumo"),
    ("costo", "Costo express"),
    ("balance", "Balance solar"),
    ("resultados", "Resultados"),
    ("avanzado", "Avanzado"),
]


STAGE2_WIDGET_KEYS = {
    "mode": "_stage2_consumption_input_mode_widget",
    "monthly": "_stage2_monthly_consumption_kwh_widget",
    "annual": "_stage2_annual_consumption_kwh_widget",
    "express_enabled": "_stage2_express_enabled_widget",
    "avg_cost": "_stage2_avg_kwh_cost_mxn_widget",
    "advanced_billing_mode": "_stage2_advanced_billing_mode_widget",
    "receipt_service_type": "_stage2_receipt_service_type_widget",
    "receipt_period_frequency": "_stage2_receipt_period_frequency_widget",
    "receipt_contracted_demand_kw": "_stage2_receipt_contracted_demand_kw_widget",
    "receipt_tariff_label": "_stage2_receipt_tariff_label_widget",
    "receipt_confirmed_tariff": "_stage2_receipt_confirmed_tariff_widget",
    "receipt_residential_tariff": "_stage2_receipt_residential_tariff_widget",
}


STAGE2_RECEIPT_SERVICE_OPTIONS = ["Industrial", "Residencial"]
STAGE2_RECEIPT_PERIOD_FREQUENCY_OPTIONS = ["Mensual", "Bimestral"]
STAGE2_INDUSTRIAL_TARIFF_OPTIONS = ["GDMTO", "GDMTH"]
STAGE2_RESIDENTIAL_TARIFF_OPTIONS = ["1A", "1B", "1C", "1D", "1E", "1F"]


STAGE2_ADVANCED_BILLING_OPTIONS = [
    "Sin análisis formal",
    "GDMTH existente",
    "CFE residencial tipo 1",
    "Tarifa configurable",
]


STAGE2_RESIDENTIAL_TYPE1_BLOCKS = [
    {"Tarifa": "1A", "Básico": "150 kWh", "Intermedio": "150 kWh", "Verano int. 1": "200 kWh", "Verano int. 2": "No aplica", "Límite DAC": "350 kWh"},
    {"Tarifa": "1B", "Básico": "150 kWh", "Intermedio": "250 kWh", "Verano int. 1": "250 kWh", "Verano int. 2": "200 kWh", "Límite DAC": "800 kWh"},
    {"Tarifa": "1C", "Básico": "150 kWh", "Intermedio": "250 kWh", "Verano int. 1": "300 kWh", "Verano int. 2": "300 kWh", "Límite DAC": "1,700 kWh"},
    {"Tarifa": "1D", "Básico": "150 kWh", "Intermedio": "250 kWh", "Verano int. 1": "450 kWh", "Verano int. 2": "400 kWh", "Límite DAC": "2,000 kWh"},
    {"Tarifa": "1E", "Básico": "150 kWh", "Intermedio": "350 kWh", "Verano int. 1": "600 kWh", "Verano int. 2": "600 kWh", "Límite DAC": "5,000 kWh"},
    {"Tarifa": "1F", "Básico": "150 kWh", "Intermedio": "450 kWh", "Verano int. 1": "1,800 kWh", "Verano int. 2": "2,600 kWh", "Límite DAC": "5,000 kWh"},
]


def _stage2_step_ids() -> list[str]:
    return [step_id for step_id, _label in STAGE2_STEPS]


def _set_stage2_step(step_id: str) -> None:
    if step_id in _stage2_step_ids():
        st.session_state.stage2_step = step_id


def _prepare_stage2_widget_state() -> None:
    st.session_state[STAGE2_WIDGET_KEYS["mode"]] = st.session_state.stage2_consumption_input_mode
    st.session_state[STAGE2_WIDGET_KEYS["monthly"]] = st.session_state.stage2_monthly_consumption_kwh
    st.session_state[STAGE2_WIDGET_KEYS["annual"]] = st.session_state.stage2_annual_consumption_kwh
    st.session_state[STAGE2_WIDGET_KEYS["express_enabled"]] = st.session_state.stage2_express_enabled
    st.session_state[STAGE2_WIDGET_KEYS["avg_cost"]] = st.session_state.stage2_avg_kwh_cost_mxn
    st.session_state[STAGE2_WIDGET_KEYS["advanced_billing_mode"]] = st.session_state.stage2_advanced_billing_mode
    st.session_state[STAGE2_WIDGET_KEYS["receipt_service_type"]] = st.session_state.stage2_receipt_service_type
    st.session_state[STAGE2_WIDGET_KEYS["receipt_period_frequency"]] = st.session_state.stage2_receipt_period_frequency
    st.session_state[STAGE2_WIDGET_KEYS["receipt_contracted_demand_kw"]] = st.session_state.stage2_receipt_contracted_demand_kw
    st.session_state[STAGE2_WIDGET_KEYS["receipt_tariff_label"]] = st.session_state.stage2_receipt_tariff_label
    st.session_state[STAGE2_WIDGET_KEYS["receipt_confirmed_tariff"]] = st.session_state.stage2_receipt_confirmed_tariff
    st.session_state[STAGE2_WIDGET_KEYS["receipt_residential_tariff"]] = st.session_state.stage2_receipt_residential_tariff


def _sync_stage2_consumption_mode() -> None:
    st.session_state.stage2_consumption_input_mode = str(st.session_state[STAGE2_WIDGET_KEYS["mode"]])


def _sync_stage2_monthly_consumption() -> None:
    st.session_state.stage2_monthly_consumption_kwh = float(st.session_state[STAGE2_WIDGET_KEYS["monthly"]])


def _sync_stage2_annual_consumption() -> None:
    st.session_state.stage2_annual_consumption_kwh = float(st.session_state[STAGE2_WIDGET_KEYS["annual"]])


def _sync_stage2_express_enabled() -> None:
    st.session_state.stage2_express_enabled = bool(st.session_state[STAGE2_WIDGET_KEYS["express_enabled"]])


def _sync_stage2_avg_cost() -> None:
    st.session_state.stage2_avg_kwh_cost_mxn = float(st.session_state[STAGE2_WIDGET_KEYS["avg_cost"]])


def _sync_stage2_advanced_billing_mode() -> None:
    selected_mode = str(st.session_state[STAGE2_WIDGET_KEYS["advanced_billing_mode"]])
    if selected_mode in STAGE2_ADVANCED_BILLING_OPTIONS:
        st.session_state.stage2_advanced_billing_mode = selected_mode


def _sync_stage2_receipt_service_type() -> None:
    selected_service = str(st.session_state[STAGE2_WIDGET_KEYS["receipt_service_type"]])
    if selected_service in STAGE2_RECEIPT_SERVICE_OPTIONS:
        st.session_state.stage2_receipt_service_type = selected_service


def _sync_stage2_receipt_period_frequency() -> None:
    selected_frequency = str(st.session_state[STAGE2_WIDGET_KEYS["receipt_period_frequency"]])
    if selected_frequency in STAGE2_RECEIPT_PERIOD_FREQUENCY_OPTIONS:
        st.session_state.stage2_receipt_period_frequency = selected_frequency


def _sync_stage2_receipt_contracted_demand() -> None:
    st.session_state.stage2_receipt_contracted_demand_kw = float(
        st.session_state[STAGE2_WIDGET_KEYS["receipt_contracted_demand_kw"]]
    )


def _sync_stage2_receipt_tariff_label() -> None:
    st.session_state.stage2_receipt_tariff_label = str(st.session_state[STAGE2_WIDGET_KEYS["receipt_tariff_label"]])


def _sync_stage2_receipt_confirmed_tariff() -> None:
    selected_tariff = str(st.session_state[STAGE2_WIDGET_KEYS["receipt_confirmed_tariff"]])
    if selected_tariff in STAGE2_INDUSTRIAL_TARIFF_OPTIONS:
        st.session_state.stage2_receipt_confirmed_tariff = selected_tariff


def _sync_stage2_receipt_residential_tariff() -> None:
    selected_tariff = str(st.session_state[STAGE2_WIDGET_KEYS["receipt_residential_tariff"]])
    if selected_tariff in STAGE2_RESIDENTIAL_TARIFF_OPTIONS:
        st.session_state.stage2_receipt_residential_tariff = selected_tariff


def _stage2_annual_consumption_kwh() -> float:
    mode = str(st.session_state.get("stage2_consumption_input_mode", "Mensual"))
    if mode == "Anual":
        return float(st.session_state.get("stage2_annual_consumption_kwh", 0.0))
    return float(st.session_state.get("stage2_monthly_consumption_kwh", 0.0)) * 12.0


def _stage2_express_result(summary: dict[str, float]) -> dict[str, float | None]:
    economic_enabled = bool(st.session_state.get("stage2_express_enabled", False))
    average_cost = float(st.session_state.get("stage2_avg_kwh_cost_mxn", 0.0))
    return compute_express_savings(
        annual_consumption_kwh=_stage2_annual_consumption_kwh(),
        annual_generation_kwh=float(summary["total_generation_kwh"]),
        average_cost_mxn_kwh=average_cost if economic_enabled else None,
        economic_enabled=economic_enabled,
    )


def render_stage2_progress() -> None:
    active_step = str(st.session_state.get("stage2_step", "consumo"))
    if active_step not in _stage2_step_ids():
        active_step = "consumo"
        st.session_state.stage2_step = active_step
    active_index = _stage2_step_ids().index(active_step)

    cols = st.columns(len(STAGE2_STEPS))
    for index, (step_id, label) in enumerate(STAGE2_STEPS):
        if index < active_index:
            status = "Listo"
        elif index == active_index:
            status = "Actual"
        else:
            status = "Pendiente"
        with cols[index]:
            button_type = "primary" if index == active_index else "secondary"
            if st.button(label, key=f"stage2_step_button_{step_id}", use_container_width=True, type=button_type):
                _set_stage2_step(step_id)
                st.rerun()
            st.caption(status)


def render_stage2_navigation() -> None:
    step_ids = _stage2_step_ids()
    active_step = str(st.session_state.get("stage2_step", "consumo"))
    if active_step not in step_ids:
        active_step = "consumo"
    index = step_ids.index(active_step)
    left, _middle, right = st.columns([1, 3, 1])
    if index > 0:
        previous_id, previous_label = STAGE2_STEPS[index - 1]
        if left.button(previous_label, key=f"stage2_previous_{active_step}", use_container_width=True):
            _set_stage2_step(previous_id)
            st.rerun()
    if index < len(STAGE2_STEPS) - 1:
        next_id, next_label = STAGE2_STEPS[index + 1]
        if right.button(next_label, key=f"stage2_next_{active_step}", use_container_width=True):
            _set_stage2_step(next_id)
            st.rerun()


def render_stage2_context(summary: dict[str, float]) -> None:
    express = _stage2_express_result(summary)
    cost_state = "activo" if st.session_state.get("stage2_express_enabled", False) else "inactivo"
    with st.container(border=True):
        st.caption(
            f"Consumo anual: {express['annual_consumption_kWh']:,.0f} kWh | "
            f"Generación FV: {express['annual_generation_kWh']:,.0f} kWh | "
            f"Cobertura express: {express['solar_coverage_pct']:.1f} % | "
            f"Costo express: {cost_state}"
        )


def render_stage2_consumption_step(summary: dict[str, float]) -> None:
    _prepare_stage2_widget_state()
    section_header(
        "Consumo",
        "Define el consumo base para estimar cobertura solar anual.",
        icon_name="bolt",
    )

    mode_col, monthly_col, annual_col = st.columns([0.9, 1.1, 1.1])
    current_mode = str(st.session_state.get(STAGE2_WIDGET_KEYS["mode"], "Mensual"))
    with mode_col:
        selected_mode = st.radio(
            "Entrada de consumo",
            options=["Mensual", "Anual"],
            horizontal=True,
            key=STAGE2_WIDGET_KEYS["mode"],
            on_change=_sync_stage2_consumption_mode,
        )
    st.session_state.stage2_consumption_input_mode = str(selected_mode)
    current_mode = str(selected_mode)
    with monthly_col:
        monthly_consumption = st.number_input(
            "Consumo mensual promedio [kWh]",
            min_value=0.0,
            step=100.0,
            key=STAGE2_WIDGET_KEYS["monthly"],
            on_change=_sync_stage2_monthly_consumption,
            disabled=current_mode != "Mensual",
        )
    with annual_col:
        annual_consumption = st.number_input(
            "Consumo anual estimado [kWh]",
            min_value=0.0,
            step=1000.0,
            key=STAGE2_WIDGET_KEYS["annual"],
            on_change=_sync_stage2_annual_consumption,
            disabled=current_mode != "Anual",
        )
    st.session_state.stage2_monthly_consumption_kwh = float(monthly_consumption)
    st.session_state.stage2_annual_consumption_kwh = float(annual_consumption)

    express = _stage2_express_result(summary)
    col1, col2, col3 = st.columns(3)
    col1.metric("Consumo anual estimado", f"{express['annual_consumption_kWh']:,.0f} kWh")
    col2.metric("Generación FV disponible", f"{express['annual_generation_kWh']:,.0f} kWh")
    col3.metric("Estado", "Listo" if express["annual_consumption_kWh"] > 0 else "Pendiente")


def render_stage2_cost_step(summary: dict[str, float]) -> None:
    _prepare_stage2_widget_state()
    section_header(
        "Costo express",
        "Activa el cálculo monetario simple si tienes un costo promedio por kWh.",
        icon_name="table",
    )

    toggle_col, cost_col, preview_col = st.columns([1, 1, 1.2])
    with toggle_col:
        express_enabled = st.checkbox(
            "Calcular ahorro express",
            key=STAGE2_WIDGET_KEYS["express_enabled"],
            on_change=_sync_stage2_express_enabled,
        )
    st.session_state.stage2_express_enabled = bool(express_enabled)
    with cost_col:
        avg_cost = st.number_input(
            "Costo promedio [MXN/kWh]",
            min_value=0.0,
            step=0.10,
            format="%.2f",
            key=STAGE2_WIDGET_KEYS["avg_cost"],
            on_change=_sync_stage2_avg_cost,
            disabled=not express_enabled,
        )
    st.session_state.stage2_avg_kwh_cost_mxn = float(avg_cost)
    express = _stage2_express_result(summary)
    with preview_col:
        if st.session_state.stage2_express_enabled and st.session_state.stage2_avg_kwh_cost_mxn > 0:
            st.metric("Ahorro anual preliminar", f"${express['annual_savings'] or 0.0:,.0f} MXN")
        elif st.session_state.stage2_express_enabled:
            st.metric("Costo promedio", "Pendiente")
        else:
            st.metric("Cálculo monetario", "Inactivo")

    st.caption("Si no activas este paso, el flujo continúa solo con balance energético.")


def render_stage2_balance_step(summary: dict[str, float]) -> None:
    section_header(
        "Balance solar",
        "Comparación anual simplificada entre consumo y generación FV actual.",
        icon_name="chart",
    )

    express = _stage2_express_result(summary)
    if express["annual_consumption_kWh"] <= 0:
        st.warning("Ingresa un consumo válido para calcular el balance solar.")
    col1, col2, col3 = st.columns(3)
    col1.metric("Energía cubierta por FV", f"{express['self_consumed_kWh']:,.0f} kWh")
    col2.metric("Energía restante de red", f"{express['grid_energy_kWh']:,.0f} kWh")
    col3.metric("Excedente estimado", f"{express['exported_kWh']:,.0f} kWh")

    col4, col5, col6 = st.columns(3)
    col4.metric("Consumo anual", f"{express['annual_consumption_kWh']:,.0f} kWh")
    col5.metric("Generación FV anual", f"{express['annual_generation_kWh']:,.0f} kWh")
    col6.metric("Cobertura solar", f"{express['solar_coverage_pct']:.1f} %")


def render_stage2_results_step(summary: dict[str, float]) -> None:
    section_header(
        "Resultados",
        "Resumen final del modo rápido de consumo y ahorro express.",
        icon_name="bolt",
    )

    express = _stage2_express_result(summary)
    if express["annual_consumption_kWh"] <= 0:
        st.warning("Ingresa un consumo válido para mostrar resultados de balance.")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Consumo anual", f"{express['annual_consumption_kWh']:,.0f} kWh")
    with col2:
        metric_card("Generación FV anual", f"{express['annual_generation_kWh']:,.0f} kWh")
    with col3:
        metric_card("Cobertura solar", f"{express['solar_coverage_pct']:.1f} %")
    with col4:
        metric_card("Energía de red", f"{express['grid_energy_kWh']:,.0f} kWh")

    if st.session_state.stage2_express_enabled and st.session_state.stage2_avg_kwh_cost_mxn > 0 and express["annual_savings"] is not None:
        cost_col1, cost_col2, cost_col3 = st.columns(3)
        with cost_col1:
            metric_card("Costo anual actual", f"${express['current_annual_cost']:,.0f} MXN")
        with cost_col2:
            metric_card("Costo anual con FV", f"${express['annual_cost_with_pv']:,.0f} MXN")
        with cost_col3:
            metric_card("Ahorro anual express", f"${express['annual_savings']:,.0f} MXN", f"{express['savings_pct']:.1f} %")
    elif st.session_state.stage2_express_enabled:
        st.info("El cálculo express está activo, pero falta un costo promedio por kWh válido.")
    else:
        st.info("El cálculo monetario express está desactivado. Los resultados muestran solo balance energético.")

    with st.expander("Cómo interpretar estos resultados"):
        st.markdown(
            """
            - Es una estimación anual simplificada y no sustituye el balance horario o quinceminutal.
            - La cobertura solar compara generación FV anual contra consumo anual estimado.
            - El ahorro express usa solo el costo promedio por kWh ingresado.
            - El análisis tarifario formal se conserva separado en Avanzado.
            """
        )


def build_default_receipt_periods(service_type: str) -> pd.DataFrame:
    if service_type == "Industrial":
        rows = [
            {
                "Periodo": f"Periodo {index}",
                "Consumo total kWh": 0.0,
                "Demanda kW": 0.0,
                "Factor de potencia %": 0.0,
                "Precio medio MXN/kWh": 0.0,
            }
            for index in range(1, 4)
        ]
    else:
        rows = [
            {
                "Periodo": f"Periodo {index}",
                "Consumo kWh": 0.0,
                "Precio medio MXN/kWh": 0.0,
            }
            for index in range(1, 4)
        ]
    return _coerce_receipt_dataframe(pd.DataFrame(rows), service_type)


def _receipt_columns_for_service(service_type: str) -> list[str]:
    if service_type == "Industrial":
        return ["Periodo", "Consumo total kWh", "Demanda kW", "Factor de potencia %", "Precio medio MXN/kWh"]
    return ["Periodo", "Consumo kWh", "Precio medio MXN/kWh"]


def _coerce_receipt_dataframe(raw_df: pd.DataFrame, service_type: str) -> pd.DataFrame:
    df = raw_df.copy() if isinstance(raw_df, pd.DataFrame) else pd.DataFrame()
    if service_type == "Industrial" and "Consumo total kWh" not in df.columns and "Consumo kWh" in df.columns:
        df["Consumo total kWh"] = df["Consumo kWh"]
    if service_type == "Residencial" and "Consumo kWh" not in df.columns and "Consumo total kWh" in df.columns:
        df["Consumo kWh"] = df["Consumo total kWh"]

    columns = _receipt_columns_for_service(service_type)
    row_count = len(df)
    coerced = pd.DataFrame(index=range(row_count), columns=columns)
    for column in columns:
        if column == "Periodo":
            if column in df.columns:
                coerced[column] = df[column].fillna("").astype(str)
            else:
                coerced[column] = [f"Periodo {index}" for index in range(1, row_count + 1)]
        else:
            if column in df.columns:
                coerced[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0).astype(float)
            else:
                coerced[column] = 0.0
            coerced[column] = coerced[column].astype(float)
    return coerced.reset_index(drop=True)


def _receipt_rows_dataframe(service_type: str) -> pd.DataFrame:
    existing_df = st.session_state.get("stage2_receipt_periods_df")
    if isinstance(existing_df, pd.DataFrame):
        receipt_df = existing_df
    else:
        legacy_rows = st.session_state.get("stage2_receipt_period_rows", [])
        if isinstance(legacy_rows, list) and legacy_rows:
            receipt_df = pd.DataFrame(legacy_rows)
        elif not bool(st.session_state.get("stage2_receipt_periods_initialized", False)):
            receipt_df = build_default_receipt_periods(service_type)
            st.session_state.stage2_receipt_periods_initialized = True
        else:
            receipt_df = pd.DataFrame(columns=_receipt_columns_for_service(service_type))

    receipt_df = _coerce_receipt_dataframe(receipt_df, service_type)
    st.session_state.stage2_receipt_periods_df = receipt_df
    return receipt_df.copy()


def _store_receipt_periods_df(edited_rows: pd.DataFrame, service_type: str) -> pd.DataFrame:
    receipt_df = _coerce_receipt_dataframe(edited_rows, service_type)
    st.session_state.stage2_receipt_periods_df = receipt_df
    st.session_state.stage2_receipt_periods_initialized = True
    return receipt_df


def _apply_data_editor_delta(base_df: pd.DataFrame, editor_state: dict[str, object]) -> pd.DataFrame:
    result = base_df.copy()
    deleted_rows = editor_state.get("deleted_rows", [])
    if isinstance(deleted_rows, list) and deleted_rows:
        delete_indexes = sorted((int(index) for index in deleted_rows), reverse=True)
        for index in delete_indexes:
            if 0 <= index < len(result):
                result = result.drop(result.index[index])
        result = result.reset_index(drop=True)

    edited_rows = editor_state.get("edited_rows", {})
    if isinstance(edited_rows, dict):
        for raw_index, changes in edited_rows.items():
            if not isinstance(changes, dict):
                continue
            index = int(raw_index)
            if 0 <= index < len(result):
                for column, value in changes.items():
                    result.loc[index, column] = value

    added_rows = editor_state.get("added_rows", [])
    if isinstance(added_rows, list) and added_rows:
        result = pd.concat([result, pd.DataFrame(added_rows)], ignore_index=True)
    return result


def _sync_stage2_receipt_periods_editor(service_type: str, editor_key: str) -> None:
    editor_state = st.session_state.get(editor_key)
    if isinstance(editor_state, pd.DataFrame):
        edited_df = editor_state
    elif isinstance(editor_state, dict):
        base_df = st.session_state.get("stage2_receipt_periods_df")
        if not isinstance(base_df, pd.DataFrame):
            base_df = pd.DataFrame(columns=_receipt_columns_for_service(service_type))
        edited_df = _apply_data_editor_delta(base_df, editor_state)
    else:
        return
    _store_receipt_periods_df(edited_df, service_type)


def _receipt_column_config(service_type: str) -> dict[str, object]:
    config: dict[str, object] = {
        "Periodo": st.column_config.TextColumn("Periodo", width="medium"),
        "Precio medio MXN/kWh": st.column_config.NumberColumn("Precio medio MXN/kWh", min_value=0.0, step=0.0001, format="%.4f"),
    }
    if service_type == "Industrial":
        config.update(
            {
                "Consumo total kWh": st.column_config.NumberColumn("Consumo total kWh", min_value=0.0, step=0.01, format="%.2f"),
                "Demanda kW": st.column_config.NumberColumn("Demanda kW", min_value=0.0, step=0.01, format="%.2f"),
                "Factor de potencia %": st.column_config.NumberColumn("Factor de potencia %", min_value=0.0, max_value=100.0, step=0.01, format="%.2f"),
            }
        )
    else:
        config["Consumo kWh"] = st.column_config.NumberColumn("Consumo kWh", min_value=0.0, step=0.01, format="%.2f")
    return config


def render_stage2_receipt_results(receipt_result: dict[str, object]) -> None:
    if int(receipt_result["captured_periods"]) <= 0:
        st.warning("Captura al menos un periodo con consumo y precio medio para mostrar el análisis.")
        return

    st.caption(
        f"{receipt_result['analysis_type']} | "
        f"Periodos capturados: {receipt_result['captured_periods']} de {receipt_result['periods_per_year']} | "
        f"Precio medio ponderado: ${receipt_result['weighted_average_price_mxn_kwh']:,.2f} MXN/kWh"
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Consumo anual", f"{receipt_result['annual_consumption_kWh']:,.0f} kWh")
    with col2:
        metric_card("Costo sin FV", f"${receipt_result['annual_cost_without_pv_mxn']:,.0f} MXN")
    with col3:
        metric_card("Generación FV", f"{receipt_result['annual_generation_kWh']:,.0f} kWh")
    with col4:
        metric_card("Cobertura FV", f"{receipt_result['solar_coverage_percent']:.1f} %")

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        metric_card("Energía cubierta", f"{receipt_result['self_consumed_kWh']:,.0f} kWh")
    with col6:
        metric_card("Energía de red", f"{receipt_result['grid_energy_kWh']:,.0f} kWh")
    with col7:
        metric_card("Costo con FV", f"${receipt_result['annual_cost_with_pv_mxn']:,.0f} MXN")
    with col8:
        metric_card("Ahorro estimado", f"${receipt_result['annual_savings_mxn']:,.0f} MXN", f"{receipt_result['annual_savings_percent']:.1f} %")

    st.plotly_chart(
        plot_receipt_period_savings(receipt_result),
        use_container_width=True,
        key="stage2_receipt_period_savings_chart",
    )

    with st.container(border=True):
        st.markdown("**Costo por periodo**")
        period_results = pd.DataFrame(receipt_result["period_results"])
        if not period_results.empty:
            st.dataframe(period_results, use_container_width=True, hide_index=True)


def render_stage2_residential_type1_view() -> None:
    st.info("Vista informativa para identificar límites de bloques y clasificación de tarifa. No contiene precios por kWh ni se usa como fuente de precios.")
    st.dataframe(pd.DataFrame(STAGE2_RESIDENTIAL_TYPE1_BLOCKS), use_container_width=True, hide_index=True)
    with st.container(border=True):
        st.markdown("**Uso en análisis con datos de recibo**")
        st.markdown(
            """
            - Selecciona 1A, 1B, 1C, 1D, 1E o 1F para clasificar el tipo residencial.
            - Captura consumo kWh y precio medio MXN/kWh desde el recibo mensual o bimestral.
            - Los precios varían por zona, periodo y condiciones del recibo.
            """
        )


def render_stage2_advanced_step(df: pd.DataFrame, summary: dict[str, float], monthly_tariff: pd.DataFrame, annual_tariff: dict[str, float]) -> None:
    _prepare_stage2_widget_state()
    section_header(
        "Análisis con datos de recibo",
        "Captura datos resumidos del recibo para estimar consumo, costo histórico o proyectado, y compararlo contra la generación fotovoltaica actual.",
        icon_name="table",
    )

    service_col, frequency_col = st.columns([1, 1])
    with service_col:
        service_type = st.selectbox(
            "Tipo de servicio",
            options=STAGE2_RECEIPT_SERVICE_OPTIONS,
            key=STAGE2_WIDGET_KEYS["receipt_service_type"],
            on_change=_sync_stage2_receipt_service_type,
        )
    st.session_state.stage2_receipt_service_type = str(service_type)
    with frequency_col:
        period_frequency = st.selectbox(
            "Periodicidad del recibo",
            options=STAGE2_RECEIPT_PERIOD_FREQUENCY_OPTIONS,
            key=STAGE2_WIDGET_KEYS["receipt_period_frequency"],
            on_change=_sync_stage2_receipt_period_frequency,
        )
    st.session_state.stage2_receipt_period_frequency = str(period_frequency)

    if service_type == "Industrial":
        demand_col, suggested_col, confirmed_col = st.columns([1, 1, 1])
        with demand_col:
            contracted_demand = st.number_input(
                "Demanda contratada kW",
                min_value=0.0,
                step=5.0,
                key=STAGE2_WIDGET_KEYS["receipt_contracted_demand_kw"],
                on_change=_sync_stage2_receipt_contracted_demand,
            )
        st.session_state.stage2_receipt_contracted_demand_kw = float(contracted_demand)
        suggested_tariff = suggest_industrial_tariff_family(float(contracted_demand))
        with suggested_col:
            metric_card("Tarifa sugerida", suggested_tariff, "GDMTO < 100 kW, GDMTH >= 100 kW")
        confirmed_tariff = str(st.session_state.get("stage2_receipt_confirmed_tariff", suggested_tariff))
        if confirmed_tariff not in STAGE2_INDUSTRIAL_TARIFF_OPTIONS:
            confirmed_tariff = suggested_tariff
            st.session_state.stage2_receipt_confirmed_tariff = confirmed_tariff
            st.session_state[STAGE2_WIDGET_KEYS["receipt_confirmed_tariff"]] = confirmed_tariff
        with confirmed_col:
            selected_tariff = st.selectbox(
                "Tarifa confirmada",
                options=STAGE2_INDUSTRIAL_TARIFF_OPTIONS,
                index=STAGE2_INDUSTRIAL_TARIFF_OPTIONS.index(confirmed_tariff),
                key=STAGE2_WIDGET_KEYS["receipt_confirmed_tariff"],
                on_change=_sync_stage2_receipt_confirmed_tariff,
            )
        st.session_state.stage2_receipt_confirmed_tariff = str(selected_tariff)
        st.text_input(
            "Tarifa que aparece en el recibo (opcional)",
            key=STAGE2_WIDGET_KEYS["receipt_tariff_label"],
            on_change=_sync_stage2_receipt_tariff_label,
        )
        st.session_state.stage2_receipt_tariff_label = str(st.session_state.get(STAGE2_WIDGET_KEYS["receipt_tariff_label"], ""))
    else:
        residential_col, note_col = st.columns([1, 2])
        with residential_col:
            selected_residential_tariff = st.selectbox(
                "Tarifa residencial",
                options=STAGE2_RESIDENTIAL_TARIFF_OPTIONS,
                key=STAGE2_WIDGET_KEYS["receipt_residential_tariff"],
                on_change=_sync_stage2_receipt_residential_tariff,
            )
        st.session_state.stage2_receipt_residential_tariff = str(selected_residential_tariff)
        with note_col:
            st.info("El precio se captura como precio medio MXN/kWh del recibo. La tabla de bloques solo clasifica límites.")
        with st.expander("Bloques residenciales tipo 1", expanded=False):
            render_stage2_residential_type1_view()

    st.subheader("Periodos del recibo")
    st.caption("Las columnas cambian según el tipo de servicio. Los datos compatibles se conservan al cambiar entre Industrial y Residencial.")
    receipt_df = _receipt_rows_dataframe(str(service_type))
    if st.button("Restablecer tabla para este tipo de servicio", key=f"stage2_reset_receipt_periods_{service_type}"):
        receipt_df = build_default_receipt_periods(str(service_type))
        st.session_state.stage2_receipt_periods_df = receipt_df
        st.session_state.stage2_receipt_periods_initialized = True
        st.rerun()
    editor_key = f"stage2_receipt_periods_editor_{service_type}"
    edited_receipt_df = st.data_editor(
        receipt_df,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config=_receipt_column_config(str(service_type)),
        key=editor_key,
        on_change=_sync_stage2_receipt_periods_editor,
        args=(str(service_type), editor_key),
    )
    receipt_periods_df = _store_receipt_periods_df(edited_receipt_df, str(service_type))
    receipt_result = compute_receipt_based_savings(
        receipt_periods_df.to_dict("records"),
        annual_generation_kwh=float(summary["total_generation_kwh"]),
        period_frequency=str(period_frequency),
    )
    render_stage2_receipt_results(receipt_result)

    with st.expander("Balance detallado con perfil temporal", expanded=False):
        st.markdown(
            """
            Si el usuario carga demanda quinceminutal, el análisis puede estimar mejor autoconsumo, energía exportada, energía de red y coincidencia temporal entre demanda y generación FV.

            Si solo se capturan datos mensuales o bimestrales del recibo, el balance se mantiene como análisis mensual o anual resumido.
            """
        )


def render_stage2_savings_wizard(df: pd.DataFrame, summary: dict[str, float], monthly_tariff: pd.DataFrame, annual_tariff: dict[str, float]) -> None:
    section_header(
        "Consumo y ahorro",
        "Ingresa tu consumo eléctrico para estimar cobertura solar, energía restante de red y ahorro express con el sistema fotovoltaico actual.",
        icon_name="bolt",
    )
    render_stage2_progress()
    st.divider()

    active_step = str(st.session_state.get("stage2_step", "consumo"))
    if active_step == "consumo":
        render_stage2_consumption_step(summary)
    elif active_step == "costo":
        render_stage2_cost_step(summary)
    elif active_step == "balance":
        render_stage2_balance_step(summary)
    elif active_step == "resultados":
        render_stage2_results_step(summary)
    else:
        render_stage2_advanced_step(df, summary, monthly_tariff, annual_tariff)

    st.divider()
    render_stage2_navigation()
    render_stage2_context(summary)

STAGE3_STEPS = [
    ("carga", "Carga crítica"),
    ("historial", "Historial"),
    ("bess", "Sistema BESS"),
    ("resultados", "Resultados"),
]


STAGE3_WIDGET_KEYS = {
    "load_value": "_stage3_load_value_widget",
    "load_unit": "_stage3_load_unit_widget",
    "power_factor": "_stage3_power_factor_widget",
    "backup_hours": "_stage3_backup_hours_widget",
    "outage_frequency": "_stage3_outage_frequency_widget",
    "outage_frequency_unit": "_stage3_outage_frequency_unit_widget",
    "average_outage_duration_h": "_stage3_average_outage_duration_h_widget",
    "typical_max_outage_duration_h": "_stage3_typical_max_outage_duration_h_widget",
    "battery_technology": "_stage3_battery_technology_widget",
    "battery_capacity_kwh": "_stage3_battery_capacity_kwh_widget",
    "battery_max_power_kw": "_stage3_battery_max_power_kw_widget",
    "depth_of_discharge": "_stage3_depth_of_discharge_widget",
    "system_efficiency": "_stage3_system_efficiency_widget",
    "safety_margin": "_stage3_safety_margin_widget",
    "life_cycles": "_stage3_life_cycles_widget",
}


def _stage3_step_ids() -> list[str]:
    return [step_id for step_id, _label in STAGE3_STEPS]


def _set_stage3_step(step_id: str) -> None:
    if step_id in _stage3_step_ids():
        st.session_state.stage3_step = step_id


def _prepare_stage3_widget_state() -> None:
    st.session_state[STAGE3_WIDGET_KEYS["load_value"]] = st.session_state.stage3_load_value
    st.session_state[STAGE3_WIDGET_KEYS["load_unit"]] = st.session_state.stage3_load_unit
    st.session_state[STAGE3_WIDGET_KEYS["power_factor"]] = st.session_state.stage3_power_factor
    st.session_state[STAGE3_WIDGET_KEYS["backup_hours"]] = st.session_state.stage3_backup_hours
    st.session_state[STAGE3_WIDGET_KEYS["outage_frequency"]] = st.session_state.stage3_outage_frequency
    st.session_state[STAGE3_WIDGET_KEYS["outage_frequency_unit"]] = st.session_state.stage3_outage_frequency_unit
    st.session_state[STAGE3_WIDGET_KEYS["average_outage_duration_h"]] = st.session_state.stage3_average_outage_duration_h
    st.session_state[STAGE3_WIDGET_KEYS["typical_max_outage_duration_h"]] = st.session_state.stage3_typical_max_outage_duration_h
    st.session_state[STAGE3_WIDGET_KEYS["battery_technology"]] = st.session_state.stage3_battery_technology
    st.session_state[STAGE3_WIDGET_KEYS["battery_capacity_kwh"]] = st.session_state.stage3_battery_capacity_kwh
    st.session_state[STAGE3_WIDGET_KEYS["battery_max_power_kw"]] = st.session_state.stage3_battery_max_power_kw
    st.session_state[STAGE3_WIDGET_KEYS["depth_of_discharge"]] = st.session_state.stage3_depth_of_discharge
    st.session_state[STAGE3_WIDGET_KEYS["system_efficiency"]] = st.session_state.stage3_system_efficiency
    st.session_state[STAGE3_WIDGET_KEYS["safety_margin"]] = st.session_state.stage3_safety_margin
    st.session_state[STAGE3_WIDGET_KEYS["life_cycles"]] = st.session_state.stage3_life_cycles


def _sync_stage3_load_value() -> None:
    st.session_state.stage3_load_value = float(st.session_state[STAGE3_WIDGET_KEYS["load_value"]])


def _sync_stage3_load_unit() -> None:
    st.session_state.stage3_load_unit = str(st.session_state[STAGE3_WIDGET_KEYS["load_unit"]])


def _sync_stage3_power_factor() -> None:
    st.session_state.stage3_power_factor = float(st.session_state[STAGE3_WIDGET_KEYS["power_factor"]])


def _sync_stage3_backup_hours() -> None:
    st.session_state.stage3_backup_hours = float(st.session_state[STAGE3_WIDGET_KEYS["backup_hours"]])


def _sync_stage3_outage_frequency() -> None:
    st.session_state.stage3_outage_frequency = float(st.session_state[STAGE3_WIDGET_KEYS["outage_frequency"]])


def _sync_stage3_outage_frequency_unit() -> None:
    st.session_state.stage3_outage_frequency_unit = str(st.session_state[STAGE3_WIDGET_KEYS["outage_frequency_unit"]])


def _sync_stage3_average_outage_duration() -> None:
    st.session_state.stage3_average_outage_duration_h = float(st.session_state[STAGE3_WIDGET_KEYS["average_outage_duration_h"]])


def _sync_stage3_typical_max_outage_duration() -> None:
    st.session_state.stage3_typical_max_outage_duration_h = float(st.session_state[STAGE3_WIDGET_KEYS["typical_max_outage_duration_h"]])


def _sync_stage3_battery_technology() -> None:
    st.session_state.stage3_battery_technology = str(st.session_state[STAGE3_WIDGET_KEYS["battery_technology"]]).strip() or "LiFePO4"


def _sync_stage3_battery_capacity() -> None:
    st.session_state.stage3_battery_capacity_kwh = float(st.session_state[STAGE3_WIDGET_KEYS["battery_capacity_kwh"]])


def _sync_stage3_battery_max_power() -> None:
    st.session_state.stage3_battery_max_power_kw = float(st.session_state[STAGE3_WIDGET_KEYS["battery_max_power_kw"]])


def _sync_stage3_depth_of_discharge() -> None:
    st.session_state.stage3_depth_of_discharge = float(st.session_state[STAGE3_WIDGET_KEYS["depth_of_discharge"]])


def _sync_stage3_system_efficiency() -> None:
    st.session_state.stage3_system_efficiency = float(st.session_state[STAGE3_WIDGET_KEYS["system_efficiency"]])


def _sync_stage3_safety_margin() -> None:
    st.session_state.stage3_safety_margin = float(st.session_state[STAGE3_WIDGET_KEYS["safety_margin"]])


def _sync_stage3_life_cycles() -> None:
    st.session_state.stage3_life_cycles = float(st.session_state[STAGE3_WIDGET_KEYS["life_cycles"]])


def _clear_stage3_result_state() -> None:
    stage3_result_defaults = {
        "stage3_result_is_complete": False,
        "stage3_result_critical_load_kw": 0.0,
        "stage3_result_backup_hours": 0.0,
        "stage3_result_required_usable_kwh": 0.0,
        "stage3_result_required_nominal_kwh": 0.0,
        "stage3_result_required_bess_capacity_kwh": 0.0,
        "stage3_result_installed_backup_hours": 0.0,
        "stage3_result_annual_outage_events": 0.0,
        "stage3_result_annual_outage_hours": 0.0,
        "stage3_result_annual_backed_hours": 0.0,
        "stage3_result_annual_backed_energy_kwh": 0.0,
        "stage3_result_uncovered_average_outage_hours": 0.0,
        "stage3_result_annual_uncovered_hours": 0.0,
        "stage3_result_equivalent_cycles_per_year": 0.0,
        "stage3_result_estimated_life_years_by_cycles": None,
        "stage3_result_long_outage_uncovered_hours": 0.0,
        "stage3_result_long_outage_covered": False,
        "stage3_result_recommended_battery_count": 0.0,
        "stage3_result_recommended_batteries": 0.0,
        "stage3_result_total_installed_capacity_kwh": 0.0,
        "stage3_result_usable_installed_energy_kwh": 0.0,
    }
    for key, value in stage3_result_defaults.items():
        st.session_state[key] = value


def _stage3_backup_result() -> tuple[dict[str, float | bool | None] | None, str | None]:
    try:
        result = calculate_bess_backup(
            critical_load_value=float(st.session_state.get("stage3_load_value", 0.0)),
            load_unit=str(st.session_state.get("stage3_load_unit", "kW")),
            power_factor=float(st.session_state.get("stage3_power_factor", 0.90)),
            backup_hours=float(st.session_state.get("stage3_backup_hours", 0.0)),
            outage_frequency=float(st.session_state.get("stage3_outage_frequency", 0.0)),
            outage_frequency_unit=str(st.session_state.get("stage3_outage_frequency_unit", "Por mes")),
            average_outage_duration_h=float(st.session_state.get("stage3_average_outage_duration_h", 0.0)),
            typical_max_outage_duration_h=float(st.session_state.get("stage3_typical_max_outage_duration_h", 0.0)),
            battery_capacity_kwh=float(st.session_state.get("stage3_battery_capacity_kwh", 5.0)),
            battery_max_power_kw=float(st.session_state.get("stage3_battery_max_power_kw", 5.0)),
            depth_of_discharge=float(st.session_state.get("stage3_depth_of_discharge", 0.80)),
            system_efficiency=float(st.session_state.get("stage3_system_efficiency", 0.90)),
            safety_margin=float(st.session_state.get("stage3_safety_margin", 0.15)),
            life_cycles=float(st.session_state.get("stage3_life_cycles", 4500.0)),
        )
    except ValueError as exc:
        _clear_stage3_result_state()
        return None, str(exc)

    st.session_state.stage3_result_critical_load_kw = float(result["critical_load_kw"])
    st.session_state.stage3_result_backup_hours = float(result["backup_hours"])
    st.session_state.stage3_result_required_usable_kwh = float(result["usable_energy_required_kwh"])
    st.session_state.stage3_result_required_nominal_kwh = float(result["nominal_bess_capacity_kwh"])
    st.session_state.stage3_result_required_bess_capacity_kwh = float(result["nominal_bess_capacity_kwh"])
    st.session_state.stage3_result_installed_backup_hours = float(result["installed_backup_hours"])
    st.session_state.stage3_result_annual_outage_events = float(result["annual_outage_events"])
    st.session_state.stage3_result_annual_outage_hours = float(result["annual_outage_hours"])
    st.session_state.stage3_result_annual_backed_hours = float(result["annual_backed_hours"])
    st.session_state.stage3_result_annual_backed_energy_kwh = float(result["annual_backed_energy_kwh"])
    st.session_state.stage3_result_uncovered_average_outage_hours = float(result["uncovered_average_outage_hours"])
    st.session_state.stage3_result_annual_uncovered_hours = float(result["annual_uncovered_hours"])
    st.session_state.stage3_result_equivalent_cycles_per_year = float(result["equivalent_cycles_per_year"])
    st.session_state.stage3_result_estimated_life_years_by_cycles = result["estimated_life_years_by_cycles"]
    st.session_state.stage3_result_long_outage_uncovered_hours = float(result["long_outage_uncovered_hours"])
    st.session_state.stage3_result_long_outage_covered = bool(result["long_outage_covered"])
    st.session_state.stage3_result_recommended_battery_count = float(result["recommended_battery_count"])
    st.session_state.stage3_result_recommended_batteries = float(result["recommended_battery_count"])
    st.session_state.stage3_result_total_installed_capacity_kwh = float(result["total_installed_capacity_kwh"])
    st.session_state.stage3_result_usable_installed_energy_kwh = float(result["usable_installed_energy_kwh"])
    st.session_state.stage3_result_is_complete = (
        result["critical_load_kw"] > 0.0
        and result["backup_hours"] > 0.0
        and result["nominal_bess_capacity_kwh"] > 0.0
    )
    return result, None


def render_stage3_progress() -> None:
    active_step = str(st.session_state.get("stage3_step", "carga"))
    if active_step not in _stage3_step_ids():
        active_step = "carga"
        st.session_state.stage3_step = active_step
    active_index = _stage3_step_ids().index(active_step)

    cols = st.columns(len(STAGE3_STEPS))
    for index, (step_id, label) in enumerate(STAGE3_STEPS):
        if index < active_index:
            status = "Listo"
        elif index == active_index:
            status = "Actual"
        else:
            status = "Pendiente"
        with cols[index]:
            button_type = "primary" if index == active_index else "secondary"
            if st.button(label, key=f"stage3_step_button_{step_id}", use_container_width=True, type=button_type):
                _set_stage3_step(step_id)
                st.rerun()
            st.caption(status)


def render_stage3_navigation() -> None:
    step_ids = _stage3_step_ids()
    active_step = str(st.session_state.get("stage3_step", "carga"))
    if active_step not in step_ids:
        active_step = "carga"
    index = step_ids.index(active_step)
    left, _middle, right = st.columns([1, 3, 1])
    if index > 0:
        previous_id, previous_label = STAGE3_STEPS[index - 1]
        if left.button(previous_label, key=f"stage3_previous_{active_step}", use_container_width=True):
            _set_stage3_step(previous_id)
            st.rerun()
    if index < len(STAGE3_STEPS) - 1:
        next_id, next_label = STAGE3_STEPS[index + 1]
        if right.button(next_label, key=f"stage3_next_{active_step}", use_container_width=True):
            _set_stage3_step(next_id)
            st.rerun()


def render_stage3_context(result: dict[str, float | bool | None] | None) -> None:
    if result is None:
        context = "Respaldo pendiente: revisa los valores de carga, horas y supuestos."
    else:
        status = "listo" if st.session_state.get("stage3_result_is_complete", False) else "pendiente"
        context = (
            f"Carga crítica: {result['critical_load_kw']:,.2f} kW | "
            f"Horas: {result['backup_hours']:,.1f} h | "
            f"BESS nominal: {result['nominal_bess_capacity_kwh']:,.1f} kWh | "
            f"Estado: {status}"
        )
    with st.container(border=True):
        st.caption(context)


def render_stage3_load_step(result: dict[str, float | bool | None] | None, error: str | None) -> None:
    _prepare_stage3_widget_state()
    section_header(
        "Carga crítica",
        "Define la potencia que el sistema de respaldo debe sostener.",
        icon_name="bolt",
    )

    unit_col, load_col, pf_col = st.columns([0.8, 1.1, 1.1])
    with unit_col:
        load_unit = st.radio(
            "Unidad",
            options=["kW", "kVA"],
            horizontal=True,
            key=STAGE3_WIDGET_KEYS["load_unit"],
            on_change=_sync_stage3_load_unit,
        )
    st.session_state.stage3_load_unit = str(load_unit)
    with load_col:
        load_value = st.number_input(
            "Potencia de carga crítica",
            min_value=0.0,
            step=1.0,
            format="%.2f",
            key=STAGE3_WIDGET_KEYS["load_value"],
            on_change=_sync_stage3_load_value,
        )
    st.session_state.stage3_load_value = float(load_value)
    with pf_col:
        power_factor = st.number_input(
            "Factor de potencia",
            min_value=0.01,
            max_value=1.0,
            step=0.01,
            format="%.2f",
            disabled=str(load_unit) != "kVA",
            key=STAGE3_WIDGET_KEYS["power_factor"],
            on_change=_sync_stage3_power_factor,
        )
    st.session_state.stage3_power_factor = float(power_factor)

    if error:
        st.warning("Revisa los valores de carga crítica.")
    elif result is not None:
        col1, col2, col3 = st.columns(3)
        col1.metric("Potencia considerada", f"{result['critical_load_kw']:,.2f} kW")
        col2.metric("Unidad de entrada", str(load_unit))
        col3.metric("Estado", "Listo" if result["critical_load_kw"] > 0 else "Pendiente")


def render_stage3_history_step(result: dict[str, float | bool | None] | None, error: str | None) -> None:
    _prepare_stage3_widget_state()
    section_header(
        "Historial de apagones",
        "Captura el patrón de apagones para estimar uso anual sin cambiar el dimensionamiento por evento.",
        icon_name="bolt",
    )

    hours_col, frequency_col, unit_col, average_col, max_col = st.columns([1, 1, 1, 1, 1])
    with hours_col:
        backup_hours = st.number_input(
            "Horas objetivo",
            min_value=0.0,
            max_value=24.0,
            step=1.0,
            format="%.1f",
            key=STAGE3_WIDGET_KEYS["backup_hours"],
            on_change=_sync_stage3_backup_hours,
        )
    st.session_state.stage3_backup_hours = float(backup_hours)
    with frequency_col:
        outage_frequency = st.number_input(
            "Frecuencia",
            min_value=0.0,
            step=1.0,
            format="%.1f",
            key=STAGE3_WIDGET_KEYS["outage_frequency"],
            on_change=_sync_stage3_outage_frequency,
        )
    st.session_state.stage3_outage_frequency = float(outage_frequency)
    with unit_col:
        outage_frequency_unit = st.selectbox(
            "Unidad",
            options=["Por mes", "Por semana"],
            key=STAGE3_WIDGET_KEYS["outage_frequency_unit"],
            on_change=_sync_stage3_outage_frequency_unit,
        )
    st.session_state.stage3_outage_frequency_unit = str(outage_frequency_unit)
    with average_col:
        average_duration = st.number_input(
            "Duración promedio [h]",
            min_value=0.0,
            max_value=168.0,
            step=0.5,
            format="%.1f",
            key=STAGE3_WIDGET_KEYS["average_outage_duration_h"],
            on_change=_sync_stage3_average_outage_duration,
        )
    st.session_state.stage3_average_outage_duration_h = float(average_duration)
    with max_col:
        max_duration = st.number_input(
            "Duración máxima típica [h]",
            min_value=0.0,
            max_value=168.0,
            step=0.5,
            format="%.1f",
            key=STAGE3_WIDGET_KEYS["typical_max_outage_duration_h"],
            on_change=_sync_stage3_typical_max_outage_duration,
        )
    st.session_state.stage3_typical_max_outage_duration_h = float(max_duration)

    result, error = _stage3_backup_result()
    if error:
        st.warning("Revisa el historial de apagones.")
    elif result is not None:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Energía por evento", f"{result['usable_energy_required_kwh']:,.1f} kWh")
        col2.metric("Apagones al año", f"{result['annual_outage_events']:,.1f}")
        col3.metric("Horas anuales sin red", f"{result['annual_outage_hours']:,.1f} h")
        col4.metric("Apagón largo no cubierto", f"{result['long_outage_uncovered_hours']:,.1f} h")


def render_stage3_bess_step(result: dict[str, float | bool | None] | None, error: str | None) -> None:
    _prepare_stage3_widget_state()
    section_header(
        "Sistema BESS",
        "Ajusta los supuestos básicos para estimar la capacidad nominal del banco de baterías.",
        icon_name="settings",
    )

    tech_col, battery_col, power_col, cycles_col = st.columns([1, 1, 1, 1])
    with tech_col:
        battery_technology = st.text_input(
            "Nombre o tecnología de batería",
            help="Usa LiFePO4 como referencia inicial o escribe el nombre del modelo comercial que deseas evaluar.",
            key=STAGE3_WIDGET_KEYS["battery_technology"],
            on_change=_sync_stage3_battery_technology,
        )
        st.session_state.stage3_battery_technology = str(battery_technology).strip() or "LiFePO4"
        st.caption("LiFePO4 es una referencia inicial; puedes evaluar otro modelo comercial.")
    with battery_col:
        battery_capacity = st.number_input(
            "Capacidad por batería [kWh]",
            min_value=0.0,
            step=1.0,
            format="%.1f",
            key=STAGE3_WIDGET_KEYS["battery_capacity_kwh"],
            on_change=_sync_stage3_battery_capacity,
        )
    st.session_state.stage3_battery_capacity_kwh = float(battery_capacity)
    with power_col:
        battery_power = st.number_input(
            "Potencia por batería [kW]",
            min_value=0.0,
            step=1.0,
            format="%.1f",
            key=STAGE3_WIDGET_KEYS["battery_max_power_kw"],
            on_change=_sync_stage3_battery_max_power,
        )
    st.session_state.stage3_battery_max_power_kw = float(battery_power)
    with cycles_col:
        life_cycles = st.number_input(
            "Ciclos de vida estimados",
            min_value=0.0,
            step=500.0,
            format="%.0f",
            key=STAGE3_WIDGET_KEYS["life_cycles"],
            on_change=_sync_stage3_life_cycles,
        )
    st.session_state.stage3_life_cycles = float(life_cycles)

    dod_col, efficiency_col, margin_col = st.columns(3)
    with dod_col:
        depth_of_discharge = st.number_input(
            "Profundidad de descarga",
            min_value=0.01,
            max_value=1.0,
            step=0.05,
            format="%.2f",
            key=STAGE3_WIDGET_KEYS["depth_of_discharge"],
            on_change=_sync_stage3_depth_of_discharge,
        )
    st.session_state.stage3_depth_of_discharge = float(depth_of_discharge)
    with efficiency_col:
        system_efficiency = st.number_input(
            "Eficiencia del sistema",
            min_value=0.01,
            max_value=1.0,
            step=0.05,
            format="%.2f",
            key=STAGE3_WIDGET_KEYS["system_efficiency"],
            on_change=_sync_stage3_system_efficiency,
        )
    st.session_state.stage3_system_efficiency = float(system_efficiency)
    with margin_col:
        safety_margin = st.number_input(
            "Margen de seguridad",
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            format="%.2f",
            key=STAGE3_WIDGET_KEYS["safety_margin"],
            on_change=_sync_stage3_safety_margin,
        )
    st.session_state.stage3_safety_margin = float(safety_margin)

    result, error = _stage3_backup_result()
    if error:
        st.warning("Revisa los supuestos del sistema BESS.")
    elif result is not None:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Energía útil", f"{result['usable_energy_required_kwh']:,.1f} kWh")
        col2.metric("Capacidad nominal", f"{result['nominal_bess_capacity_kwh']:,.1f} kWh")
        col3.metric("Baterías recomendadas", f"{result['recommended_battery_count']:,.0f}")
        col4.metric("Energía útil instalada", f"{result['usable_installed_energy_kwh']:,.1f} kWh")
        col5.metric("Autonomía real instalada", f"{result['installed_backup_hours']:,.1f} h")


def render_stage3_results_step(result: dict[str, float | bool | None] | None, error: str | None) -> None:
    section_header(
        "Resultados",
        "Dimensionamiento preliminar del respaldo energético con BESS.",
        icon_name="bolt",
    )

    if error:
        st.warning("Revisa las entradas del wizard para mostrar resultados.")
        return
    if result is None:
        st.warning("Ingresa carga crítica, horas de respaldo y supuestos válidos.")
        return

    if not st.session_state.get("stage3_result_is_complete", False):
        st.info("El dimensionamiento se mostrará completo cuando la carga crítica y las horas sean mayores que cero.")

    st.markdown("**Dimensionamiento por evento**")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        metric_card("Potencia crítica", f"{result['critical_load_kw']:,.2f} kW")
    with col2:
        metric_card("Horas de respaldo", f"{result['backup_hours']:,.1f} h")
    with col3:
        metric_card("Energía útil", f"{result['usable_energy_required_kwh']:,.1f} kWh")
    with col4:
        metric_card("BESS nominal", f"{result['nominal_bess_capacity_kwh']:,.1f} kWh")
    with col5:
        metric_card("Baterías", f"{result['recommended_battery_count']:,.0f}")

    col6, col7, col8, col9, col10 = st.columns(5)
    with col6:
        metric_card("Tecnología", str(st.session_state.get("stage3_battery_technology", "LiFePO4")))
    with col7:
        metric_card("Profundidad de descarga", f"{result['depth_of_discharge']:.0%}")
    with col8:
        metric_card("Eficiencia y margen", f"{result['system_efficiency']:.0%} / {result['safety_margin']:.0%}")
    with col9:
        metric_card("Capacidad instalada", f"{result['total_installed_capacity_kwh']:,.1f} kWh")
    with col10:
        metric_card("Autonomía real instalada", f"{result['installed_backup_hours']:,.1f} h")

    st.markdown("**Uso anual estimado**")
    cycle_life = interpret_cycle_life(
        float(result["equivalent_cycles_per_year"]),
        result["estimated_life_years_by_cycles"],
    )
    long_outage_label = (
        f"{result['long_outage_uncovered_hours']:,.1f} h"
        if result["long_outage_uncovered_hours"] > 0
        else "Cubierto"
    )
    annual_col1, annual_col2, annual_col3, annual_col4 = st.columns(4)
    with annual_col1:
        metric_card("Apagones al año", f"{result['annual_outage_events']:,.1f}")
    with annual_col2:
        metric_card("Horas sin red", f"{result['annual_outage_hours']:,.1f} h")
    with annual_col3:
        metric_card("Horas respaldadas", f"{result['annual_backed_hours']:,.1f} h")
    with annual_col4:
        metric_card("Horas no cubiertas", f"{result['annual_uncovered_hours']:,.1f} h")

    annual_col5, annual_col6, annual_col7, annual_col8 = st.columns(4)
    with annual_col5:
        metric_card("Energía anual respaldada", f"{result['annual_backed_energy_kwh']:,.1f} kWh")
    with annual_col6:
        metric_card("Ciclos equivalentes", f"{result['equivalent_cycles_per_year']:,.1f}/año")
    with annual_col7:
        metric_card(cycle_life["title"], cycle_life["value"])
    with annual_col8:
        metric_card("Apagón largo", long_outage_label)

    average_status = (
        "El sistema cubre el apagón promedio capturado."
        if result["average_outage_covered"]
        else "El apagón promedio supera las horas objetivo seleccionadas."
    )
    if result["long_outage_uncovered_hours"] > 0:
        st.warning(f"{average_status} Un apagón largo típico podría quedar corto por {result['long_outage_uncovered_hours']:,.1f} h.")
    else:
        st.info(f"{average_status} La duración máxima típica queda cubierta por las horas objetivo.")

    st.caption(
        "El resultado estima la capacidad nominal del banco de baterías necesaria para sostener la carga crítica durante "
        "las horas seleccionadas, considerando profundidad de descarga, eficiencia y margen de seguridad."
    )
    st.caption(
        "El tamaño del banco se calcula para un apagón objetivo. El historial de apagones permite estimar el uso anual "
        "del sistema y la exigencia sobre la batería. Las horas respaldadas se limitan por la autonomía real instalada."
    )
    st.caption(
        "La vida por ciclos es una referencia teórica. En usos con pocos apagones, los ciclos pueden no ser el factor "
        "limitante; la vida real depende de vida calendario, garantía, temperatura y condiciones de operación."
    )

    with st.expander("Cómo interpretar estos resultados", expanded=False):
        st.markdown(
            """
            - La energía útil requerida es la energía que consumen las cargas críticas durante el periodo de respaldo.
            - La capacidad nominal es mayor que la energía útil porque considera profundidad de descarga, eficiencia y margen de seguridad.
            - El número recomendado de baterías considera energía nominal requerida y potencia crítica.
            - El historial de apagones estima eventos anuales y horas sin red.
            - Las horas respaldadas y la energía anual respaldada se limitan por la autonomía real instalada.
            - Los ciclos equivalentes comparan la energía anual realmente respaldada contra la energía útil instalada.
            - La vida por ciclos es una referencia teórica; no representa una garantía de vida real de la batería.
            - La profundidad de descarga indica qué fracción de la batería se usa sin agotar todo el banco.
            - La eficiencia representa pérdidas del sistema entre batería, conversión y entrega a la carga.
            - El margen de seguridad agrega holgura para variaciones operativas y degradación preliminar.
            - La frecuencia de apagones no aumenta automáticamente la capacidad nominal requerida; aumenta el uso anual estimado.
            - Este resultado es una estimación de dimensionamiento preliminar, no una cotización ni un estudio financiero.
            """
        )


def render_stage3_backup_wizard() -> None:
    section_header(
        "Respaldo",
        "Dimensiona un sistema básico de respaldo con BESS para cargas críticas.",
        icon_name="bolt",
    )
    result, error = _stage3_backup_result()
    render_stage3_progress()
    st.divider()

    active_step = str(st.session_state.get("stage3_step", "carga"))
    if active_step == "carga":
        render_stage3_load_step(result, error)
    elif active_step == "historial":
        render_stage3_history_step(result, error)
    elif active_step == "bess":
        render_stage3_bess_step(result, error)
    else:
        render_stage3_results_step(result, error)

    result, _error = _stage3_backup_result()
    st.divider()
    render_stage3_navigation()
    render_stage3_context(result)


STAGE4_STEPS = [
    ("inaccion", "Costo de inacción"),
    ("inversion", "Inversión"),
    ("evaluacion", "Evaluación"),
    ("resultados", "Resultados"),
]


STAGE4_WIDGET_KEYS = {
    "annual_outage_events": "_stage4_annual_outage_events_widget",
    "annual_outage_hours": "_stage4_annual_outage_hours_widget",
    "outage_cost_per_hour": "_stage4_outage_cost_per_hour_widget",
    "fixed_cost_per_outage": "_stage4_fixed_cost_per_outage_widget",
    "annual_repairs": "_stage4_annual_repairs_widget",
    "avoidable_loss_fraction": "_stage4_avoidable_loss_fraction_widget",
    "recommended_batteries": "_stage4_recommended_batteries_widget",
    "battery_unit_cost": "_stage4_battery_unit_cost_widget",
    "balance_of_system_mode": "_stage4_balance_of_system_mode_widget",
    "balance_of_system_percentage": "_stage4_balance_of_system_percentage_widget",
    "balance_of_system_manual_cost": "_stage4_balance_of_system_manual_cost_widget",
    "include_pv_investment": "_stage4_include_pv_investment_widget",
    "pv_investment_cost": "_stage4_pv_investment_cost_widget",
    "include_energy_savings": "_stage4_include_energy_savings_widget",
    "annual_energy_savings": "_stage4_annual_energy_savings_widget",
}


def _stage4_step_ids() -> list[str]:
    return [step_id for step_id, _label in STAGE4_STEPS]


def _set_stage4_step(step_id: str) -> None:
    if step_id in _stage4_step_ids():
        st.session_state.stage4_step = step_id


def _format_mxn(value: float | None) -> str:
    if value is None:
        return "No disponible"
    return f"${float(value):,.0f} MXN"


def _format_years(value: float | None) -> str:
    if value is None:
        return "No disponible"
    return f"{float(value):,.1f} años"


def _stage4_stage3_events_reference() -> float:
    return float(st.session_state.get("stage3_result_annual_outage_events", 0.0) or 0.0)


def _stage4_stage3_hours_reference() -> float:
    return float(st.session_state.get("stage3_result_annual_outage_hours", 0.0) or 0.0)


def _stage4_stage3_battery_reference() -> float:
    return float(st.session_state.get("stage3_result_recommended_battery_count", 0.0) or 0.0)


def _stage4_annual_outage_events_value() -> float:
    manual_value = float(st.session_state.get("stage4_annual_outage_events", 0.0) or 0.0)
    return manual_value if manual_value > 0.0 else _stage4_stage3_events_reference()


def _stage4_annual_outage_hours_value() -> float:
    manual_value = float(st.session_state.get("stage4_annual_outage_hours", 0.0) or 0.0)
    return manual_value if manual_value > 0.0 else _stage4_stage3_hours_reference()


def _stage4_recommended_batteries_value() -> float:
    manual_value = float(st.session_state.get("stage4_recommended_batteries", 0.0) or 0.0)
    return manual_value if manual_value > 0.0 else _stage4_stage3_battery_reference()


def _stage4_energy_savings_reference(summary: dict[str, float]) -> float:
    express = _stage2_express_result(summary)
    annual_savings = express.get("annual_savings")
    return float(annual_savings or 0.0)


def _prepare_stage4_widget_state(summary: dict[str, float]) -> None:
    st.session_state[STAGE4_WIDGET_KEYS["annual_outage_events"]] = _stage4_annual_outage_events_value()
    st.session_state[STAGE4_WIDGET_KEYS["annual_outage_hours"]] = _stage4_annual_outage_hours_value()
    st.session_state[STAGE4_WIDGET_KEYS["outage_cost_per_hour"]] = st.session_state.stage4_outage_cost_per_hour_mxn
    st.session_state[STAGE4_WIDGET_KEYS["fixed_cost_per_outage"]] = st.session_state.stage4_fixed_cost_per_outage_mxn
    st.session_state[STAGE4_WIDGET_KEYS["annual_repairs"]] = st.session_state.stage4_annual_repairs_or_damage_cost_mxn
    st.session_state[STAGE4_WIDGET_KEYS["avoidable_loss_fraction"]] = (
        st.session_state.stage4_avoidable_loss_fraction * 100.0
    )
    st.session_state[STAGE4_WIDGET_KEYS["recommended_batteries"]] = _stage4_recommended_batteries_value()
    st.session_state[STAGE4_WIDGET_KEYS["battery_unit_cost"]] = st.session_state.stage4_battery_unit_cost_mxn
    st.session_state[STAGE4_WIDGET_KEYS["balance_of_system_mode"]] = st.session_state.stage4_balance_of_system_mode
    st.session_state[STAGE4_WIDGET_KEYS["balance_of_system_percentage"]] = (
        st.session_state.stage4_balance_of_system_percentage * 100.0
    )
    st.session_state[STAGE4_WIDGET_KEYS["balance_of_system_manual_cost"]] = st.session_state.stage4_balance_of_system_manual_cost_mxn
    st.session_state[STAGE4_WIDGET_KEYS["include_pv_investment"]] = st.session_state.stage4_include_pv_investment
    st.session_state[STAGE4_WIDGET_KEYS["pv_investment_cost"]] = st.session_state.stage4_pv_investment_cost_mxn
    st.session_state[STAGE4_WIDGET_KEYS["include_energy_savings"]] = st.session_state.stage4_include_energy_savings
    energy_savings = float(st.session_state.get("stage4_annual_energy_savings_mxn", 0.0) or 0.0)
    st.session_state[STAGE4_WIDGET_KEYS["annual_energy_savings"]] = (
        energy_savings if energy_savings > 0.0 else _stage4_energy_savings_reference(summary)
    )


def _sync_stage4_annual_outage_events() -> None:
    st.session_state.stage4_annual_outage_events = float(st.session_state[STAGE4_WIDGET_KEYS["annual_outage_events"]])


def _sync_stage4_annual_outage_hours() -> None:
    st.session_state.stage4_annual_outage_hours = float(st.session_state[STAGE4_WIDGET_KEYS["annual_outage_hours"]])


def _sync_stage4_outage_cost_per_hour() -> None:
    st.session_state.stage4_outage_cost_per_hour_mxn = float(st.session_state[STAGE4_WIDGET_KEYS["outage_cost_per_hour"]])


def _sync_stage4_fixed_cost_per_outage() -> None:
    st.session_state.stage4_fixed_cost_per_outage_mxn = float(st.session_state[STAGE4_WIDGET_KEYS["fixed_cost_per_outage"]])


def _sync_stage4_annual_repairs() -> None:
    st.session_state.stage4_annual_repairs_or_damage_cost_mxn = float(st.session_state[STAGE4_WIDGET_KEYS["annual_repairs"]])


def _sync_stage4_avoidable_loss_fraction() -> None:
    st.session_state.stage4_avoidable_loss_fraction = percent_to_fraction(
        st.session_state[STAGE4_WIDGET_KEYS["avoidable_loss_fraction"]],
        "avoidable_loss_percent",
    )


def _sync_stage4_recommended_batteries() -> None:
    st.session_state.stage4_recommended_batteries = float(st.session_state[STAGE4_WIDGET_KEYS["recommended_batteries"]])


def _sync_stage4_battery_unit_cost() -> None:
    st.session_state.stage4_battery_unit_cost_mxn = float(st.session_state[STAGE4_WIDGET_KEYS["battery_unit_cost"]])


def _sync_stage4_balance_of_system_mode() -> None:
    st.session_state.stage4_balance_of_system_mode = str(st.session_state[STAGE4_WIDGET_KEYS["balance_of_system_mode"]])


def _sync_stage4_balance_of_system_percentage() -> None:
    st.session_state.stage4_balance_of_system_percentage = percent_to_fraction(
        st.session_state[STAGE4_WIDGET_KEYS["balance_of_system_percentage"]],
        "balance_of_system_percent",
    )


def _sync_stage4_balance_of_system_manual_cost() -> None:
    st.session_state.stage4_balance_of_system_manual_cost_mxn = float(st.session_state[STAGE4_WIDGET_KEYS["balance_of_system_manual_cost"]])


def _sync_stage4_include_pv_investment() -> None:
    st.session_state.stage4_include_pv_investment = bool(st.session_state[STAGE4_WIDGET_KEYS["include_pv_investment"]])


def _sync_stage4_pv_investment_cost() -> None:
    st.session_state.stage4_pv_investment_cost_mxn = float(st.session_state[STAGE4_WIDGET_KEYS["pv_investment_cost"]])


def _sync_stage4_include_energy_savings() -> None:
    st.session_state.stage4_include_energy_savings = bool(st.session_state[STAGE4_WIDGET_KEYS["include_energy_savings"]])


def _sync_stage4_annual_energy_savings() -> None:
    st.session_state.stage4_annual_energy_savings_mxn = float(st.session_state[STAGE4_WIDGET_KEYS["annual_energy_savings"]])


def _stage4_profitability_result(summary: dict[str, float]) -> tuple[dict[str, float | None] | None, str | None]:
    try:
        result = calculate_profitability(
            annual_outage_events=_stage4_annual_outage_events_value(),
            annual_outage_hours=_stage4_annual_outage_hours_value(),
            outage_cost_per_hour=float(st.session_state.get("stage4_outage_cost_per_hour_mxn", 0.0)),
            fixed_cost_per_outage=float(st.session_state.get("stage4_fixed_cost_per_outage_mxn", 0.0)),
            annual_repairs_or_damage_cost=float(st.session_state.get("stage4_annual_repairs_or_damage_cost_mxn", 0.0)),
            avoidable_loss_fraction=float(st.session_state.get("stage4_avoidable_loss_fraction", 0.90)),
            recommended_batteries=_stage4_recommended_batteries_value(),
            battery_unit_cost=float(st.session_state.get("stage4_battery_unit_cost_mxn", 25000.0)),
            balance_of_system_mode=str(st.session_state.get("stage4_balance_of_system_mode", "Porcentaje")),
            balance_of_system_percentage=float(st.session_state.get("stage4_balance_of_system_percentage", 0.20)),
            balance_of_system_manual_cost=float(st.session_state.get("stage4_balance_of_system_manual_cost_mxn", 0.0)),
            include_pv_investment=bool(st.session_state.get("stage4_include_pv_investment", False)),
            pv_investment_cost=float(st.session_state.get("stage4_pv_investment_cost_mxn", 0.0)),
            include_energy_savings=bool(st.session_state.get("stage4_include_energy_savings", False)),
            annual_energy_savings=float(st.session_state.get("stage4_annual_energy_savings_mxn", 0.0) or _stage4_energy_savings_reference(summary)),
        )
    except ValueError as exc:
        st.session_state.stage4_result_is_complete = False
        return None, str(exc)

    st.session_state.stage4_result_annual_inaction_cost = float(result["annual_inaction_cost"])
    st.session_state.stage4_result_avoidable_losses = float(result["avoidable_losses"])
    st.session_state.stage4_result_total_investment = float(result["total_investment"])
    st.session_state.stage4_result_annual_total_benefit = float(result["annual_total_benefit"])
    st.session_state.stage4_result_simple_payback_years = result["simple_payback_years"]
    st.session_state.stage4_result_simple_roi_pct = result["simple_roi_pct"]
    st.session_state.stage4_result_is_complete = result["total_investment"] > 0.0 and result["annual_total_benefit"] > 0.0
    return result, None


def render_stage4_progress() -> None:
    active_step = str(st.session_state.get("stage4_step", "inaccion"))
    if active_step not in _stage4_step_ids():
        active_step = "inaccion"
        st.session_state.stage4_step = active_step
    active_index = _stage4_step_ids().index(active_step)

    cols = st.columns(len(STAGE4_STEPS))
    for index, (step_id, label) in enumerate(STAGE4_STEPS):
        if index < active_index:
            status = "Listo"
        elif index == active_index:
            status = "Actual"
        else:
            status = "Pendiente"
        with cols[index]:
            button_type = "primary" if index == active_index else "secondary"
            if st.button(label, key=f"stage4_step_button_{step_id}", use_container_width=True, type=button_type):
                _set_stage4_step(step_id)
                st.rerun()
            st.caption(status)


def render_stage4_navigation() -> None:
    step_ids = _stage4_step_ids()
    active_step = str(st.session_state.get("stage4_step", "inaccion"))
    if active_step not in step_ids:
        active_step = "inaccion"
    index = step_ids.index(active_step)
    left, _middle, right = st.columns([1, 3, 1])
    if index > 0:
        previous_id, previous_label = STAGE4_STEPS[index - 1]
        if left.button(previous_label, key=f"stage4_previous_{active_step}", use_container_width=True):
            _set_stage4_step(previous_id)
            st.rerun()
    if index < len(STAGE4_STEPS) - 1:
        next_id, next_label = STAGE4_STEPS[index + 1]
        if right.button(next_label, key=f"stage4_next_{active_step}", use_container_width=True):
            _set_stage4_step(next_id)
            st.rerun()


def render_stage4_context(result: dict[str, float | None] | None) -> None:
    if result is None:
        context = "Rentabilidad pendiente: revisa pérdidas, inversión y beneficios."
    else:
        context = (
            f"Inversión total: {_format_mxn(result['total_investment'])} | "
            f"Beneficio anual: {_format_mxn(result['annual_total_benefit'])} | "
            f"Recuperación: {_format_years(result['simple_payback_years'])}"
        )
    with st.container(border=True):
        st.caption(context)


def render_stage4_inaction_step(summary: dict[str, float], result: dict[str, float | None] | None, error: str | None) -> None:
    _prepare_stage4_widget_state(summary)
    section_header(
        "Costo de inacción",
        "Captura el impacto económico anual de apagones y daños operativos.",
        icon_name="table",
    )

    if _stage4_stage3_events_reference() > 0.0 or _stage4_stage3_hours_reference() > 0.0:
        st.caption(
            f"Referencia de Respaldo: {_stage4_stage3_events_reference():,.1f} apagones/año, "
            f"{_stage4_stage3_hours_reference():,.1f} h/año sin red."
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        annual_events = st.number_input(
            "Apagones al año",
            min_value=0.0,
            step=1.0,
            format="%.1f",
            key=STAGE4_WIDGET_KEYS["annual_outage_events"],
            on_change=_sync_stage4_annual_outage_events,
        )
    st.session_state.stage4_annual_outage_events = float(annual_events)
    with col2:
        annual_hours = st.number_input(
            "Horas anuales sin red",
            min_value=0.0,
            step=1.0,
            format="%.1f",
            key=STAGE4_WIDGET_KEYS["annual_outage_hours"],
            on_change=_sync_stage4_annual_outage_hours,
        )
    st.session_state.stage4_annual_outage_hours = float(annual_hours)
    with col3:
        hourly_cost = st.number_input(
            "Costo por hora sin operación [MXN/h]",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            key=STAGE4_WIDGET_KEYS["outage_cost_per_hour"],
            on_change=_sync_stage4_outage_cost_per_hour,
        )
    st.session_state.stage4_outage_cost_per_hour_mxn = float(hourly_cost)
    with col4:
        avoidable_percent = st.number_input(
            "Pérdidas evitables [%]",
            min_value=0.0,
            max_value=100.0,
            step=5.0,
            format="%.0f",
            key=STAGE4_WIDGET_KEYS["avoidable_loss_fraction"],
            on_change=_sync_stage4_avoidable_loss_fraction,
        )
    st.session_state.stage4_avoidable_loss_fraction = percent_to_fraction(avoidable_percent, "avoidable_loss_percent")

    cost_col1, cost_col2 = st.columns(2)
    with cost_col1:
        fixed_cost = st.number_input(
            "Costo fijo por apagón [MXN/evento]",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            key=STAGE4_WIDGET_KEYS["fixed_cost_per_outage"],
            on_change=_sync_stage4_fixed_cost_per_outage,
        )
    st.session_state.stage4_fixed_cost_per_outage_mxn = float(fixed_cost)
    with cost_col2:
        repairs = st.number_input(
            "Reparaciones o daños anuales [MXN/año]",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            key=STAGE4_WIDGET_KEYS["annual_repairs"],
            on_change=_sync_stage4_annual_repairs,
        )
    st.session_state.stage4_annual_repairs_or_damage_cost_mxn = float(repairs)

    result, error = _stage4_profitability_result(summary)
    if error:
        st.warning("Revisa los valores del costo de inacción.")
    elif result is not None:
        metric1, metric2, metric3, metric4 = st.columns(4)
        metric1.metric("Apagones al año", f"{result['annual_outage_events']:,.1f}")
        metric2.metric("Horas sin red", f"{result['annual_outage_hours']:,.1f} h")
        metric3.metric("Costo anual de inacción", _format_mxn(result["annual_inaction_cost"]))
        metric4.metric("Pérdidas evitables", _format_mxn(result["avoidable_losses"]))


def render_stage4_investment_step(summary: dict[str, float], result: dict[str, float | None] | None, error: str | None) -> None:
    _prepare_stage4_widget_state(summary)
    section_header(
        "Inversión estimada",
        "Estima el costo de implementar el respaldo con baterías y componentes complementarios.",
        icon_name="table",
    )

    if _stage4_stage3_battery_reference() > 0.0:
        st.caption(
            f"Referencia de Respaldo: {_stage4_stage3_battery_reference():,.0f} baterías, "
            f"{float(st.session_state.get('stage3_result_required_nominal_kwh', 0.0) or 0.0):,.1f} kWh nominales, "
            f"{st.session_state.get('stage3_battery_technology', 'LiFePO4')}."
        )
    st.caption(
        "LiFePO4 y $25,000 MXN se usan como referencia inicial. Puedes ajustar el modelo, capacidad y costo "
        "según la ficha técnica y cotización real."
    )

    batt_col, unit_col, mode_col, complement_col = st.columns(4)
    with batt_col:
        batteries = st.number_input(
            "Baterías consideradas",
            min_value=0.0,
            step=1.0,
            format="%.0f",
            key=STAGE4_WIDGET_KEYS["recommended_batteries"],
            on_change=_sync_stage4_recommended_batteries,
        )
    st.session_state.stage4_recommended_batteries = float(batteries)
    with unit_col:
        unit_cost = st.number_input(
            "Costo unitario por batería [MXN]",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            key=STAGE4_WIDGET_KEYS["battery_unit_cost"],
            on_change=_sync_stage4_battery_unit_cost,
        )
        st.caption("El costo unitario es una referencia editable; sustitúyelo por la cotización real.")
    st.session_state.stage4_battery_unit_cost_mxn = float(unit_cost)
    with mode_col:
        bos_mode = st.radio(
            "Costos complementarios",
            options=["Porcentaje", "Monto manual"],
            horizontal=True,
            key=STAGE4_WIDGET_KEYS["balance_of_system_mode"],
            on_change=_sync_stage4_balance_of_system_mode,
        )
    st.session_state.stage4_balance_of_system_mode = str(bos_mode)
    with complement_col:
        if bos_mode == "Porcentaje":
            bos_percentage_percent = st.number_input(
                "Costos complementarios [%]",
                min_value=0.0,
                max_value=100.0,
                step=5.0,
                format="%.0f",
                key=STAGE4_WIDGET_KEYS["balance_of_system_percentage"],
                on_change=_sync_stage4_balance_of_system_percentage,
            )
            st.session_state.stage4_balance_of_system_percentage = percent_to_fraction(
                bos_percentage_percent,
                "balance_of_system_percent",
            )
        else:
            bos_manual = st.number_input(
                "Monto complementario [MXN]",
                min_value=0.0,
                step=1000.0,
                format="%.0f",
                key=STAGE4_WIDGET_KEYS["balance_of_system_manual_cost"],
                on_change=_sync_stage4_balance_of_system_manual_cost,
            )
            st.session_state.stage4_balance_of_system_manual_cost_mxn = float(bos_manual)

    pv_toggle_col, pv_cost_col = st.columns([1, 1])
    with pv_toggle_col:
        include_pv = st.checkbox(
            "Incluir inversión FV",
            key=STAGE4_WIDGET_KEYS["include_pv_investment"],
            on_change=_sync_stage4_include_pv_investment,
        )
    st.session_state.stage4_include_pv_investment = bool(include_pv)
    with pv_cost_col:
        pv_cost = st.number_input(
            "Inversión FV estimada [MXN]",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            disabled=not include_pv,
            key=STAGE4_WIDGET_KEYS["pv_investment_cost"],
            on_change=_sync_stage4_pv_investment_cost,
        )
    st.session_state.stage4_pv_investment_cost_mxn = float(pv_cost)

    result, error = _stage4_profitability_result(summary)
    if error:
        st.warning("Revisa los valores de inversión.")
    elif result is not None:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Baterías", f"{result['recommended_batteries']:,.0f}")
        col2.metric("Costo baterías", _format_mxn(result["battery_total_cost"]))
        col3.metric("Complementarios", _format_mxn(result["balance_of_system_cost"]))
        col4.metric("Inversión BESS", _format_mxn(result["bess_investment"]))
        col5.metric("Inversión total", _format_mxn(result["total_investment"]))


def render_stage4_evaluation_step(summary: dict[str, float], result: dict[str, float | None] | None, error: str | None) -> None:
    _prepare_stage4_widget_state(summary)
    section_header(
        "Evaluación",
        "Combina pérdidas evitables y ahorro energético opcional para estimar recuperación simple.",
        icon_name="chart",
    )

    savings_reference = _stage4_energy_savings_reference(summary)
    if savings_reference > 0.0:
        st.caption(f"Referencia de Consumo y ahorro: {_format_mxn(savings_reference)} anuales. Puedes editarla o desactivarla.")
    else:
        st.caption("El ahorro energético anual es opcional. Puedes capturarlo manualmente si deseas incluirlo.")

    include_col, savings_col = st.columns([1, 1])
    with include_col:
        include_savings = st.checkbox(
            "Incluir ahorro energético anual",
            key=STAGE4_WIDGET_KEYS["include_energy_savings"],
            on_change=_sync_stage4_include_energy_savings,
        )
    st.session_state.stage4_include_energy_savings = bool(include_savings)
    with savings_col:
        annual_savings = st.number_input(
            "Ahorro energético anual [MXN/año]",
            min_value=0.0,
            step=1000.0,
            format="%.0f",
            disabled=not include_savings,
            key=STAGE4_WIDGET_KEYS["annual_energy_savings"],
            on_change=_sync_stage4_annual_energy_savings,
        )
    st.session_state.stage4_annual_energy_savings_mxn = float(annual_savings)

    result, error = _stage4_profitability_result(summary)
    if error:
        st.warning("Revisa los valores de evaluación.")
    elif result is not None:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Beneficio anual total", _format_mxn(result["annual_total_benefit"]))
        col2.metric("Recuperación simple", _format_years(result["simple_payback_years"]))
        roi_label = f"{result['simple_roi_pct']:,.1f} %" if result["simple_roi_pct"] is not None else "No disponible"
        col3.metric("ROI simple", roi_label)
        col4.metric("Inacción a 5 años", _format_mxn(result["inaction_cost_5_years"]))
        if result["annual_total_benefit"] <= 0.0:
            st.info("No es posible estimar recuperación con beneficio anual nulo.")


def render_stage4_results_step(result: dict[str, float | None] | None, error: str | None) -> None:
    section_header(
        "Resultados",
        "Resumen ejecutivo de rentabilidad simple por continuidad operativa.",
        icon_name="table",
    )
    if error:
        st.warning("Revisa las entradas del wizard para mostrar resultados.")
        return
    if result is None:
        st.warning("Captura pérdidas e inversión para mostrar resultados de rentabilidad.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Inversión total", _format_mxn(result["total_investment"]))
    with col2:
        metric_card("Costo anual de inacción", _format_mxn(result["annual_inaction_cost"]))
    with col3:
        metric_card("Pérdidas evitables", _format_mxn(result["avoidable_losses"]))
    with col4:
        metric_card("Ahorro energético", _format_mxn(result["annual_energy_savings"]))

    col5, col6, col7, col8 = st.columns(4)
    with col5:
        metric_card("Beneficio anual total", _format_mxn(result["annual_total_benefit"]))
    with col6:
        metric_card("Recuperación simple", _format_years(result["simple_payback_years"]))
    with col7:
        roi_label = f"{result['simple_roi_pct']:,.1f} %" if result["simple_roi_pct"] is not None else "No disponible"
        metric_card("ROI simple", roi_label)
    with col8:
        metric_card("Inacción a 5 años", _format_mxn(result["inaction_cost_5_years"]))

    horizon_col1, horizon_col2, horizon_col3 = st.columns(3)
    horizon_col1.metric("Inacción a 3 años", _format_mxn(result["inaction_cost_3_years"]))
    horizon_col2.metric("Inacción a 5 años", _format_mxn(result["inaction_cost_5_years"]))
    horizon_col3.metric("Inacción a 10 años", _format_mxn(result["inaction_cost_10_years"]))

    if result["simple_payback_years"] is None:
        st.info("No es posible estimar recuperación con beneficio anual nulo o inversión nula.")
    else:
        st.info(
            f"La inversión se recupera en aproximadamente {result['simple_payback_years']:,.1f} años "
            "usando el beneficio anual estimado: pérdidas evitables más ahorro energético opcional."
        )

    if result["inaction_cost_5_years"] >= result["total_investment"]:
        st.success(
            "Como métrica de riesgo, el costo bruto de no actuar durante 5 años supera la inversión estimada."
        )
    else:
        st.info(
            "Como métrica de riesgo, el costo bruto de no actuar durante 5 años no supera la inversión estimada."
        )

    st.plotly_chart(
        plot_profitability_cumulative_chart(result),
        use_container_width=True,
        key="stage4_profitability_cumulative_chart",
    )
    if result["annual_total_benefit"] <= 0.0:
        st.caption("No se puede estimar recuperación sin beneficio anual positivo; la gráfica conserva inversión y costo acumulado de inacción.")
    else:
        st.caption(
            "La recuperación simple usa el beneficio acumulado estimado, no todo el costo bruto de la inacción."
        )

    with st.expander("Cómo interpretar la rentabilidad", expanded=False):
        st.markdown(
            """
            - El costo de la inacción estima lo que cuesta operar sin respaldo ante apagones.
            - El beneficio anual suma pérdidas evitables y ahorro energético anual si el usuario decide incluirlo.
            - La recuperación simple divide inversión total entre beneficio anual total, no entre todo el costo bruto de la inacción.
            - Si el sistema evita solo una parte de las pérdidas, únicamente esa parte se considera beneficio.
            - El ROI simple compara beneficio anual total contra inversión total.
            - Este análisis no incluye financiamiento, inflación, impuestos, depreciación, valor presente neto ni tasa interna de retorno.
            - El resultado depende de la calidad de los datos de pérdidas e inversión ingresados.
            """
        )


def render_stage4_profitability_wizard(summary: dict[str, float]) -> None:
    section_header(
        "Rentabilidad",
        "Evalúa recuperación simple, ROI y costo de la inacción con base en continuidad operativa.",
        icon_name="table",
    )
    result, error = _stage4_profitability_result(summary)
    render_stage4_progress()
    st.divider()

    active_step = str(st.session_state.get("stage4_step", "inaccion"))
    if active_step == "inaccion":
        render_stage4_inaction_step(summary, result, error)
    elif active_step == "inversion":
        render_stage4_investment_step(summary, result, error)
    elif active_step == "evaluacion":
        render_stage4_evaluation_step(summary, result, error)
    else:
        render_stage4_results_step(result, error)

    result, _error = _stage4_profitability_result(summary)
    st.divider()
    render_stage4_navigation()
    render_stage4_context(result)


def render_simulation_tab(df: pd.DataFrame, summary: dict[str, float]) -> None:
    section_header(
        "Consumo y balance energético",
        "Generación fotovoltaica, demanda, autoconsumo, energía de red y exportación.",
        icon_name="bolt",
    )
    st.caption("Esta sección usa la demanda configurada para evaluar consumo, autoconsumo y energía de red.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card("Potencia instalada", f"{summary['installed_power_kw']:.1f} kW", "Capacidad nominal del arreglo")
    with col2:
        metric_card("Área total", f"{summary['total_area_m2']:.1f} m²", "Área activa estimada")
    with col3:
        metric_card("Generación anual", f"{summary['total_generation_kwh']:,.0f} kWh", "Energía PV anual")
    with col4:
        metric_card("Cobertura", f"{summary['coverage_percent']:.1f} %", "Demanda cubierta por autoconsumo")

    st.divider()

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Demanda anual", f"{summary['total_demand_kwh']:,.0f} kWh")
    col6.metric("Autoconsumo", f"{summary['self_consumed_kwh']:,.0f} kWh")
    col7.metric("Energía de red", f"{summary['grid_energy_kwh']:,.0f} kWh")
    col8.metric("Energía exportada", f"{summary['exported_kwh']:,.0f} kWh")

    st.caption(
        "La potencia instalada y el área son métricas nominales. La generación anual depende de irradiancia, "
        "temperatura y pérdidas del sistema."
    )
    st.caption(
        "Cobertura de demanda usa autoconsumo directo: energía FV generada y consumida en el mismo intervalo. "
        "Sin baterías, una parte de la generación puede exportarse y no cubrir demanda nocturna o fuera del horario solar."
    )

    annual_demand_kwh = float(summary["total_demand_kwh"])
    annual_generation_kwh = float(summary["total_generation_kwh"])
    self_consumed_kwh = float(summary["self_consumed_kwh"])
    exported_kwh = float(summary["exported_kwh"])
    average_demand_kw = annual_demand_kwh / 8760.0 if annual_demand_kwh > 0 else 0.0
    generation_to_demand_percent = 100.0 * annual_generation_kwh / annual_demand_kwh if annual_demand_kwh > 0 else 0.0
    direct_coverage_percent = 100.0 * self_consumed_kwh / annual_demand_kwh if annual_demand_kwh > 0 else 0.0
    exported_fraction_percent = 100.0 * exported_kwh / annual_generation_kwh if annual_generation_kwh > 0 else 0.0

    col9, col10, col11, col12 = st.columns(4)
    col9.metric("Demanda media anual", f"{average_demand_kw:.1f} kW")
    col10.metric("Generación anual / demanda anual", f"{generation_to_demand_percent:.1f} %")
    col11.metric("Cobertura directa por autoconsumo", f"{direct_coverage_percent:.1f} %")
    col12.metric("Fracción exportada", f"{exported_fraction_percent:.1f} %")
    st.caption(
        "Generación anual / demanda anual compara energía total anual. Cobertura directa por autoconsumo compara "
        "solo la energía FV aprovechada por la carga en el mismo intervalo."
    )

    st.subheader("Operación diaria")
    st.caption("Compara la potencia instantánea generada por el sistema FV contra la demanda del sitio.")
    year = int(st.session_state.year)
    selected_date = st.date_input(
        "Día para resultados energéticos",
        value=pd.to_datetime(f"{year}-06-21").date(),
        min_value=pd.to_datetime(f"{year}-01-01").date(),
        max_value=pd.to_datetime(f"{year}-12-31").date(),
        key="energy_selected_date",
    )
    df_day = df[df["date"] == selected_date]
    if df_day.empty:
        st.warning("No hay datos disponibles para la fecha seleccionada.")
    else:
        st.plotly_chart(
            plot_daily_generation_vs_demand(df_day),
            use_container_width=True,
            key="energy_daily_generation_vs_demand_chart",
        )

    st.subheader("Balance mensual")
    st.caption("Resume generación, demanda, autoconsumo, energía de red y exportación durante el año.")
    st.plotly_chart(plot_monthly_energy(df), use_container_width=True, key="energy_monthly_energy_chart")
    st.plotly_chart(
        plot_monthly_energy_balance(df),
        use_container_width=True,
        key="energy_monthly_balance_chart",
    )


def render_charts_tab(df: pd.DataFrame) -> None:
    section_header(
        "Análisis avanzado",
        "Vistas secundarias para revisar irradiancia, componentes POA y perfiles promedio.",
        icon_name="chart",
    )

    year = int(st.session_state.year)
    selected_date = st.date_input(
        "Día para análisis solar",
        value=pd.to_datetime(f"{year}-06-21").date(),
        min_value=pd.to_datetime(f"{year}-01-01").date(),
        max_value=pd.to_datetime(f"{year}-12-31").date(),
        key="analysis_selected_date",
    )

    df_day = df[df["date"] == selected_date]
    if df_day.empty:
        st.warning("No hay datos disponibles para la fecha seleccionada.")
        return

    st.subheader("Análisis solar diario")
    st.caption("Muestra la irradiancia horizontal, la irradiancia en plano del arreglo y sus componentes físicas.")
    st.plotly_chart(
        plot_daily_ghi_dni_dhi(df_day),
        use_container_width=True,
        key="advanced_daily_ghi_dni_dhi_chart",
    )
    st.plotly_chart(plot_poa_components(df_day), use_container_width=True, key="advanced_poa_components_chart")

    st.subheader("Análisis anual secundario")
    st.caption("Resume el balance anual y el perfil horario promedio para detectar patrones generales.")
    st.plotly_chart(plot_net_energy_flow(df), use_container_width=True, key="advanced_net_energy_flow_chart")
    st.plotly_chart(plot_hourly_average(df), use_container_width=True, key="advanced_hourly_average_chart")


def render_tariff_tab(monthly_tariff: pd.DataFrame, annual_tariff: dict[str, float]) -> None:
    section_header(
        "Ahorro estimado GDMTH",
        "Costo anual sin FV, costo con FV, ahorro, cargos por demanda, factor de potencia e IVA.",
        icon_name="table",
    )
    st.info(
        "Estimación académica configurable. Para una factura oficial deben usarse calendarios, región, temporada y contrato CFE vigentes."
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Costo anual sin FV", f"${annual_tariff['annual_cost_without_pv_mxn']:,.0f} MXN")
    col2.metric("Costo anual con FV", f"${annual_tariff['annual_cost_with_pv_mxn']:,.0f} MXN")
    col3.metric("Ahorro anual", f"${annual_tariff['annual_savings_mxn']:,.0f} MXN")
    col4.metric("Ahorro porcentual", f"{annual_tariff['annual_savings_percent']:.1f} %")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("IVA sin FV", f"${annual_tariff.get('annual_iva_without_pv_mxn', 0):,.0f} MXN")
    col6.metric("IVA con FV", f"${annual_tariff.get('annual_iva_with_pv_mxn', 0):,.0f} MXN")
    col7.metric("Distribución sin FV", f"${annual_tariff.get('annual_distribution_cost_without_pv_mxn', 0):,.0f} MXN")
    col8.metric("Capacidad sin FV", f"${annual_tariff.get('annual_capacity_cost_without_pv_mxn', 0):,.0f} MXN")

    st.subheader("Costo, periodos y componentes")
    st.caption("Compara el costo mensual con y sin FV, la energía por periodo GDMTH y los componentes principales del cargo.")
    st.plotly_chart(
        plot_monthly_tariff_savings(monthly_tariff),
        use_container_width=True,
        key="tariff_monthly_savings_chart",
    )
    st.plotly_chart(
        plot_tariff_energy_by_period(monthly_tariff),
        use_container_width=True,
        key="tariff_energy_by_period_chart",
    )
    st.plotly_chart(
        plot_tariff_component_breakdown(monthly_tariff),
        use_container_width=True,
        key="tariff_component_breakdown_chart",
    )

    with st.expander("Tabla mensual tarifaria"):
        st.caption("Conserva energía por periodos, demandas facturables, factor de potencia, IVA y totales con/sin FV.")
        st.dataframe(monthly_tariff, use_container_width=True, hide_index=True)


def render_scenarios_tab(
    pv_config: PVSystemConfig,
    demand_config: DemandConfig,
    irradiance_df: pd.DataFrame | None,
) -> pd.DataFrame | None:
    section_header(
        "Comparación de escenarios",
        "Evalúa variaciones de número de paneles, tilt y azimuth para identificar configuraciones más convenientes.",
        icon_name="chart",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        panel_text = st.text_input("Paneles", value="40, 60, 80")
    with col2:
        tilt_text = st.text_input("Tilt [°]", value="15, 25, 35")
    with col3:
        azimuth_text = st.text_input("Azimuth [°]", value="170, 180, 190")

    try:
        panel_counts = tuple(int(v) for v in parse_number_list(panel_text, int))
        tilts = tuple(float(v) for v in parse_number_list(tilt_text, float))
        azimuths = tuple(float(v) for v in parse_number_list(azimuth_text, float))
    except ValueError:
        st.error("Revisa que las listas estén separadas por comas y contengan solo números.")
        return None

    total_cases = len(panel_counts) * len(tilts) * len(azimuths)
    st.caption(f"Número de escenarios a evaluar: {total_cases}")
    if total_cases > 60:
        st.warning("Reduce el número de combinaciones para mantener la app rápida.")
        return None

    if st.button("Ejecutar comparación de escenarios", use_container_width=True):
        with st.spinner("Ejecutando escenarios..."):
            st.session_state["scenarios_df"] = run_scenario_grid(
                pv_config,
                demand_config,
                panel_counts,
                tilts,
                azimuths,
                irradiance_df,
            )

    scenarios_df = st.session_state.get("scenarios_df")
    if isinstance(scenarios_df, pd.DataFrame) and not scenarios_df.empty:
        st.plotly_chart(
            plot_scenario_generation(scenarios_df),
            use_container_width=True,
            key="scenario_generation_chart",
        )
        st.plotly_chart(
            plot_scenario_coverage(scenarios_df),
            use_container_width=True,
            key="scenario_coverage_chart",
        )
        st.dataframe(scenarios_df.sort_values("annual_generation_kWh", ascending=False), use_container_width=True, hide_index=True)
        return scenarios_df

    info_panel(
        "Sin escenarios ejecutados",
        "Configura las listas y presiona el botón para comparar alternativas del sistema.",
        icon_name="settings",
    )
    return None


def _current_export_signature(
    df: pd.DataFrame,
    summary: dict[str, float],
    monthly_tariff: pd.DataFrame,
    annual_tariff: dict[str, float],
) -> tuple:
    first_timestamp = str(df["datetime"].iloc[0]) if not df.empty and "datetime" in df.columns else ""
    last_timestamp = str(df["datetime"].iloc[-1]) if not df.empty and "datetime" in df.columns else ""
    summary_values = tuple((key, round(float(value), 6)) for key, value in sorted(summary.items()))
    tariff_values = tuple((key, round(float(value), 6)) for key, value in sorted(annual_tariff.items()))

    energy_columns = [
        "energy_kWh",
        "demand_energy_kWh",
        "self_consumed_kWh",
        "grid_energy_kWh",
        "exported_kWh",
    ]
    available_energy_columns = [column for column in energy_columns if column in df.columns]
    energy_totals = tuple(
        (column, round(float(df[column].sum()), 6))
        for column in available_energy_columns
    )
    if available_energy_columns:
        energy_checksum = int(
            pd.util.hash_pandas_object(
                df[available_energy_columns].round(6),
                index=False,
            ).sum()
        )
    else:
        energy_checksum = 0

    monthly_numeric = monthly_tariff.select_dtypes(include="number")
    monthly_tariff_totals = tuple(
        (column, round(float(monthly_numeric[column].sum()), 6))
        for column in sorted(monthly_numeric.columns)
    )
    if not monthly_numeric.empty:
        monthly_tariff_checksum = int(
            pd.util.hash_pandas_object(
                monthly_numeric.reindex(sorted(monthly_numeric.columns), axis=1).round(6),
                index=False,
            ).sum()
        )
    else:
        monthly_tariff_checksum = 0

    return (
        df.shape,
        first_timestamp,
        last_timestamp,
        summary_values,
        tariff_values,
        energy_totals,
        energy_checksum,
        monthly_tariff_totals,
        monthly_tariff_checksum,
    )


def _reset_prepared_exports_if_needed(export_signature: tuple) -> None:
    if st.session_state.get("prepared_export_signature") == export_signature:
        return

    for key in ("prepared_csv_export", "prepared_excel_export", "prepared_pdf_export"):
        st.session_state.pop(key, None)
    st.session_state.prepared_export_signature = export_signature


def render_results_tab(
    df: pd.DataFrame,
    summary: dict[str, float],
    monthly_tariff: pd.DataFrame,
    annual_tariff: dict[str, float],
    scenarios_df: pd.DataFrame | None,
) -> None:
    section_header(
        "Datos y exportación avanzada",
        "Serie temporal, resumen técnico y descargas disponibles.",
        icon_name="table",
    )
    st.caption("Esta sección conserva las tablas y descargas completas para revisión posterior a la vista rápida.")

    st.subheader("Resumen técnico")
    st.caption("Indicadores principales usados para las descargas y la revisión del caso simulado.")
    summary_df = summary_table(summary)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    st.caption(
        "La potencia nominal estimada por área y eficiencia (STC) se calcula como área × eficiencia × 1000 W/m². "
        "Es una validación nominal del panel, no la generación real simulada; por eso no cambia con nubes ni pérdidas."
    )

    export_signature = _current_export_signature(df, summary, monthly_tariff, annual_tariff)
    _reset_prepared_exports_if_needed(export_signature)

    st.subheader("Exportaciones")
    st.caption("La exportación se genera bajo demanda para mejorar rendimiento.")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Preparar CSV", use_container_width=True):
            st.session_state.prepared_csv_export = df.to_csv(index=False).encode("utf-8")
        if st.session_state.get("prepared_csv_export") is not None:
            st.download_button(
                label="Descargar CSV 15 min",
                data=st.session_state.prepared_csv_export,
                file_name="simulacion_fotovoltaica_gdmth_15min.csv",
                mime="text/csv",
                use_container_width=True,
            )
    with col2:
        st.caption("El archivo Excel incluye la serie anual completa de 15 minutos, por lo que puede tardar varios segundos en generarse.")
        if st.button("Preparar Excel", use_container_width=True):
            with st.spinner("Preparando Excel..."):
                st.session_state.prepared_excel_export = build_excel_export(
                    df,
                    summary_df,
                    monthly_tariff=monthly_tariff,
                    scenarios=scenarios_df,
                )
        if st.session_state.get("prepared_excel_export") is not None:
            st.download_button(
                label="Descargar Excel",
                data=st.session_state.prepared_excel_export,
                file_name="reporte_fotovoltaico_gdmth.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    with col3:
        if st.button("Preparar PDF", use_container_width=True):
            with st.spinner("Preparando PDF..."):
                st.session_state.prepared_pdf_export = build_pdf_report(summary_df, annual_tariff=annual_tariff)
        if st.session_state.get("prepared_pdf_export") is not None:
            st.download_button(
                label="Descargar PDF",
                data=st.session_state.prepared_pdf_export,
                file_name="reporte_fotovoltaico_gdmth.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

    st.subheader("Vista previa quinceminutal")
    st.caption("Primeros intervalos de la simulación anual en resolución de 15 minutos.")
    preview_columns = [
        "datetime",
        "irradiance_source",
        "weather_model_detail",
        "GHI_W_m2",
        "DHI_W_m2",
        "DNI_W_m2",
        "POA_W_m2",
        "generation_kW",
        "demand_kW",
        "demand_source",
        "energy_kWh",
        "demand_energy_kWh",
        "self_consumed_kWh",
        "grid_energy_kWh",
        "exported_kWh",
        "tariff_period",
        "cost_with_pv_mxn",
    ]
    st.dataframe(df[preview_columns].head(120), use_container_width=True, height=360)

    with st.expander("Tabla mensual tarifaria completa"):
        st.dataframe(monthly_tariff, use_container_width=True, hide_index=True)

    st.caption("La tabla completa puede tardar dependiendo del tamaño del dataset.")
    if st.checkbox("Mostrar datos completos", value=False):
        st.dataframe(df, use_container_width=True, height=520)


def render_advanced_solar_controls() -> None:
    section_header(
        "Fuentes solares avanzadas",
        "Opciones técnicas que quedan fuera del flujo principal de Diagnóstico solar.",
        icon_name="settings",
    )
    st.caption("PVGIS, NSRDB, escenario climático simple, modelo POA y albedo se conservan para usuarios avanzados.")

    advanced_source = st.selectbox(
        "Fuente avanzada",
        options=["Escenario climático simple", "PVGIS con pvlib.iotools", "NSRDB PSM3 con pvlib.iotools"],
        key="advanced_source_choice",
        format_func=lambda value: ADVANCED_IRRADIANCE_LABELS.get(value, value),
    )
    if st.button("Usar fuente avanzada", key="advanced_use_source", use_container_width=True):
        _select_irradiance_source(advanced_source)
        st.rerun()

    source = str(st.session_state.irradiance_source)
    if source == "Escenario climático simple":
        st.selectbox(
            "Condición atmosférica",
            options=list(CLIMATE_FACTORS.keys()),
            key="climate_condition",
            help="Los factores climáticos modifican la irradiancia y la generación real, no la potencia nominal instalada.",
        )
        if st.session_state.climate_condition == "Personalizado":
            st.slider("Factor de irradiancia", min_value=0.05, max_value=1.20, step=0.01, key="custom_weather_factor")
        else:
            st.caption(f"Factor aplicado: {CLIMATE_FACTORS[st.session_state.climate_condition]:.2f}")

    if source == "PVGIS con pvlib.iotools":
        st.selectbox(
            "Base PVGIS",
            options=["Automático", "PVGIS-SARAH3", "PVGIS-ERA5", "PVGIS-SARAH2"],
            key="pvgis_database",
        )

    if source == "NSRDB PSM3 con pvlib.iotools":
        st.text_input("NSRDB API key", key="nsrdb_api_key", type="password")
        st.text_input("Correo registrado en NSRDB", key="nsrdb_email")
        st.selectbox("Intervalo NSRDB [min]", options=[30, 60], key="nsrdb_interval")

    if source in {"PVGIS con pvlib.iotools", "NSRDB PSM3 con pvlib.iotools"}:
        current_signature = current_weather_source_signature(
            source=source,
            latitude=float(st.session_state.latitude),
            longitude=float(st.session_state.longitude),
            year=int(st.session_state.year),
            timezone=str(st.session_state.timezone),
            pvgis_database=str(st.session_state.get("pvgis_database", "Automático")),
            nsrdb_interval=int(st.session_state.get("nsrdb_interval", 30)),
        )
        loaded_signature = st.session_state.get("external_irradiance_signature")
        if external_irradiance_signature_matches(loaded_signature, current_signature):
            st.success(f"Datos solares externos cargados: {st.session_state.get('external_irradiance_label', '')}")
        elif loaded_signature is not None:
            log_weather_signature_mismatch(source, current_signature, loaded_signature, st.session_state.get("external_irradiance_df"))
            st.warning("Los datos externos cargados no coinciden con la configuración actual.")
        else:
            st.info("Datos solares externos no cargados. Se usa cielo despejado temporalmente hasta cargarlos.")
        if st.button("Cargar datos solares externos", key="advanced_load_external_irradiance", use_container_width=True):
            st.session_state.load_external_irradiance_requested = True
            st.rerun()

    st.selectbox("Modelo de transposición POA", options=["isotropic", "haydavies", "perez"], key="transposition_model")
    st.slider("Albedo", min_value=0.05, max_value=0.60, step=0.01, key="albedo")


def main() -> None:
    apply_pending_location_update()
    apply_auto_timezone_update()
    app_header()
    pv_config, demand_config, tariff_config = build_sidebar()
    irradiance_df, irradiance_label = get_irradiance_data_or_none(pv_config)
    demand_df = get_demand_data_or_none(pv_config, demand_config)

    with st.spinner("Ejecutando simulación..."):
        df = run_simulation(pv_config, demand_config, irradiance_df, irradiance_label, demand_df)
        df = add_tariff_columns(df, tariff_config)
        monthly_tariff = monthly_tariff_summary(df, tariff_config)
        annual_tariff = annual_tariff_summary(monthly_tariff)

    summary = compute_summary(df=df, installed_power_kw=pv_config.installed_power_kw, total_area_m2=pv_config.total_area_m2)

    tab_diagnosis, tab_savings, tab_backup, tab_profitability, tab_advanced = st.tabs(
        [
            "Diagnóstico solar",
            "Consumo y ahorro",
            "Respaldo",
            "Rentabilidad",
            "Avanzado",
        ]
    )

    with tab_diagnosis:
        render_quick_solar_diagnosis_tab(df, summary, demand_config, demand_df)
    with tab_savings:
        render_stage2_savings_wizard(df, summary, monthly_tariff, annual_tariff)
    with tab_backup:
        render_stage3_backup_wizard()
    with tab_profitability:
        render_stage4_profitability_wizard(summary)
    with tab_advanced:
        render_advanced_solar_controls()
        st.divider()
        render_charts_tab(df)
        st.divider()
        render_data_source_tab(df)
        st.divider()
        render_results_tab(df, summary, monthly_tariff, annual_tariff, None)


if __name__ == "__main__":
    main()
