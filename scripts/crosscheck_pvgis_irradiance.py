"""Cross-check NASA POWER irradiance and PVWatts yield against a PVGIS TMY.

This diagnostic intentionally does not add PVGIS as a SolarClean weather provider.
PVGIS TMY has no precipitation field, so it is suitable here only for the clean-PV
comparison.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from solarclean.application.use_cases import _weather_provider, _weather_request  # noqa: E402
from solarclean.config.loader import load_config  # noqa: E402
from solarclean.config.models import SolarCleanConfig  # noqa: E402
from solarclean.domain.environment.weather import (  # noqa: E402
    CANONICAL_WEATHER_COLUMNS,
    WeatherDataset,
)
from solarclean.infrastructure.pvlib_adapter.pvwatts import (  # noqa: E402
    PVWattsPowerModel,
)

PVGIS_API_ROOT = "https://re.jrc.ec.europa.eu/api"
PVGIS_VERSIONS = ("v5_3", "v5_2")
DEFAULT_LATITUDE = 24.7136
DEFAULT_LONGITUDE = 46.6753
DEFAULT_TIMEZONE = "Asia/Riyadh"
NOMINAL_TMY_YEAR = 2025
EXPECTED_PVGIS_FIELDS: dict[str, str] = {
    "G(h)": "ghi_w_m2",
    "Gb(n)": "dni_w_m2",
    "Gd(h)": "dhi_w_m2",
    "T2m": "temp_air_c",
    "WS10m": "wind_speed_m_s",
    "RH": "relative_humidity_pct",
}
INTERPRETATION = (
    "PVGIS TMY is a climatological typical year while the NASA dataset is the actual "
    "year 2025, so monthly differences up to approximately +/-10% are expected from "
    "weather alone. Annual differences beyond approximately 7% suggest a systematic "
    "irradiance bias worth investigating. This comparison bounds weather-input "
    "uncertainty but is not a ground-truth validation; neither source is a ground station."
)


def pvgis_cache_path(latitude: float, longitude: float) -> Path:
    """Return the repository-local raw PVGIS cache path for coordinates."""
    filename = f"pvgis_tmy_{latitude:.4f}_{longitude:.4f}.json"
    return PROJECT_ROOT / "data" / "cache" / "weather_crosscheck" / filename


def fetch_pvgis_tmy(
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    *,
    cache_path: Path | None = None,
    timeout_seconds: float = 60.0,
    http_client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Load cached PVGIS TMY JSON, or fetch v5.3 and fall back to v5.2."""
    destination = cache_path or pvgis_cache_path(latitude, longitude)
    if destination.exists():
        payload = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"cached PVGIS response is not a JSON object: {destination}")
        return payload

    owns_client = http_client is None
    client = http_client or httpx.Client()
    errors: list[str] = []
    try:
        for version in PVGIS_VERSIONS:
            url = f"{PVGIS_API_ROOT}/{version}/tmy"
            try:
                response = client.get(
                    url,
                    params={"lat": latitude, "lon": longitude, "outputformat": "json"},
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("response was not a JSON object")
                _extract_tmy_records(payload)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{version}: {exc}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return payload
    finally:
        if owns_client:
            client.close()
    raise RuntimeError("PVGIS TMY fetch failed (" + "; ".join(errors) + ")")


def normalize_pvgis_tmy(
    payload: Mapping[str, Any],
    *,
    target_timezone: str = DEFAULT_TIMEZONE,
    nominal_year: int = NOMINAL_TMY_YEAR,
) -> pd.DataFrame:
    """Normalize PVGIS TMY hourly records to SolarClean canonical columns."""
    records = _extract_tmy_records(payload)
    if not records:
        raise ValueError("PVGIS TMY response contains no hourly records")

    timestamp_field = _timestamp_field(records[0])
    first_fields = set(records[0])
    missing = [field for field in EXPECTED_PVGIS_FIELDS if field not in first_fields]
    if missing:
        raise ValueError(
            f"PVGIS TMY fields changed; missing {missing}, received {sorted(first_fields)}"
        )

    index = _synthetic_tmy_index(records, timestamp_field, nominal_year, target_timezone)
    columns: dict[str, list[float]] = {}
    for pvgis_field, canonical_field in EXPECTED_PVGIS_FIELDS.items():
        try:
            columns[canonical_field] = [float(record[pvgis_field]) for record in records]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid PVGIS values for field {pvgis_field}") from exc
    columns["precipitation_mm"] = [0.0] * len(records)

    frame = pd.DataFrame(columns, index=index)
    frame = frame.loc[:, list(CANONICAL_WEATHER_COLUMNS)]
    if frame.index.has_duplicates:
        raise ValueError("synthetic PVGIS TMY timestamps contain duplicates")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("PVGIS TMY records are not in chronological month-by-month order")
    return frame


def build_pvgis_weather_dataset(
    payload: Mapping[str, Any],
    *,
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    elevation_m: float | None = None,
    target_timezone: str = DEFAULT_TIMEZONE,
    nominal_year: int = NOMINAL_TMY_YEAR,
) -> WeatherDataset:
    """Build the diagnostic WeatherDataset consumed by the project's PVWatts model."""
    frame = normalize_pvgis_tmy(payload, target_timezone=target_timezone, nominal_year=nominal_year)
    metadata: dict[str, object] = {
        "provider": "pvgis_tmy_v5",
        "source": "pvgis_tmy_v5",
        "coordinates": {
            "latitude": latitude,
            "longitude": longitude,
            "elevation_m": elevation_m,
        },
        "target_timezone": target_timezone,
        "nominal_year": nominal_year,
        "variables": list(CANONICAL_WEATHER_COLUMNS),
        "pvgis_hourly_fields": sorted(_extract_tmy_records(payload)[0]),
        "precipitation_note": (
            "PVGIS TMY has no precipitation field; precipitation_mm is zero because this "
            "diagnostic runs only the clean PV model and never the soiling model."
        ),
    }
    return WeatherDataset(hourly=frame, metadata=metadata)


def compare_datasets(
    nasa_weather: WeatherDataset,
    pvgis_weather: WeatherDataset,
    config: SolarCleanConfig,
) -> dict[str, object]:
    """Run PVWatts and return JSON-serializable monthly and annual comparisons."""
    power_model = PVWattsPowerModel()
    nasa_profile = power_model.calculate_hourly(nasa_weather, config.pv_system)
    pvgis_profile = power_model.calculate_hourly(pvgis_weather, config.pv_system)

    nasa_monthly = _monthly_ghi(nasa_weather.hourly)
    pvgis_monthly = _monthly_ghi(pvgis_weather.hourly)
    monthly: list[dict[str, object]] = []
    for month in range(1, 13):
        nasa_ghi = float(nasa_monthly.get(month, 0.0))
        pvgis_ghi = float(pvgis_monthly.get(month, 0.0))
        monthly.append(
            {
                "month": month,
                "month_name": pd.Timestamp(2025, month, 1).strftime("%B"),
                "nasa_ghi_kwh_m2": nasa_ghi,
                "pvgis_ghi_kwh_m2": pvgis_ghi,
                "nasa_vs_pvgis_percent": _percent_difference(nasa_ghi, pvgis_ghi),
            }
        )

    nasa_annual_ghi = float(nasa_weather.hourly["ghi_w_m2"].sum() / 1000.0)
    pvgis_annual_ghi = float(pvgis_weather.hourly["ghi_w_m2"].sum() / 1000.0)
    nasa_energy = nasa_profile.annual_clean_energy_kwh
    pvgis_energy = pvgis_profile.annual_clean_energy_kwh
    capacity_kwp = config.pv_system.total_dc_capacity_w / 1000.0
    largest = max(monthly, key=lambda row: abs(float(row["nasa_vs_pvgis_percent"])))
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "comparison_definition": "percent difference = (NASA - PVGIS) / PVGIS * 100",
        "site": {
            "latitude": config.site.latitude,
            "longitude": config.site.longitude,
            "timezone": config.simulation.target_timezone,
        },
        "pvgis_fields_received": pvgis_weather.metadata["pvgis_hourly_fields"],
        "monthly_ghi": monthly,
        "annual": {
            "nasa_ghi_kwh_m2": nasa_annual_ghi,
            "pvgis_ghi_kwh_m2": pvgis_annual_ghi,
            "nasa_vs_pvgis_ghi_percent": _percent_difference(nasa_annual_ghi, pvgis_annual_ghi),
            "nasa_clean_ac_energy_kwh": nasa_energy,
            "pvgis_clean_ac_energy_kwh": pvgis_energy,
            "nasa_vs_pvgis_clean_ac_energy_percent": _percent_difference(nasa_energy, pvgis_energy),
            "system_capacity_kwp": capacity_kwp,
            "nasa_specific_yield_kwh_per_kwp": nasa_energy / capacity_kwp,
            "pvgis_specific_yield_kwh_per_kwp": pvgis_energy / capacity_kwp,
            "nasa_vs_pvgis_specific_yield_percent": _percent_difference(
                nasa_energy / capacity_kwp, pvgis_energy / capacity_kwp
            ),
        },
        "largest_monthly_deviation": largest,
        "interpretation": INTERPRETATION,
        "precipitation_note": pvgis_weather.metadata["precipitation_note"],
    }


