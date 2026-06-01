from __future__ import annotations

import os
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
from src.irradiance_data import (
    fetch_nasa_power_hourly,
    fetch_nsrdb_psm3,
    fetch_pvgis_hourly,
    read_uploaded_irradiance,
    to_15min_irradiance,
)
from src.plotting import (
    plot_daily_generation_vs_demand,
    plot_daily_irradiance,
    plot_hourly_average,
    plot_monthly_energy,
    plot_monthly_energy_balance,
    plot_monthly_tariff_savings,
    plot_net_energy_flow,
    plot_poa_components,
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
    page_title="Simulador Fotovoltaico GDMTH",
    layout="wide",
    initial_sidebar_state="expanded",
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
    "year": 2026,
    "panel_power_w": 550.0,
    "panel_area_m2": 2.5,
    "panel_efficiency_percent": 22.0,
    "number_of_panels": 60,
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
    "load_external_irradiance_requested": False,
    "timezone": DEFAULT_TIMEZONE,
    "transposition_model": "isotropic",
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
}

for key, value in DEFAULT_STATE.items():
    st.session_state.setdefault(key, value)


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


def external_irradiance_signature(
    source: str,
    latitude: float,
    longitude: float,
    year: int,
    timezone: str,
    pvgis_database: str | None = None,
    nsrdb_interval: int | None = None,
) -> tuple:
    signature: tuple = (
        str(source),
        round(float(latitude), 6),
        round(float(longitude), 6),
        int(year),
        str(timezone),
    )
    if source == "PVGIS con pvlib.iotools":
        return signature + (str(pvgis_database or "Automático"),)
    if source == "NSRDB PSM3 con pvlib.iotools":
        return signature + (int(nsrdb_interval or 30),)
    return signature


def current_external_irradiance_signature(pv_config: PVSystemConfig) -> tuple:
    return external_irradiance_signature(
        source=str(st.session_state.irradiance_source),
        latitude=pv_config.latitude,
        longitude=pv_config.longitude,
        year=pv_config.year,
        timezone=pv_config.timezone,
        pvgis_database=str(st.session_state.get("pvgis_database", "Automático")),
        nsrdb_interval=int(st.session_state.get("nsrdb_interval", 30)),
    )


def external_irradiance_signature_matches(loaded_signature: tuple | None, current_signature: tuple) -> bool:
    return loaded_signature is not None and tuple(loaded_signature) == tuple(current_signature)


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
def load_nasa_irradiance(latitude: float, longitude: float, year: int, timezone: str) -> pd.DataFrame:
    hourly = fetch_nasa_power_hourly(latitude=latitude, longitude=longitude, year=year)
    return to_15min_irradiance(hourly, year=year, timezone=timezone)


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


