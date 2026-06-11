from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PVSystemConfig:
    year: int
    latitude: float
    longitude: float
    altitude_m: float
    tilt_deg: float
    azimuth_deg: float
    panel_power_w: float
    panel_area_m2: float
    panel_efficiency: float
    number_of_panels: int
    albedo: float
    system_losses: float
    timezone: str = "Etc/GMT+6"
    transposition_model: str = "haydavies"
    weather_adjustment_factor: float = 1.0
    weather_condition: str = "Cielo despejado"
    temperature_coefficient_per_c: float = -0.004

    @property
    def installed_power_kw(self) -> float:
        return self.panel_power_w * self.number_of_panels / 1000.0

    @property
    def total_area_m2(self) -> float:
        return self.panel_area_m2 * self.number_of_panels

    @property
    def module_power_from_area_w(self) -> float:
        return self.panel_area_m2 * self.panel_efficiency * 1000.0

    @property
    def estimated_panel_power_w(self) -> float:
        return self.module_power_from_area_w

    @property
    def installed_power_from_area_kw(self) -> float:
        return self.module_power_from_area_w * self.number_of_panels / 1000.0


def _require_pvlib() -> Any:
    """Import pvlib only when the solar engine is executed."""
    try:
        import pvlib  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pvlib is required for the photovoltaic simulation. "
            "Install the project dependencies with: pip install -r requirements.txt"
        ) from exc
    return pvlib


def validate_pv_system_config(config: PVSystemConfig, tolerance: float = 0.10) -> None:
    """Validate PV inputs that must be physically valid before simulation."""
    if not (-90.0 <= config.latitude <= 90.0):
        raise ValueError("La latitud debe estar entre -90 y 90 grados.")
    if not (-180.0 <= config.longitude <= 180.0):
        raise ValueError("La longitud debe estar entre -180 y 180 grados.")
    if config.panel_power_w <= 0:
        raise ValueError("La potencia nominal del panel debe ser positiva.")
    if config.panel_area_m2 <= 0:
        raise ValueError("El area del panel debe ser positiva.")
    if not (0.0 < config.panel_efficiency <= 1.0):
        raise ValueError("La eficiencia del panel debe estar entre 0 y 100%.")
    if config.number_of_panels <= 0:
        raise ValueError("El numero de paneles debe ser positivo.")
    if not (0.0 <= config.system_losses < 1.0):
        raise ValueError("Las perdidas del sistema deben estar entre 0 y 100%.")
    if not (0.0 <= config.albedo <= 1.0):
        raise ValueError("El albedo debe estar entre 0 y 1.")


def panel_power_consistency_warning(config: PVSystemConfig, tolerance: float = 0.10) -> str:
    """Return a non-blocking warning when Wp differs from area x efficiency."""
    estimated_power_w = config.estimated_panel_power_w
    relative_difference = abs(estimated_power_w - config.panel_power_w) / config.panel_power_w
    if relative_difference > tolerance:
        return (
            "Advertencia: la potencia nominal del panel no coincide con area x eficiencia x 1000 W/m2. "
            f"Con {config.panel_area_m2:.2f} m2 y {100 * config.panel_efficiency:.1f}% se obtienen "
            f"{estimated_power_w:.0f} W, pero se ingresaron {config.panel_power_w:.0f} W. "
            "La simulacion usa la potencia nominal ingresada como base de generacion."
        )
    return ""


def generate_time_index(year: int, timezone: str = "Etc/GMT+6") -> pd.DatetimeIndex:
    """Return a timezone-aware 15-minute time index for a complete year."""
    start = pd.Timestamp(f"{year}-01-01 00:00:00", tz=timezone)
    end = pd.Timestamp(f"{year}-12-31 23:45:00", tz=timezone)
    return pd.date_range(start=start, end=end, freq="15min")


