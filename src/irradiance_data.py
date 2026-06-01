from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from typing import Any

import pandas as pd
import requests


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
    ],
    "DHI_W_m2": [
        "DHI_W_m2", "dhi", "DHI", "Diffuse Horizontal Irradiance", "diffuse_horizontal_irradiance",
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


def fetch_nasa_power_hourly(
    latitude: float,
    longitude: float,
    year: int,
    timeout_seconds: int = 30,
) -> pd.DataFrame:
    """
    Fetch hourly irradiance and basic weather data from NASA POWER.

    This provider is kept as a lightweight no-key fallback. It is not the central
    Jensen et al. iotools pathway, but it is useful for quick real-weather scenarios.
    """
    start = f"{year}0101"
    end = f"{year}1231"
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point"
    params = {
        "parameters": "ALLSKY_SFC_SW_DWN,T2M,WS10M",
        "community": "RE",
        "longitude": longitude,
        "latitude": latitude,
        "start": start,
        "end": end,
        "format": "JSON",
    }

    response = requests.get(url, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    parameters = payload["properties"]["parameter"]

    ghi_series = parameters.get("ALLSKY_SFC_SW_DWN", {})
    t2m_series = parameters.get("T2M", {})
    ws_series = parameters.get("WS10M", {})

    records: list[dict[str, float | pd.Timestamp]] = []
    for raw_key, ghi_value in ghi_series.items():
        timestamp = pd.to_datetime(raw_key, format="%Y%m%d%H")
        records.append(
            {
                "datetime": timestamp,
                "GHI_W_m2": float(ghi_value),
                "temperature_C": float(t2m_series.get(raw_key, float("nan"))),
                "wind_speed_m_s": float(ws_series.get(raw_key, float("nan"))),
            }
        )

    return standardize_irradiance_table(pd.DataFrame(records), year=year)


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
