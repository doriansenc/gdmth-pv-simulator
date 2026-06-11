from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import Any

import pandas as pd
import requests


NASA_POWER_PARAMETERS = ["ghi", "dni", "dhi", "temp_air", "wind_speed"]
NASA_MIN_COVERAGE_FRACTION = 0.95


@dataclass(frozen=True)
class IrradianceDataConfig:
    source: str
    timeout_seconds: int = 30


COLUMN_ALIASES = {
    "GHI_W_m2": [
        "GHI_W_m2", "ghi", "GHI", "Global Horiz", "Global Horizontal Irradiance",
        "global_horizontal_irradiance", "ALLSKY_SFC_SW_DWN", "poa_global_hor",
    ],
    "DNI_W_m2": [
        "DNI_W_m2", "dni", "DNI", "Direct Normal Irradiance", "direct_normal_irradiance",
        "ALLSKY_SFC_SW_DNI",
    ],
    "DHI_W_m2": [
        "DHI_W_m2", "dhi", "DHI", "Diffuse Horizontal Irradiance", "diffuse_horizontal_irradiance",
        "ALLSKY_SFC_SW_DIFF",
    ],
    "temperature_C": [
        "temperature_C", "temp_air", "Temperature", "T2M", "temp_air_C", "air_temperature",
    ],
    "wind_speed_m_s": [
        "wind_speed_m_s", "wind_speed", "Wind Speed", "WS10M", "wind_speed_10m",
    ],
}


def _require_pvlib() -> Any:
    try:
        import pvlib  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "pvlib is required for pvlib.iotools data retrieval. "
            "Install dependencies with: pip install -r requirements.txt"
        ) from exc
    return pvlib


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {str(col).strip().lower(): col for col in columns}
    for alias in aliases:
        key = alias.strip().lower()
        if key in normalized:
            return normalized[key]
    return None


def standardize_irradiance_table(raw: pd.DataFrame, year: int | None = None) -> pd.DataFrame:
    """
    Convert irradiance/weather tables from different providers to the internal schema.

    Output columns use the internal convention:
    datetime, GHI_W_m2, DNI_W_m2, DHI_W_m2, temperature_C, wind_speed_m_s.
    At least GHI_W_m2 must be available. DNI/DHI are optional because the solar engine
    can decompose GHI using pvlib.irradiance.erbs.
    """
    if raw is None or raw.empty:
        raise ValueError("The irradiance table is empty.")

    df = raw.copy()

    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
        index_name = df.columns[0]
        df = df.rename(columns={index_name: "datetime"})
    elif "datetime" not in df.columns:
        datetime_column = _find_column(list(df.columns), ["datetime", "time", "timestamp", "date", "period_end"])
        if datetime_column is None:
            raise ValueError("The irradiance table needs a datetime, time or timestamp column.")
        df = df.rename(columns={datetime_column: "datetime"})

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"])

    output = pd.DataFrame({"datetime": df["datetime"]})
    for output_name, aliases in COLUMN_ALIASES.items():
        input_name = _find_column(list(df.columns), aliases)
        if input_name is not None:
            output[output_name] = pd.to_numeric(df[input_name], errors="coerce")

    if "GHI_W_m2" not in output.columns:
        raise ValueError(
            "No GHI column was found. Provide a column named GHI_W_m2, ghi, GHI or equivalent."
        )

    if year is not None:
        output = output[output["datetime"].dt.year == int(year)]

    output = output.sort_values("datetime").drop_duplicates("datetime")
    output["GHI_W_m2"] = output["GHI_W_m2"].clip(lower=0.0)

    for column in ["DNI_W_m2", "DHI_W_m2"]:
        if column in output.columns:
            output[column] = output[column].clip(lower=0.0)

    # Defensive conversion for providers that return hourly irradiation in kWh/m2.
    daylight = output.loc[output["GHI_W_m2"] > 0, "GHI_W_m2"]
    if not daylight.empty and daylight.quantile(0.90) < 20:
        for column in ["GHI_W_m2", "DNI_W_m2", "DHI_W_m2"]:
            if column in output.columns:
                output[column] = output[column] * 1000.0

    if output.empty:
        raise ValueError("The irradiance table has no records for the selected year.")

    return output.reset_index(drop=True)