def write_reports(report: Mapping[str, object], output_directory: Path) -> tuple[Path, Path]:
    """Write the machine-readable and human-readable cross-check reports."""
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "pvgis_crosscheck.json"
    markdown_path = output_directory / "pvgis_crosscheck.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _extract_tmy_records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    outputs = payload.get("outputs")
    if not isinstance(outputs, Mapping):
        raise KeyError("PVGIS response missing outputs")
    records = outputs.get("tmy_hourly")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise TypeError("PVGIS response missing outputs.tmy_hourly list")
    if not all(isinstance(record, Mapping) for record in records):
        raise TypeError("PVGIS outputs.tmy_hourly contains a non-object record")
    return list(records)


def _timestamp_field(record: Mapping[str, Any]) -> str:
    candidates = [field for field in record if str(field).lower().startswith("time")]
    if len(candidates) != 1:
        raise ValueError(f"expected one PVGIS timestamp field, found {candidates}")
    return str(candidates[0])


def _synthetic_tmy_index(
    records: Sequence[Mapping[str, Any]],
    timestamp_field: str,
    nominal_year: int,
    target_timezone: str,
) -> pd.DatetimeIndex:
    timestamps: list[pd.Timestamp] = []
    for record in records:
        raw = str(record[timestamp_field])
        parsed = pd.to_datetime(raw, format="%Y%m%d:%H%M", errors="raise")
        timestamps.append(
            pd.Timestamp(
                year=nominal_year,
                month=parsed.month,
                day=parsed.day,
                hour=parsed.hour,
                minute=parsed.minute,
                tz="UTC",
            )
        )
    return pd.DatetimeIndex(timestamps).tz_convert(target_timezone)