def _standardize_external_irradiance(
    times: pd.DatetimeIndex,
    irradiance_df: pd.DataFrame | None,
    timezone: str,
) -> pd.DataFrame | None:
    """
    Align an external irradiance table to the simulation time index.

    Required columns: datetime and GHI_W_m2.
    Optional columns: DNI_W_m2, DHI_W_m2, temperature_C and wind_speed_m_s.
    """
    if irradiance_df is None or irradiance_df.empty:
        return None
    if "datetime" not in irradiance_df.columns or "GHI_W_m2" not in irradiance_df.columns:
        return None

    external = irradiance_df.copy()
    external["datetime"] = pd.to_datetime(external["datetime"])

    if external["datetime"].dt.tz is None:
        external["datetime"] = external["datetime"].dt.tz_localize(timezone)
    else:
        external["datetime"] = external["datetime"].dt.tz_convert(timezone)

    keep_columns = ["datetime", "GHI_W_m2"]
    for optional_column in ["DNI_W_m2", "DHI_W_m2", "temperature_C", "wind_speed_m_s"]:
        if optional_column in external.columns:
            keep_columns.append(optional_column)

    external = external[keep_columns]
    external = external.drop_duplicates("datetime").set_index("datetime").sort_index()
    external = external.reindex(times.union(external.index)).interpolate(method="time").reindex(times)
    external = external.ffill().bfill().fillna(0.0)

    for column in ["GHI_W_m2", "DNI_W_m2", "DHI_W_m2"]:
        if column in external.columns:
            external[column] = external[column].clip(lower=0.0)

    return external.reset_index().rename(columns={"index": "datetime"})


def _build_pvlib_weather_components(
    times: pd.DatetimeIndex,
    solar_position: pd.DataFrame,
    config: PVSystemConfig,
    external_irradiance: pd.DataFrame | None,
) -> tuple[pd.DataFrame, str]:
    """
    Build GHI, DNI and DHI using pvlib.

    Without external data, pvlib's Ineichen clear-sky model is used. With external
    data from pvlib.iotools, NASA POWER or CSV, the provided GHI is aligned to the
    simulation index and DNI/DHI are used when available. If external DNI/DHI are
    missing, pvlib.irradiance.erbs decomposes GHI into DNI and DHI.
    """
    pvlib = _require_pvlib()

    if external_irradiance is None:
        site = pvlib.location.Location(
            latitude=config.latitude,
            longitude=config.longitude,
            tz=config.timezone,
            altitude=config.altitude_m,
        )
        clearsky = site.get_clearsky(
            times,
            model="ineichen",
            solar_position=solar_position,
        )
        weather = pd.DataFrame(
            {
                "GHI_W_m2": clearsky["ghi"].to_numpy(dtype=float),
                "DNI_W_m2": clearsky["dni"].to_numpy(dtype=float),
                "DHI_W_m2": clearsky["dhi"].to_numpy(dtype=float),
                "temperature_C": np.full(len(times), 25.0),
                "wind_speed_m_s": np.full(len(times), 1.0),
            },
            index=times,
        ).clip(lower=0.0)

        factor = float(np.clip(config.weather_adjustment_factor, 0.0, 1.5))
        if factor != 1.0:
            weather[["GHI_W_m2", "DNI_W_m2", "DHI_W_m2"]] = weather[["GHI_W_m2", "DNI_W_m2", "DHI_W_m2"]] * factor
            return weather.clip(lower=0.0), f"pvlib Ineichen ajustado ({config.weather_condition})"

        return weather, "pvlib Ineichen cielo despejado"

    weather = external_irradiance.set_index("datetime").reindex(times)
    weather["GHI_W_m2"] = weather["GHI_W_m2"].clip(lower=0.0)

    has_dni = "DNI_W_m2" in weather.columns and weather["DNI_W_m2"].notna().any()
    has_dhi = "DHI_W_m2" in weather.columns and weather["DHI_W_m2"].notna().any()

    if not (has_dni and has_dhi):
        erbs = pvlib.irradiance.erbs(
            ghi=weather["GHI_W_m2"],
            zenith=solar_position["apparent_zenith"],
            datetime_or_doy=times,
        )
        weather["DNI_W_m2"] = erbs["dni"].to_numpy(dtype=float)
        weather["DHI_W_m2"] = erbs["dhi"].to_numpy(dtype=float)
        detail = "Externo con GHI + pvlib Erbs"
    else:
        weather["DNI_W_m2"] = weather["DNI_W_m2"].clip(lower=0.0)
        weather["DHI_W_m2"] = weather["DHI_W_m2"].clip(lower=0.0)
        detail = "Externo con GHI, DNI y DHI"

    if "temperature_C" not in weather.columns:
        weather["temperature_C"] = 25.0
    if "wind_speed_m_s" not in weather.columns:
        weather["wind_speed_m_s"] = 1.0

    weather = weather[["GHI_W_m2", "DNI_W_m2", "DHI_W_m2", "temperature_C", "wind_speed_m_s"]].copy()
    weather[["GHI_W_m2", "DNI_W_m2", "DHI_W_m2"]] = weather[
        ["GHI_W_m2", "DNI_W_m2", "DHI_W_m2"]
    ].clip(lower=0.0)
    weather["wind_speed_m_s"] = weather["wind_speed_m_s"].clip(lower=0.0)
    return weather, detail