def _coerce_datetime_to_timezone(df: pd.DataFrame, timezone: str) -> pd.DataFrame:
    result = df.copy()
    result["datetime"] = pd.to_datetime(result["datetime"], errors="coerce")
    result = result.dropna(subset=["datetime"])
    if result.empty:
        raise ValueError("The irradiance table has no valid datetime records.")

    if result["datetime"].dt.tz is None:
        result["datetime"] = result["datetime"].dt.tz_localize(timezone)
    else:
        result["datetime"] = result["datetime"].dt.tz_convert(timezone)
    return result


def _validate_annual_coverage(df: pd.DataFrame, year: int, min_coverage_fraction: float) -> None:
    days_in_year = 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
    covered_days = df["datetime"].dt.normalize().nunique()
    coverage = covered_days / days_in_year
    if coverage < min_coverage_fraction:
        raise ValueError(
            "The irradiance table does not cover enough of the selected year. "
            f"Covered {covered_days} of {days_in_year} days ({100 * coverage:.1f}%)."
        )

    gaps = df.sort_values("datetime")["datetime"].diff().dropna()
    if not gaps.empty and gaps.max() > pd.Timedelta(days=7):
        raise ValueError(
            "The irradiance table has gaps longer than 7 days. "
            "Use a continuous hourly or sub-hourly annual file."
        )


def annual_coverage_report(df: pd.DataFrame, year: int) -> dict[str, Any]:
    """Return a compact diagnostic report for an annual irradiance table."""
    if df is None or df.empty or "datetime" not in df.columns:
        days_in_year = 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
        return {
            "year": int(year),
            "rows": 0,
            "covered_days": 0,
            "days_in_year": days_in_year,
            "coverage_fraction": 0.0,
            "first_timestamp": "",
            "last_timestamp": "",
            "columns_present": [],
            "columns_missing": ["GHI_W_m2", "DNI_W_m2", "DHI_W_m2", "temperature_C", "wind_speed_m_s"],
        }

    data = df.copy()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data = data.dropna(subset=["datetime"]).sort_values("datetime")
    days_in_year = 366 if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else 365
    covered_days = int(data["datetime"].dt.normalize().nunique())
    expected_columns = ["GHI_W_m2", "DNI_W_m2", "DHI_W_m2", "temperature_C", "wind_speed_m_s"]
    columns_present = [column for column in expected_columns if column in data.columns]
    columns_missing = [column for column in expected_columns if column not in data.columns]
    return {
        "year": int(year),
        "rows": int(len(data)),
        "covered_days": covered_days,
        "days_in_year": days_in_year,
        "coverage_fraction": covered_days / days_in_year if days_in_year else 0.0,
        "first_timestamp": str(data["datetime"].iloc[0]) if not data.empty else "",
        "last_timestamp": str(data["datetime"].iloc[-1]) if not data.empty else "",
        "columns_present": columns_present,
        "columns_missing": columns_missing,
    }