def _monthly_ghi(frame: pd.DataFrame) -> pd.Series:
    return frame["ghi_w_m2"].groupby(pd.DatetimeIndex(frame.index).month).sum() / 1000.0


def _percent_difference(value: float, reference: float) -> float:
    if reference == 0.0:
        raise ValueError("cannot calculate percent difference against zero")
    return (value - reference) / reference * 100.0


def _render_markdown(report: Mapping[str, object]) -> str:
    monthly = report["monthly_ghi"]
    annual = report["annual"]
    largest = report["largest_monthly_deviation"]
    if not isinstance(monthly, list) or not isinstance(annual, Mapping):
        raise TypeError("comparison report has an invalid structure")
    if not isinstance(largest, Mapping):
        raise TypeError("comparison report has an invalid largest deviation")
    fields_received = ", ".join(str(value) for value in report["pvgis_fields_received"])
    lines = [
        "# PVGIS irradiance cross-check",
        "",
        "Percent difference is `(NASA - PVGIS) / PVGIS * 100`.",
        "",
        "## Monthly GHI",
        "",
        "| Month | NASA (kWh/m2) | PVGIS (kWh/m2) | Difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    for raw_row in monthly:
        if not isinstance(raw_row, Mapping):
            raise TypeError("monthly comparison row must be an object")
        lines.append(
            f"| {raw_row['month_name']} | {float(raw_row['nasa_ghi_kwh_m2']):.2f} | "
            f"{float(raw_row['pvgis_ghi_kwh_m2']):.2f} | "
            f"{float(raw_row['nasa_vs_pvgis_percent']):+.2f}% |"
        )
    lines.extend(
        [
            "",
            "## Annual comparison",
            "",
            f"- NASA GHI: {float(annual['nasa_ghi_kwh_m2']):,.2f} kWh/m2",
            f"- PVGIS GHI: {float(annual['pvgis_ghi_kwh_m2']):,.2f} kWh/m2",
            f"- GHI difference: {float(annual['nasa_vs_pvgis_ghi_percent']):+.2f}%",
            f"- NASA clean AC energy: {float(annual['nasa_clean_ac_energy_kwh']):,.2f} kWh",
            f"- PVGIS clean AC energy: {float(annual['pvgis_clean_ac_energy_kwh']):,.2f} kWh",
            "- NASA specific yield: "
            f"{float(annual['nasa_specific_yield_kwh_per_kwp']):,.2f} kWh/kWp",
            "- PVGIS specific yield: "
            f"{float(annual['pvgis_specific_yield_kwh_per_kwp']):,.2f} kWh/kWp",
            "- Specific-yield difference: "
            f"{float(annual['nasa_vs_pvgis_specific_yield_percent']):+.2f}%",
            "",
            "Largest monthly deviation: "
            f"{largest['month_name']} ({float(largest['nasa_vs_pvgis_percent']):+.2f}%).",
            "",
            "## Interpretation",
            "",
            str(report["interpretation"]),
            "",
            "## Data notes",
            "",
            f"- PVGIS fields received: {fields_received}",
            f"- {report['precipitation_note']}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    config = load_config(PROJECT_ROOT / "configs" / "default.yaml")
    payload = fetch_pvgis_tmy(
        config.site.latitude,
        config.site.longitude,
        timeout_seconds=config.weather.timeout_seconds,
    )
    pvgis_weather = build_pvgis_weather_dataset(
        payload,
        latitude=config.site.latitude,
        longitude=config.site.longitude,
        elevation_m=config.site.elevation_m,
        target_timezone=config.simulation.target_timezone,
    )
    nasa_weather = _weather_provider(config).load(_weather_request(config))
    report = compare_datasets(nasa_weather, pvgis_weather, config)
    paths = write_reports(report, PROJECT_ROOT / "outputs" / "pvgis_crosscheck")
    print(f"Wrote {paths[0]}")
    print(f"Wrote {paths[1]}")


if __name__ == "__main__":
    main()