def pvlib_poa_transposition(
    config: PVSystemConfig,
    times: pd.DatetimeIndex,
    solar_position: pd.DataFrame,
    weather: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate POA irradiance with pvlib.irradiance.get_total_irradiance.

    This is the central transposition step after GHI, DNI and DHI are obtained from
    clear-sky modeling, pvlib.iotools, NASA POWER or CSV.
    """
    pvlib = _require_pvlib()

    model = config.transposition_model.lower().strip()
    kwargs: dict[str, Any] = {}

    if model in {"haydavies", "reindl", "perez", "perez-driesse"}:
        kwargs["dni_extra"] = pvlib.irradiance.get_extra_radiation(times)

    if model in {"perez", "perez-driesse"}:
        kwargs["airmass"] = pvlib.atmosphere.get_relative_airmass(
            solar_position["apparent_zenith"]
        )

    try:
        total = pvlib.irradiance.get_total_irradiance(
            surface_tilt=config.tilt_deg,
            surface_azimuth=config.azimuth_deg,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"],
            dni=weather["DNI_W_m2"],
            ghi=weather["GHI_W_m2"],
            dhi=weather["DHI_W_m2"],
            albedo=config.albedo,
            model=model,
            **kwargs,
        )
        model_used = model
    except Exception:
        if model == "isotropic":
            raise
        total = pvlib.irradiance.get_total_irradiance(
            surface_tilt=config.tilt_deg,
            surface_azimuth=config.azimuth_deg,
            solar_zenith=solar_position["apparent_zenith"],
            solar_azimuth=solar_position["azimuth"],
            dni=weather["DNI_W_m2"],
            ghi=weather["GHI_W_m2"],
            dhi=weather["DHI_W_m2"],
            albedo=config.albedo,
            model="isotropic",
        )
        model_used = "isotropic"

    poa = pd.DataFrame(
        {
            "POA_W_m2": total["poa_global"].to_numpy(dtype=float),
            "POA_beam_W_m2": total["poa_direct"].to_numpy(dtype=float),
            "POA_diffuse_W_m2": total["poa_diffuse"].to_numpy(dtype=float),
            "POA_ground_W_m2": total["poa_ground_diffuse"].to_numpy(dtype=float),
            "POA_sky_diffuse_W_m2": total["poa_sky_diffuse"].to_numpy(dtype=float),
        },
        index=times,
    )

    poa = poa.clip(lower=0.0)
    poa.attrs["transposition_model_used"] = model_used
    return poa


def jensen_poa_transposition(
    config: PVSystemConfig,
    times: pd.DatetimeIndex,
    solar_position: pd.DataFrame,
    weather: pd.DataFrame,
) -> pd.DataFrame:
    """
    Course-compatible wrapper for the pvlib POA transposition step.

    The Jensen et al. paper supplied for the project focuses on pvlib.iotools and
    standardized access to irradiance datasets. In this application, the Jensen/pvlib
    workflow means: retrieve or prepare irradiance data, calculate solar position,
    transpose GHI/DNI/DHI to POA with pvlib, and estimate PV generation.
    """
    return pvlib_poa_transposition(config, times, solar_position, weather)


# Backward-compatible alias for older imports.
jensen_ready_poa_transposition = jensen_poa_transposition


def simulate_pv_system(
    config: PVSystemConfig,
    irradiance_df: pd.DataFrame | None = None,
    irradiance_source_label: str = "Cielo despejado",
) -> pd.DataFrame:
    """Generate a 15-minute PV simulation table using pvlib."""
    pvlib = _require_pvlib()
    validate_pv_system_config(config)

    times = generate_time_index(config.year, config.timezone)
    external_irradiance = _standardize_external_irradiance(times, irradiance_df, config.timezone)

    solar_position = pvlib.solarposition.get_solarposition(
        time=times,
        latitude=config.latitude,
        longitude=config.longitude,
        altitude=config.altitude_m,
    )

    weather, weather_detail = _build_pvlib_weather_components(
        times=times,
        solar_position=solar_position,
        config=config,
        external_irradiance=external_irradiance,
    )

    poa = jensen_poa_transposition(
        config=config,
        times=times,
        solar_position=solar_position,
        weather=weather,
    )

    cell_temperature_c = pvlib.temperature.faiman(
        poa_global=poa["POA_W_m2"],
        temp_air=weather["temperature_C"],
        wind_speed=weather["wind_speed_m_s"],
    )
    temperature_factor = 1.0 + config.temperature_coefficient_per_c * (cell_temperature_c.to_numpy(dtype=float) - 25.0)
    temperature_factor = np.clip(temperature_factor, 0.0, 1.20)

    raw_generation_kw = config.installed_power_kw * (poa["POA_W_m2"].to_numpy(dtype=float) / 1000.0) * temperature_factor
    loss_factor = max(0.0, 1.0 - config.system_losses)
    generation_kw = np.maximum(raw_generation_kw * loss_factor, 0.0)
    energy_kwh = generation_kw * 0.25
    consistency_warning = panel_power_consistency_warning(config)
    panel_power_relative_difference = abs(config.estimated_panel_power_w - config.panel_power_w) / config.panel_power_w

    source = irradiance_source_label

    df = pd.DataFrame(
        {
            "datetime": times,
            "latitude": config.latitude,
            "longitude": config.longitude,
            "altitude_m": config.altitude_m,
            "timezone": config.timezone,
            "irradiance_source": source,
            "weather_model_detail": weather_detail,
            "weather_condition": config.weather_condition,
            "weather_adjustment_factor": config.weather_adjustment_factor,
            "transposition_model": poa.attrs.get("transposition_model_used", config.transposition_model),
            "installed_power_kw": config.installed_power_kw,
            "estimated_panel_power_w": config.estimated_panel_power_w,
            "module_power_from_area_w": config.module_power_from_area_w,
            "installed_power_from_area_kw": config.installed_power_from_area_kw,
            "panel_power_relative_difference": panel_power_relative_difference,
            "panel_power_consistency_warning": consistency_warning,
            "solar_elevation_deg": solar_position["apparent_elevation"].to_numpy(dtype=float),
            "solar_azimuth_deg": solar_position["azimuth"].to_numpy(dtype=float),
            "solar_zenith_deg": solar_position["apparent_zenith"].to_numpy(dtype=float),
            "GHI_W_m2": weather["GHI_W_m2"].to_numpy(dtype=float),
            "DHI_W_m2": weather["DHI_W_m2"].to_numpy(dtype=float),
            "DNI_W_m2": weather["DNI_W_m2"].to_numpy(dtype=float),
            "temperature_C": weather["temperature_C"].to_numpy(dtype=float),
            "wind_speed_m_s": weather["wind_speed_m_s"].to_numpy(dtype=float),
            "cell_temperature_C": cell_temperature_c.to_numpy(dtype=float),
            "POA_beam_W_m2": poa["POA_beam_W_m2"].to_numpy(dtype=float),
            "POA_diffuse_W_m2": poa["POA_diffuse_W_m2"].to_numpy(dtype=float),
            "POA_sky_diffuse_W_m2": poa["POA_sky_diffuse_W_m2"].to_numpy(dtype=float),
            "POA_ground_W_m2": poa["POA_ground_W_m2"].to_numpy(dtype=float),
            "POA_W_m2": poa["POA_W_m2"].to_numpy(dtype=float),
            "raw_dc_power_kW": raw_generation_kw,
            "generation_kW": generation_kw,
            "energy_kWh": energy_kwh,
        }
    )

    df["date"] = df["datetime"].dt.date
    df["month"] = df["datetime"].dt.month
    df["month_name"] = df["datetime"].dt.strftime("%b")
    df["hour"] = df["datetime"].dt.hour
    df["day_of_year"] = df["datetime"].dt.dayofyear
    df["weekday"] = df["datetime"].dt.dayofweek
    df["is_weekend"] = df["weekday"] >= 5

    return df