def fetch_nasa_power_hourly(
    latitude: float,
    longitude: float,
    year: int,
    timeout_seconds: int = 30,
) -> pd.DataFrame:
    """
    Fetch hourly irradiance and basic weather data from NASA POWER.

    pvlib.iotools.get_nasa_power is preferred when available because it maps the
    NASA POWER names directly to pvlib conventions (ghi, dni, dhi, temp_air and
    wind_speed). The request uses UTC and includes a one-day buffer on each side;
    downstream code converts to the project timezone and filters the complete
    local reference year.
    """
    pvlib = _require_pvlib()
    start_ts = pd.Timestamp(f"{year}-01-01") - pd.Timedelta(days=1)
    end_ts = pd.Timestamp(f"{year}-12-31") + pd.Timedelta(days=1)
    if hasattr(pvlib.iotools, "get_nasa_power"):
        data, _metadata = pvlib.iotools.get_nasa_power(
            latitude=latitude,
            longitude=longitude,
            start=start_ts,
            end=end_ts,
            parameters=NASA_POWER_PARAMETERS,
            map_variables=True,
        )
        return standardize_irradiance_table(data)

    start = start_ts.strftime("%Y%m%d")
    end = end_ts.strftime("%Y%m%d")
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point"
    params = {
        "parameters": "ALLSKY_SFC_SW_DWN,ALLSKY_SFC_SW_DNI,ALLSKY_SFC_SW_DIFF,T2M,WS10M",
        "community": "RE",
        "longitude": longitude,
        "latitude": latitude,
        "start": start,
        "end": end,
        "format": "JSON",
        "time-standard": "utc",
    }

    response = requests.get(url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    parameters = payload["properties"]["parameter"]

    ghi_series = parameters.get("ALLSKY_SFC_SW_DWN", {})
    dni_series = parameters.get("ALLSKY_SFC_SW_DNI", {})
    dhi_series = parameters.get("ALLSKY_SFC_SW_DIFF", {})
    t2m_series = parameters.get("T2M", {})
    ws_series = parameters.get("WS10M", {})

    records: list[dict[str, float | pd.Timestamp]] = []
    for raw_key, ghi_value in ghi_series.items():
        timestamp = pd.to_datetime(raw_key, format="%Y%m%d%H")
        records.append(
            {
                "datetime": timestamp,
                "GHI_W_m2": float(ghi_value),
                "DNI_W_m2": float(dni_series.get(raw_key, float("nan"))),
                "DHI_W_m2": float(dhi_series.get(raw_key, float("nan"))),
                "temperature_C": float(t2m_series.get(raw_key, float("nan"))),
                "wind_speed_m_s": float(ws_series.get(raw_key, float("nan"))),
            }
        )

    return standardize_irradiance_table(pd.DataFrame(records))


def _coerce_nasa_to_local_reference_year(raw: pd.DataFrame, data_year: int, timezone: str) -> pd.DataFrame:
    data = standardize_irradiance_table(raw)
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    data = data.dropna(subset=["datetime"])
    if data.empty:
        raise ValueError("NASA POWER returned no valid datetime records.")
    # NASA POWER is requested using the UTC time-standard. pvlib returns a UTC
    # DatetimeIndex; the direct requests fallback returns naive UTC timestamps.
    if data["datetime"].dt.tz is None:
        data["datetime"] = data["datetime"].dt.tz_localize("UTC")
    data["datetime"] = data["datetime"].dt.tz_convert(timezone)
    data = data[data["datetime"].dt.year == int(data_year)]
    return data.sort_values("datetime").reset_index(drop=True)


def _remap_reference_year_to_simulation_year(df: pd.DataFrame, simulation_year: int) -> pd.DataFrame:
    result = df.copy()
    timestamps = pd.to_datetime(result["datetime"])
    remapped = []
    for timestamp in timestamps:
        try:
            remapped.append(timestamp.replace(year=int(simulation_year)))
        except ValueError:
            # Drop Feb 29 when a leap reference year is mapped into a non-leap simulation year.
            remapped.append(pd.NaT)
    result["datetime"] = remapped
    result = result.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
    return result


def prepare_nasa_power_irradiance(
    latitude: float,
    longitude: float,
    simulation_year: int,
    nasa_data_year: int,
    timezone: str,
) -> pd.DataFrame:
    """
    Build a complete 15-minute NASA POWER table for the simulation year.

    NASA POWER is requested as UTC hourly data for a complete historical reference
    year, with one-day buffers at both edges. Data are converted to the project
    timezone, filtered to the local reference year, validated at 95% annual
    coverage, remapped to the simulation year, and interpolated to 15 minutes.
    """
    raw = fetch_nasa_power_hourly(latitude=latitude, longitude=longitude, year=nasa_data_year)
    local_reference = _coerce_nasa_to_local_reference_year(raw, nasa_data_year, timezone)
    hourly_report = annual_coverage_report(local_reference, nasa_data_year)
    if hourly_report["coverage_fraction"] < NASA_MIN_COVERAGE_FRACTION:
        raise ValueError(
            "NASA POWER coverage insufficient. "
            f"Data year {nasa_data_year}; covered {hourly_report['covered_days']} of "
            f"{hourly_report['days_in_year']} days ({100 * hourly_report['coverage_fraction']:.1f}%). "
            f"First timestamp: {hourly_report['first_timestamp']}. "
            f"Last timestamp: {hourly_report['last_timestamp']}. "
            f"Columns present: {', '.join(hourly_report['columns_present'])}. "
            f"Columns missing: {', '.join(hourly_report['columns_missing']) or 'none'}."
        )

    remapped = _remap_reference_year_to_simulation_year(local_reference, simulation_year)
    result = to_15min_irradiance(
        remapped,
        year=simulation_year,
        timezone=timezone,
        min_coverage_fraction=NASA_MIN_COVERAGE_FRACTION,
    )
    result.attrs["nasa_power_diagnostics"] = {
        "provider": "pvlib.iotools.get_nasa_power" if hasattr(_require_pvlib().iotools, "get_nasa_power") else "requests",
        "endpoint": "https://power.larc.nasa.gov/api/temporal/hourly/point",
        "parameters": NASA_POWER_PARAMETERS,
        "timezone_strategy": "NASA POWER requested in UTC, converted to project timezone, then remapped to simulation year.",
        "mode": "complete_reference_year",
        "is_provisional": False,
        "simulation_year": int(simulation_year),
        "nasa_data_year": int(nasa_data_year),
        "nasa_requested_year": int(nasa_data_year),
        "base_year": int(nasa_data_year),
        "selected_data_year": int(nasa_data_year),
        "final_weather_year": int(simulation_year),
        "real_days": int(hourly_report["covered_days"]),
        "completed_days": 0,
        "hourly_rows_original": int(len(raw)),
        "hourly_rows_local_reference": int(len(local_reference)),
        "rows_15min": int(len(result)),
        **hourly_report,
    }
    return result


def _empty_irradiance_table() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["datetime", "GHI_W_m2", "DNI_W_m2", "DHI_W_m2", "temperature_C", "wind_speed_m_s"]
    )