def build_sidebar() -> tuple[PVSystemConfig, DemandConfig, TariffConfig]:
    st.sidebar.title("Configuración")
    st.sidebar.caption("Parámetros principales del modelo validado.")

    with st.sidebar.expander("Ubicación y recurso solar", expanded=True):
        st.number_input("Año de simulación", min_value=2018, max_value=2035, step=1, key="year")
        st.number_input("Latitud", format="%.6f", key="latitude", on_change=register_manual_location_change)
        st.number_input("Longitud", format="%.6f", key="longitude", on_change=register_manual_location_change)
        st.number_input(
            "Altitud [m]",
            min_value=0.0,
            max_value=5000.0,
            step=10.0,
            key="altitude_m",
            on_change=register_manual_location_change,
            args=(False,),
        )
        st.checkbox("Actualizar altitud al cambiar ubicación", key="auto_altitude")
        st.checkbox(
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

    with st.sidebar.expander("Fuente de irradiancia y POA", expanded=True):
        current_source = str(st.session_state.get("irradiance_source", DEFAULT_IRRADIANCE_SOURCE))
        if current_source not in IRRADIANCE_SOURCES:
            current_source = DEFAULT_IRRADIANCE_SOURCE
            st.session_state.irradiance_source = current_source
        if st.session_state.get("irradiance_source_group") not in IRRADIANCE_SOURCE_GROUPS:
            st.session_state.irradiance_source_group = IRRADIANCE_SOURCE_GROUP_BY_SOURCE.get(
                current_source,
                "Fuente principal del MVP",
            )

        st.radio(
            "Tipo de fuente de irradiancia",
            options=IRRADIANCE_SOURCE_GROUPS,
            key="irradiance_source_group",
            help="Usa las fuentes principales para el MVP. Las fuentes externas son avanzadas y se cargan bajo demanda.",
        )

        if st.session_state.irradiance_source_group == "Fuente principal del MVP":
            if st.session_state.irradiance_source not in PRIMARY_IRRADIANCE_SOURCES:
                st.session_state.irradiance_source = DEFAULT_IRRADIANCE_SOURCE
            st.selectbox(
                "Fuente de irradiancia principal",
                options=PRIMARY_IRRADIANCE_SOURCES,
                key="irradiance_source",
                help="Opciones estables para la entrega: cielo despejado, escenario climático simple o archivo propio.",
            )
        else:
            if st.session_state.irradiance_source not in ADVANCED_IRRADIANCE_SOURCES:
                st.session_state.irradiance_source = ADVANCED_IRRADIANCE_SOURCES[0]
            st.selectbox(
                "Fuente solar externa avanzada",
                options=ADVANCED_IRRADIANCE_SOURCES,
                key="irradiance_source",
                format_func=lambda source: ADVANCED_IRRADIANCE_LABELS.get(source, source),
                help="PVGIS, NASA POWER y NSRDB no se descargan automáticamente; debes presionar Cargar datos solares externos.",
            )

        if st.session_state.irradiance_source == "Escenario climático simple":
            st.selectbox(
                "Condición atmosférica",
                options=list(CLIMATE_FACTORS.keys()),
                key="climate_condition",
                help=(
                    "Los factores climáticos modifican la irradiancia y por tanto la generación real, "
                    "pero no cambian la potencia nominal instalada."
                ),
            )
            if st.session_state.climate_condition == "Personalizado":
                st.slider(
                    "Factor de irradiancia",
                    min_value=0.05,
                    max_value=1.20,
                    step=0.01,
                    key="custom_weather_factor",
                    help=(
                        "Multiplica GHI, DNI y DHI antes del cálculo POA. Afecta la generación simulada, "
                        "no la potencia nominal del sistema."
                    ),
                )
            else:
                st.caption(f"Factor aplicado: {CLIMATE_FACTORS[st.session_state.climate_condition]:.2f}")

        if st.session_state.irradiance_source == "PVGIS con pvlib.iotools":
            st.selectbox(
                "Base PVGIS",
                options=["Automático", "PVGIS-SARAH3", "PVGIS-ERA5", "PVGIS-SARAH2"],
                key="pvgis_database",
                help="Automático deja que PVGIS elija la base disponible para la ubicación.",
            )

        if st.session_state.irradiance_source == "NSRDB PSM3 con pvlib.iotools":
            st.text_input("NSRDB API key", key="nsrdb_api_key", type="password")
            st.text_input("Correo registrado en NSRDB", key="nsrdb_email")
            st.selectbox("Intervalo NSRDB [min]", options=[30, 60], key="nsrdb_interval")

        if st.session_state.irradiance_source in EXTERNAL_IRRADIANCE_SOURCES:
            current_signature = external_irradiance_signature(
                source=str(st.session_state.irradiance_source),
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
                st.warning("Los datos externos cargados no coinciden con la configuración actual.")
            else:
                st.info("Datos solares externos no cargados. Se usará cielo despejado temporalmente hasta cargarlos.")

            if st.button("Cargar datos solares externos", use_container_width=True):
                st.session_state.load_external_irradiance_requested = True

        if st.session_state.irradiance_source == "CSV propio":
            st.file_uploader(
                "Archivo CSV o Excel",
                type=["csv", "xlsx", "xls"],
                key="uploaded_irradiance_file",
                help="Columnas mínimas: datetime y ghi. Opcionales: dni, dhi, temp_air, wind_speed.",
            )

        timezone_options = get_timezone_select_options()

        st.selectbox(
            "Zona horaria",
            options=timezone_options,
            key="timezone",
            help=(
                "La zona horaria afecta posición solar, demanda real y periodos tarifarios. "
                "Para Monterrey se recomienda America/Monterrey."
            ),
        )
        st.selectbox(
            "Modelo de transposición POA",
            options=["isotropic", "haydavies", "perez"],
            key="transposition_model",
            help="Transpone GHI/DNI/DHI al plano del arreglo con pvlib.",
        )
        st.slider("Albedo", min_value=0.05, max_value=0.60, step=0.01, key="albedo")

    with st.sidebar.expander("Sistema fotovoltaico", expanded=True):
        st.number_input("Potencia por panel [W]", min_value=100.0, max_value=800.0, step=10.0, key="panel_power_w")
        st.number_input("Área por panel [m2]", min_value=1.0, max_value=4.0, step=0.1, key="panel_area_m2")
        st.slider("Eficiencia del panel [%]", min_value=10.0, max_value=25.0, step=0.1, key="panel_efficiency_percent")
        st.number_input("Número de paneles", min_value=1, max_value=2000, step=1, key="number_of_panels")
        st.slider(
            "Pérdidas del sistema [%]",
            min_value=0.0,
            max_value=30.0,
            step=0.5,
            key="system_losses_percent",
            help=(
                "Pérdidas agregadas por inversor, cableado, suciedad, mismatch, disponibilidad "
                "y otros efectos no modelados individualmente."
            ),
        )
        st.slider("Inclinación, tilt [deg]", min_value=0, max_value=60, step=1, key="tilt_deg")
        st.slider("Orientación, azimuth [deg]", min_value=0, max_value=360, step=5, key="azimuth_deg")
        st.caption("Referencia: 180 deg representa orientación sur en el hemisferio norte.")

    with st.sidebar.expander("Demanda", expanded=True):
        st.selectbox("Modo de demanda", options=["Demanda sintética", "Demanda cargada por archivo"], key="demand_mode")
        st.slider(
            "Factor de potencia",
            min_value=0.70,
            max_value=0.95,
            step=0.01,
            key="power_factor",
            help="En demanda sintética calcula kVA. En demanda real se usa si el archivo no trae power_factor.",
        )
        if st.session_state.demand_mode == "Demanda cargada por archivo":
            st.file_uploader(
                "Archivo CSV o Excel de demanda",
                type=["csv", "xlsx", "xls"],
                key="uploaded_demand_file",
                help="Columnas mínimas: datetime y demand_kW. Opcionales: demand_energy_kWh y power_factor.",
            )
            st.caption("La demanda real se valida y se ajusta a intervalos de 15 minutos.")
        else:
            st.selectbox("Demanda máxima [kW]", options=[30.0, 50.0, 60.0], key="max_demand_kw")
            st.slider("Factor de planta", min_value=0.50, max_value=0.70, step=0.01, key="plant_factor")
            st.slider("Reducción en fin de semana", min_value=0.00, max_value=0.60, step=0.01, key="weekend_reduction")
            st.slider("Incremento en verano", min_value=0.00, max_value=0.25, step=0.01, key="summer_increase")
            st.number_input("Semilla de variabilidad", min_value=1, max_value=9999, step=1, key="random_seed")
            st.caption("La demanda sintética genera una curva anual quinceminutal con verano y fines de semana.")

    with st.sidebar.expander("Tarifa GDMTH", expanded=True):
        st.caption("Estimación académica: periodos horarios, demanda facturable, factor de potencia e IVA. No sustituye factura oficial CFE.")
        st.number_input("Cargo fijo mensual [MXN]", min_value=0.0, step=50.0, key="fixed_monthly_charge_mxn")
        st.number_input("Cargo base [MXN/kWh]", min_value=0.0, step=0.05, key="base_rate_mxn_kwh")
        st.number_input("Cargo intermedio [MXN/kWh]", min_value=0.0, step=0.05, key="intermediate_rate_mxn_kwh")
        st.number_input("Cargo punta [MXN/kWh]", min_value=0.0, step=0.05, key="peak_rate_mxn_kwh")
        st.checkbox("Incluir cargo por demanda", key="demand_charge_enabled")
        st.number_input("Cargo distribución [MXN/kW]", min_value=0.0, step=1.0, key="distribution_rate_mxn_kw")
        st.number_input("Cargo capacidad [MXN/kW]", min_value=0.0, step=10.0, key="capacity_rate_mxn_kw")
        st.number_input("IVA [%]", min_value=0.0, max_value=30.0, step=1.0, key="iva_rate_percent")
        st.caption("El factor de potencia se calcula desde kVA/reactivos si existen; si no, usa el factor configurado.")

    weather_factor, weather_condition = get_weather_adjustment()

    pv_config = PVSystemConfig(
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
                        data = load_nasa_irradiance(
                            pv_config.latitude,
                            pv_config.longitude,
                            pv_config.year,
                            pv_config.timezone,
                        )
                    label = "NASA POWER"

                st.session_state.external_irradiance_df = data
                st.session_state.external_irradiance_signature = current_signature
                st.session_state.external_irradiance_label = label
                st.success(f"Datos solares externos cargados: {label}")
                return data, label
            except Exception as exc:
                st.error(f"No se pudo cargar la fuente externa seleccionada. Se usa cielo despejado temporalmente. Detalle: {exc}")
                return None, "Cielo despejado con pvlib Ineichen"

        loaded_data = st.session_state.get("external_irradiance_df")
        loaded_signature = st.session_state.get("external_irradiance_signature")
        if isinstance(loaded_data, pd.DataFrame) and external_irradiance_signature_matches(
            loaded_signature,
            current_signature,
        ):
            return loaded_data, str(st.session_state.get("external_irradiance_label", source))

        if loaded_signature is not None:
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

    st.subheader("Vista previa de irradiancia usada en la simulación")
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


def render_simulation_tab(df: pd.DataFrame, summary: dict[str, float]) -> None:
    section_header(
        "Resultados energéticos",
        "Generación fotovoltaica, demanda, autoconsumo, energía de red y exportación.",
        icon_name="bolt",
    )

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
        st.plotly_chart(plot_daily_generation_vs_demand(df_day), use_container_width=True)

    st.subheader("Balance mensual")
    st.caption("Resume generación, demanda, autoconsumo, energía de red y exportación durante el año.")
    st.plotly_chart(plot_monthly_energy(df), use_container_width=True)
    st.plotly_chart(plot_monthly_energy_balance(df), use_container_width=True)


def render_charts_tab(df: pd.DataFrame) -> None:
    section_header(
        "Gráficas y análisis",
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
    st.plotly_chart(plot_daily_irradiance(df_day), use_container_width=True)
    st.plotly_chart(plot_poa_components(df_day), use_container_width=True)

    st.subheader("Análisis anual secundario")
    st.caption("Resume el balance anual y el perfil horario promedio para detectar patrones generales.")
    st.plotly_chart(plot_net_energy_flow(df), use_container_width=True)
    st.plotly_chart(plot_hourly_average(df), use_container_width=True)


def render_tariff_tab(monthly_tariff: pd.DataFrame, annual_tariff: dict[str, float]) -> None:
    section_header(
        "Resultados económicos GDMTH",
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
    st.plotly_chart(plot_monthly_tariff_savings(monthly_tariff), use_container_width=True)
    st.plotly_chart(plot_tariff_energy_by_period(monthly_tariff), use_container_width=True)
    st.plotly_chart(plot_tariff_component_breakdown(monthly_tariff), use_container_width=True)

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
        st.plotly_chart(plot_scenario_generation(scenarios_df), use_container_width=True)
        st.plotly_chart(plot_scenario_coverage(scenarios_df), use_container_width=True)
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
        "Datos y exportación",
        "Serie temporal, resumen técnico y descargas disponibles.",
        icon_name="table",
    )

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

    tab_resource, tab_energy, tab_economic, tab_charts, tab_data = st.tabs(
        ["Ubicación y recurso", "Resultados energéticos", "Resultados económicos", "Gráficas", "Datos/exportación"]
    )

    with tab_resource:
        render_location_tab()
        st.divider()
        render_data_source_tab(df)
    with tab_energy:
        render_simulation_tab(df, summary)
    with tab_economic:
        render_tariff_tab(monthly_tariff, annual_tariff)
    with tab_charts:
        render_charts_tab(df)
    with tab_data:
        render_results_tab(df, summary, monthly_tariff, annual_tariff, None)


if __name__ == "__main__":
    main()