def _try_local_nasa_year(latitude: float, longitude: float, year: int, timezone: str) -> pd.DataFrame:
    try:
        raw = fetch_nasa_power_hourly(latitude=latitude, longitude=longitude, year=year)
        return _coerce_nasa_to_local_reference_year(raw, year, timezone)
    except Exception:
        return _empty_irradiance_table()


def prepare_nasa_power_provisional_irradiance(
    latitude: float,
    longitude: float,
    simulation_year: int,
    selected_data_year: int,
    base_year: int,
    timezone: str,
) -> pd.DataFrame:
    """
    Build a complete NASA POWER table using available selected-year data plus a
    complete historical base year for missing timestamps.

    This mode is intended for current or incomplete years. Available records from
    selected_data_year are used first. Missing timestamps are filled with the same
    month, day and hour from base_year, remapped into simulation_year.
    """
    selected_local = _try_local_nasa_year(latitude, longitude, selected_data_year, timezone)

    base_raw = fetch_nasa_power_hourly(latitude=latitude, longitude=longitude, year=base_year)
    base_local = _coerce_nasa_to_local_reference_year(base_raw, base_year, timezone)
    base_report = annual_coverage_report(base_local, base_year)
    if base_report["coverage_fraction"] < NASA_MIN_COVERAGE_FRACTION:
        raise ValueError(
            "NASA POWER base year coverage insufficient. "
            f"Base year {base_year}; covered {base_report['covered_days']} of "
            f"{base_report['days_in_year']} days ({100 * base_report['coverage_fraction']:.1f}%)."
        )

    selected_for_simulation = selected_local.copy()
    if not selected_for_simulation.empty and selected_data_year != simulation_year:
        selected_for_simulation = _remap_reference_year_to_simulation_year(
            selected_for_simulation,
            simulation_year,
        )

    base_for_simulation = _remap_reference_year_to_simulation_year(base_local, simulation_year)
    complete_hourly_index = pd.date_range(
        start=pd.Timestamp(f"{simulation_year}-01-01 00:00:00", tz=timezone),
        end=pd.Timestamp(f"{simulation_year}-12-31 23:00:00", tz=timezone),
        freq="h",
    )

    expected_columns = ["GHI_W_m2", "DNI_W_m2", "DHI_W_m2", "temperature_C", "wind_speed_m_s"]
    base_indexed = (
        base_for_simulation[["datetime", *expected_columns]]
        .drop_duplicates("datetime")
        .set_index("datetime")
        .sort_index()
    )
    selected_indexed = (
        selected_for_simulation[["datetime", *expected_columns]]
        .drop_duplicates("datetime")
        .set_index("datetime")
        .sort_index()
        if not selected_for_simulation.empty
        else pd.DataFrame(columns=expected_columns)
    )

    combined = selected_indexed.combine_first(base_indexed).reindex(complete_hourly_index)
    combined = combined.interpolate(method="time").ffill().bfill()
    combined = combined.reset_index().rename(columns={"index": "datetime"})

    selected_report = annual_coverage_report(selected_for_simulation, simulation_year)
    real_days = int(selected_report["covered_days"])
    days_in_year = 366 if pd.Timestamp(year=simulation_year, month=12, day=31).dayofyear == 366 else 365
    completed_days = max(days_in_year - real_days, 0)

    result = to_15min_irradiance(
        combined,
        year=simulation_year,
        timezone=timezone,
        min_coverage_fraction=NASA_MIN_COVERAGE_FRACTION,
    )
    final_report = annual_coverage_report(result, simulation_year)
    result.attrs["nasa_power_diagnostics"] = {
        "provider": "pvlib.iotools.get_nasa_power" if hasattr(_require_pvlib().iotools, "get_nasa_power") else "requests",
        "endpoint": "https://power.larc.nasa.gov/api/temporal/hourly/point",
        "parameters": NASA_POWER_PARAMETERS,
        "timezone_strategy": "Selected NASA year and base year converted to project timezone before completion.",
        "mode": "provisional_selected_year",
        "is_provisional": True,
        "simulation_year": int(simulation_year),
        "nasa_data_year": int(selected_data_year),
        "nasa_requested_year": int(selected_data_year),
        "selected_data_year": int(selected_data_year),
        "base_year": int(base_year),
        "final_weather_year": int(simulation_year),
        "real_days": real_days,
        "completed_days": completed_days,
        "hourly_rows_selected_year": int(len(selected_local)),
        "hourly_rows_base_year": int(len(base_local)),
        "rows_15min": int(len(result)),
        **final_report,
    }
    return result


def fetch_pvgis_hourly(
    latitude: float,
    longitude: float,
    year: int,
    timeout_seconds: int = 30,
    raddatabase: str | None = None,
) -> pd.DataFrame:
    """
    Fetch hourly irradiance data through pvlib.iotools.get_pvgis_hourly.

    PVGIS is convenient because it does not usually require an API key and can return
    GHI, DNI, DHI and weather variables using pvlib's standardized interface.
    """
    pvlib = _require_pvlib()
    start = pd.Timestamp(f"{year}-01-01")
    end = pd.Timestamp(f"{year}-12-31 23:59")

    kwargs: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "start": start,
        "end": end,
        "components": True,
        "surface_tilt": 0,
        "surface_azimuth": 180,
        "map_variables": True,
        "timeout": timeout_seconds,
    }
    if raddatabase and raddatabase != "Automático":
        kwargs["raddatabase"] = raddatabase

    result = pvlib.iotools.get_pvgis_hourly(**kwargs)
    data = result[0] if isinstance(result, tuple) else result
    lower_columns = {str(col).strip().lower(): col for col in data.columns}
    if "ghi" not in lower_columns and "poa_global" in lower_columns:
        data = data.rename(columns={lower_columns["poa_global"]: "ghi"})
    return standardize_irradiance_table(data, year=year)


def _fetch_nsrdb_psm3_csv(
    latitude: float,
    longitude: float,
    year: int,
    api_key: str,
    email: str,
    interval: int,
    timeout_seconds: int = 60,
) -> pd.DataFrame:
    url = "https://developer.nrel.gov/api/nsrdb/v2/solar/psm3-download.csv"
    params = {
        "wkt": f"POINT({longitude} {latitude})",
        "names": str(year),
        "leap_day": "true" if pd.Timestamp(year=year, month=12, day=31).dayofyear == 366 else "false",
        "interval": int(interval),
        "utc": "false",
        "full_name": "GDMTH PV Simulator",
        "email": email,
        "affiliation": "Academic",
        "mailing_list": "false",
        "reason": "Academic PV simulation",
        "api_key": api_key,
        "attributes": "ghi,dni,dhi,air_temperature,wind_speed",
    }
    response = requests.get(url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    text = response.text

    metadata = pd.read_csv(StringIO(text), nrows=1)
    data = pd.read_csv(StringIO(text), skiprows=2)
    if {"Year", "Month", "Day", "Hour", "Minute"}.issubset(data.columns):
        data["datetime"] = pd.to_datetime(
            {
                "year": data["Year"],
                "month": data["Month"],
                "day": data["Day"],
                "hour": data["Hour"],
                "minute": data["Minute"],
            },
            errors="coerce",
        )

    if not metadata.empty:
        timezone_value = metadata.iloc[0].get("Local Time Zone")
        elevation_value = metadata.iloc[0].get("Elevation")
        if timezone_value is not None:
            data["nsrdb_local_time_zone"] = timezone_value
        if elevation_value is not None:
            data["nsrdb_elevation_m"] = elevation_value

    return standardize_irradiance_table(data, year=year)


def fetch_nsrdb_psm3(
    latitude: float,
    longitude: float,
    year: int,
    api_key: str,
    email: str,
    interval: int = 30,
) -> pd.DataFrame:
    """
    Fetch NSRDB PSM3 data through pvlib.iotools.get_psm3.

    This mode is highly relevant for Mexico because NSRDB PSM3 covers Mexico and
    provides modeled irradiance time series. It requires an API key and email.
    """
    if not api_key or not email:
        raise ValueError("NSRDB requires an API key and an email address.")

    pvlib = _require_pvlib()
    if hasattr(pvlib.iotools, "get_psm3"):
        data, _metadata = pvlib.iotools.get_psm3(
            latitude=latitude,
            longitude=longitude,
            api_key=api_key,
            email=email,
            names=str(year),
            interval=int(interval),
            map_variables=True,
        )
    else:
        data = _fetch_nsrdb_psm3_csv(
            latitude=latitude,
            longitude=longitude,
            year=year,
            api_key=api_key,
            email=email,
            interval=interval,
        )
    return standardize_irradiance_table(data, year=year)


def read_uploaded_irradiance(uploaded_file: Any, year: int | None = None) -> pd.DataFrame:
    """
    Read a user-uploaded CSV or Excel file with irradiance data.

    Recommended columns: datetime, ghi, dni, dhi, temp_air and wind_speed.
    Minimum required columns: datetime and ghi.
    """
    filename = getattr(uploaded_file, "name", "").lower()
    if filename.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(uploaded_file)
    else:
        raw = pd.read_csv(uploaded_file)
    return standardize_irradiance_table(raw, year=year)


def to_15min_irradiance(
    source_df: pd.DataFrame,
    year: int,
    timezone: str = "Etc/GMT+6",
    min_coverage_fraction: float = 0.75,
) -> pd.DataFrame:
    """Interpolate an irradiance table to a complete 15-minute annual index."""
    start = pd.Timestamp(f"{year}-01-01 00:00:00", tz=timezone)
    end = pd.Timestamp(f"{year}-12-31 23:45:00", tz=timezone)
    target_index = pd.date_range(start=start, end=end, freq="15min")

    df = standardize_irradiance_table(source_df, year=year)
    df = _coerce_datetime_to_timezone(df, timezone)
    df = df[df["datetime"].dt.year == int(year)]
    _validate_annual_coverage(df, year, min_coverage_fraction)

    df = df.drop_duplicates("datetime").set_index("datetime").sort_index()
    df = df.reindex(target_index.union(df.index)).interpolate(method="time").reindex(target_index)
    df = df.ffill(limit=4).bfill(limit=4).fillna(0.0)
    df = df.reset_index().rename(columns={"index": "datetime"})
    return df
