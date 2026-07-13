"""Benchmark SolarClean-DT soiling against pvlib's published model implementations.

This is an external model-form comparison under provisional literature parameters,
not validation against measured Riyadh soiling observations.

Usage:
    python scripts/benchmark_soiling_vs_published.py
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pvlib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from solarclean.application.use_cases import _weather_provider, _weather_request  # noqa: E402
from solarclean.config.loader import load_config  # noqa: E402
from solarclean.config.models import (  # noqa: E402
    RainfallCleaningConfig,
    SoilingConfig,
    SolarCleanConfig,
)
from solarclean.domain.contamination.soiling import (  # noqa: E402
    ContaminationState,
    DailyEnvironment,
    KimberStyleSoilingModel,
)

CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "soiling_benchmark"
KIMBER_RATES: tuple[float, ...] = (0.0005, 0.001, 0.002, 0.003, 0.005)
ENSEMBLE_SEEDS: tuple[int, ...] = tuple(range(200))
HSU_PM2_5_G_M3 = 60e-6
HSU_PM10_G_M3 = 150e-6


def load_hourly_weather(config: SolarCleanConfig) -> pd.DataFrame:
    """Load normalized weather through SolarClean's configured provider path."""
    return _weather_provider(config).load(_weather_request(config)).hourly.copy()


def derive_weather_inputs(
    hourly_weather: pd.DataFrame,
    timezone: str,
) -> tuple[pd.Series, pd.DataFrame]:
    """Return hourly rain and daily rain/RH inputs in the requested timezone."""
    required = {"precipitation_mm", "relative_humidity_pct"}
    missing = sorted(required.difference(hourly_weather.columns))
    if missing:
        raise ValueError(f"weather frame missing required columns: {', '.join(missing)}")

    frame = hourly_weather.copy()
    index = pd.DatetimeIndex(frame.index)
    index = index.tz_localize(timezone) if index.tz is None else index.tz_convert(timezone)
    frame.index = index
    frame = frame.sort_index()

    hourly_rain = frame["precipitation_mm"].astype(float).rename("precipitation_mm")
    daily = pd.DataFrame(
        {
            "precipitation_mm": hourly_rain.resample("D").sum(),
            "mean_relative_humidity_pct": frame["relative_humidity_pct"]
            .astype(float)
            .resample("D")
            .mean(),
            "max_relative_humidity_pct": frame["relative_humidity_pct"]
            .astype(float)
            .resample("D")
            .max(),
        }
    )
    if daily.isna().any().any():
        raise ValueError("daily weather aggregation produced missing values")
    return hourly_rain, daily


def run_project_model(
    daily_weather: pd.DataFrame,
    soiling: SoilingConfig,
    rainfall: RainfallCleaningConfig,
    *,
    seed: int,
) -> pd.Series:
    """Run one daily SolarClean soiling pass and return end-of-day ratios."""
    required = {
        "precipitation_mm",
        "mean_relative_humidity_pct",
        "max_relative_humidity_pct",
    }
    missing = sorted(required.difference(daily_weather.columns))
    if missing:
        raise ValueError(f"daily weather frame missing required columns: {', '.join(missing)}")

    model = KimberStyleSoilingModel(soiling, rainfall)
    rng = np.random.default_rng(seed)
    state = ContaminationState()
    ratios: list[float] = []
    for timestamp, row in daily_weather.sort_index().iterrows():
        environment = DailyEnvironment(
            date=pd.Timestamp(timestamp).date(),
            precipitation_mm=float(row["precipitation_mm"]),
            mean_relative_humidity_pct=float(row["mean_relative_humidity_pct"]),
            max_relative_humidity_pct=float(row["max_relative_humidity_pct"]),
        )
        update = model.update(state, environment, rng, event_inputs=None)
        state = update.state
        ratios.append(state.dust_soiling_ratio)
    return pd.Series(ratios, index=daily_weather.sort_index().index, name="soiling_ratio")


def run_project_ensemble(
    daily_weather: pd.DataFrame,
    soiling: SoilingConfig,
    rainfall: RainfallCleaningConfig,
    seeds: Sequence[int] = ENSEMBLE_SEEDS,
) -> pd.DataFrame:
    """Run independent project-model passes and return daily mean and 5--95% band."""
    passes = np.column_stack(
        [
            run_project_model(daily_weather, soiling, rainfall, seed=seed).to_numpy()
            for seed in seeds
        ]
    )
    return pd.DataFrame(
        {
            "mean": passes.mean(axis=1),
            "p05": np.percentile(passes, 5, axis=1),
            "p95": np.percentile(passes, 95, axis=1),
        },
        index=daily_weather.sort_index().index,
    )


def run_kimber_model(
    hourly_rain: pd.Series,
    *,
    soiling_loss_rate: float,
    cleaning_threshold: float | None = None,
) -> pd.Series:
    """Run pvlib Kimber and normalize its loss output to ratio (1 = clean)."""
    kwargs: dict[str, float] = {"soiling_loss_rate": soiling_loss_rate}
    if cleaning_threshold is not None:
        kwargs["cleaning_threshold"] = cleaning_threshold
    loss = pvlib.soiling.kimber(hourly_rain.astype(float), **kwargs)
    return (1.0 - loss).rename("soiling_ratio")


def run_hsu_model(
    hourly_rain: pd.Series,
    *,
    surface_tilt: float = 25.0,
    cleaning_threshold: float = 5.0,
    pm2_5_g_m3: float = HSU_PM2_5_G_M3,
    pm10_g_m3: float = HSU_PM10_G_M3,
) -> pd.Series:
    """Run pvlib HSU, whose native output is already ratio (1 = clean)."""
    ratio = pvlib.soiling.hsu(
        hourly_rain.astype(float),
        cleaning_threshold=cleaning_threshold,
        surface_tilt=surface_tilt,
        pm2_5=pm2_5_g_m3,
        pm10=pm10_g_m3,
    )
    return ratio.rename("soiling_ratio")


def daily_end(series: pd.Series) -> pd.Series:
    """Downsample an hourly ratio to its end-of-day value."""
    return series.resample("D").last().rename(series.name)


def model_metrics(series: pd.Series, rain_reset_days: int) -> dict[str, float | int]:
    """Summarize a daily clean-is-1 ratio series."""
    mean_ratio = float(series.mean())
    return {
        "annual_mean_soiling_ratio": mean_ratio,
        "minimum_soiling_ratio": float(series.min()),
        "annual_average_loss_percent": (1.0 - mean_ratio) * 100.0,
        "rain_cleaning_reset_days_ge_5mm": rain_reset_days,
    }


def _kimber_key(rate: float, threshold_label: str) -> str:
    return f"pvlib_kimber_rate_{rate:.4f}_threshold_{threshold_label}"


def _build_verdict(models: Mapping[str, Mapping[str, float | int]]) -> dict[str, object]:
    project_loss = float(models["project_stochastic_mean"]["annual_average_loss_percent"])
    kimber_items = [
        (key, values) for key, values in models.items() if key.startswith("pvlib_kimber")
    ]
    kimber_losses = [float(values["annual_average_loss_percent"]) for _, values in kimber_items]
    closest_key, closest_metrics = min(
        kimber_items,
        key=lambda item: abs(float(item[1]["annual_average_loss_percent"]) - project_loss),
    )
    closest_rate = float(str(closest_key).split("_rate_")[1].split("_threshold_")[0])
    hsu_loss = float(models["pvlib_hsu"]["annual_average_loss_percent"])
    lower = min(kimber_losses)
    upper = max(kimber_losses)
    return {
        "project_central_annual_loss_percent": project_loss,
        "kimber_envelope_annual_loss_percent": {"minimum": lower, "maximum": upper},
        "project_inside_kimber_envelope": lower <= project_loss <= upper,
        "closest_kimber_variant": closest_key,
        "closest_kimber_rate_per_day": closest_rate,
        "closest_kimber_annual_loss_percent": float(closest_metrics["annual_average_loss_percent"]),
        "hsu_annual_loss_percent": hsu_loss,
        "project_minus_hsu_loss_percentage_points": project_loss - hsu_loss,
        "caveat": (
            "This corroborates model form against published models under literature parameters; "
            "it is NOT validation against measured Riyadh soiling data."
        ),
    }


def _write_plot(
    path: Path,
    ensemble: pd.DataFrame,
    deterministic: pd.Series,
    kimber_curves: Mapping[str, pd.Series],
    hsu: pd.Series,
) -> None:
    fig, ax = plt.subplots(figsize=(15, 8))
    ax.fill_between(
        ensemble.index,
        ensemble["p05"],
        ensemble["p95"],
        color="#377eb8",
        alpha=0.18,
        label="SolarClean stochastic 5--95%",
    )
    ax.plot(
        ensemble.index,
        ensemble["mean"],
        color="#174a7e",
        linewidth=2.2,
        label="SolarClean stochastic mean",
    )
    ax.plot(
        deterministic.index,
        deterministic,
        color="#174a7e",
        linestyle="--",
        linewidth=1.4,
        label="SolarClean deterministic central",
    )
    colors = plt.cm.YlOrRd(np.linspace(0.25, 0.9, len(KIMBER_RATES)))
    for key, curve in kimber_curves.items():
        rate_text = key.split("_rate_")[1].split("_threshold_")[0]
        threshold_text = key.rsplit("_threshold_", maxsplit=1)[1]
        rate_index = KIMBER_RATES.index(float(rate_text))
        linestyle = ":" if threshold_text == "default_6mm" else "-"
        ax.plot(
            curve.index,
            curve,
            color=colors[rate_index],
            linestyle=linestyle,
            linewidth=1.0,
            label=f"pvlib Kimber {rate_text}/day, {threshold_text.replace('_', ' ')}",
        )
    ax.plot(hsu.index, hsu, color="#4daf4a", linewidth=1.8, label="pvlib HSU")
    ax.set(
        title="Riyadh 2025 soiling model-form benchmark",
        xlabel="Date (Asia/Riyadh)",
        ylabel="Soiling ratio (1 = clean)",
        ylim=(0.5, 1.01),
    )
    ax.grid(alpha=0.25)
    ax.legend(loc="lower left", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _markdown_table(models: Mapping[str, Mapping[str, float | int]]) -> str:
    lines = [
        "| Model variant | Mean ratio | Minimum ratio | Average loss (%) | Rain days >= 5 mm |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, metrics in models.items():
        lines.append(
            f"| {name} | {float(metrics['annual_mean_soiling_ratio']):.6f} | "
            f"{float(metrics['minimum_soiling_ratio']):.6f} | "
            f"{float(metrics['annual_average_loss_percent']):.3f} | "
            f"{int(metrics['rain_cleaning_reset_days_ge_5mm'])} |"
        )
    return "\n".join(lines)


def _write_reports(
    output_dir: Path,
    models: Mapping[str, Mapping[str, float | int]],
    verdict: Mapping[str, object],
    rain_reset_days: int,
) -> None:
    payload = {
        "scope": "External model-form corroboration, not measured-site validation.",
        "weather": "Normalized NASA POWER Riyadh 2025 series in Asia/Riyadh.",
        "rain_cleaning_reset_days_ge_5mm": rain_reset_days,
        "parameters": {
            "project": "configs/default.yaml values; 200 stochastic seeds (0..199)",
            "kimber_rates_per_day": list(KIMBER_RATES),
            "kimber_cleaning_thresholds_mm": ["pvlib default (6.0)", 5.0],
            "hsu_surface_tilt_degrees": 25.0,
            "hsu_cleaning_threshold_mm": 5.0,
            "hsu_pm2_5_ug_m3": 60.0,
            "hsu_pm10_ug_m3": 150.0,
            "hsu_pm_basis": "literature-typical annual means, provisional",
        },
        "models": models,
        "verdict": verdict,
    }
    (output_dir / "soiling_benchmark.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    envelope = verdict["kimber_envelope_annual_loss_percent"]
    assert isinstance(envelope, Mapping)
    inside = "inside" if verdict["project_inside_kimber_envelope"] else "outside"
    comparison = float(verdict["project_minus_hsu_loss_percentage_points"])
    hsu_relation = "higher" if comparison > 0 else "lower"
    lines = [
        "# Soiling benchmark against published pvlib models",
        "",
        "## Scope",
        "",
        "All models use the same normalized NASA POWER Riyadh 2025 rainfall series in "
        "Asia/Riyadh. SolarClean uses daily rainfall and humidity aggregates; pvlib uses the "
        "hourly rainfall series. This is external corroboration of model form, not site "
        "validation.",
        "",
        "## Parameters and normalization",
        "",
        "- SolarClean: the `configs/default.yaml` soiling and rainfall-cleaning values. The "
        "central stochastic result is the daily mean of 200 independent seeds (0--199); its "
        "5th--95th percentile band and a no-stochasticity/no-dust-event curve are also reported.",
        "- pvlib Kimber: rates 0.0005, 0.001, 0.002, 0.003, and 0.005 per day, each with "
        "pvlib's 6 mm default cleaning threshold and the project's 5 mm full-rain threshold. "
        "Kimber loss output was converted to ratio as `1 - loss`. The sweep is informed by "
        "Kimber et al. (2006) and the arid-soiling context in Ilse et al. (2019, Joule).",
        "- pvlib HSU (Coello & Boyle, 2019): 25 degree tilt, 5 mm cleaning threshold, and "
        "PM2.5 = 60 micrograms/m^3 and PM10 = 150 micrograms/m^3. These are "
        "literature-typical annual means, provisional; pvlib expects g/m^3, so the inputs were "
        "60e-6 and 150e-6 g/m^3. HSU already returns a clean-is-1 ratio.",
        f"- Shared count of daily rainfall resets (rain >= 5 mm): {rain_reset_days}.",
        "",
        "## Results",
        "",
        _markdown_table(models),
        "",
        "## Verdict",
        "",
        f"The SolarClean stochastic-mean annual loss is "
        f"{float(verdict['project_central_annual_loss_percent']):.3f}%. It falls **{inside}** "
        f"the combined pvlib Kimber sweep envelope of {float(envelope['minimum']):.3f}% to "
        f"{float(envelope['maximum']):.3f}% annual average loss. The closest Kimber curve is "
        f"{float(verdict['closest_kimber_rate_per_day']):.4f}/day "
        f"(`{verdict['closest_kimber_variant']}`), at "
        f"{float(verdict['closest_kimber_annual_loss_percent']):.3f}% loss.",
        "",
        f"The HSU annual average loss is {float(verdict['hsu_annual_loss_percent']):.3f}%. "
        f"SolarClean is {abs(comparison):.3f} percentage points {hsu_relation} than HSU under "
        "these provisional particulate assumptions.",
        "",
        "**Caveat:** This corroborates model form against published models under literature "
        "parameters; it is **NOT validation against measured Riyadh soiling data**.",
        "",
        "## References",
        "",
        "- Kimber, A. et al. (2006), *The Effect of Soiling on Large Grid-Connected "
        "Photovoltaic Systems in California and the Southwest Region of the United States*.",
        "- Ilse, K. et al. (2019), *Techno-Economic Assessment of Soiling Losses and "
        "Mitigation Strategies for Solar Power Generation*, Joule. "
        "https://doi.org/10.1016/j.joule.2019.08.019",
        "- Coello, M. and Boyle, L. (2019), *Simple Model for Predicting Time Series Soiling "
        "of Photovoltaic Panels*, IEEE Journal of Photovoltaics. "
        "https://doi.org/10.1109/JPHOTOV.2019.2919628",
    ]
    (output_dir / "soiling_benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    config = load_config(CONFIG_PATH)
    hourly_weather = load_hourly_weather(config)
    hourly_rain, daily_weather = derive_weather_inputs(
        hourly_weather, config.simulation.target_timezone
    )
    rain_reset_days = int((daily_weather["precipitation_mm"] >= 5.0).sum())

    ensemble = run_project_ensemble(daily_weather, config.soiling, config.rainfall_cleaning)
    deterministic_config = config.soiling.model_copy(
        update={"stochastic_std_fraction": 0.0, "dust_event_probability": 0.0}
    )
    deterministic = run_project_model(
        daily_weather,
        deterministic_config,
        config.rainfall_cleaning,
        seed=config.soiling.random_seed,
    )

    kimber_curves: dict[str, pd.Series] = {}
    for rate in KIMBER_RATES:
        default_key = _kimber_key(rate, "default_6mm")
        kimber_curves[default_key] = daily_end(
            run_kimber_model(hourly_rain, soiling_loss_rate=rate)
        )
        matched_key = _kimber_key(rate, "5mm")
        kimber_curves[matched_key] = daily_end(
            run_kimber_model(
                hourly_rain,
                soiling_loss_rate=rate,
                cleaning_threshold=5.0,
            )
        )
    hsu = daily_end(run_hsu_model(hourly_rain))

    models: dict[str, dict[str, float | int]] = {
        "project_stochastic_mean": model_metrics(ensemble["mean"], rain_reset_days),
        "project_stochastic_p05": model_metrics(ensemble["p05"], rain_reset_days),
        "project_stochastic_p95": model_metrics(ensemble["p95"], rain_reset_days),
        "project_deterministic_central": model_metrics(deterministic, rain_reset_days),
    }
    models.update(
        {key: model_metrics(curve, rain_reset_days) for key, curve in kimber_curves.items()}
    )
    models["pvlib_hsu"] = model_metrics(hsu, rain_reset_days)
    verdict = _build_verdict(models)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_plot(
        OUTPUT_DIR / "soiling_benchmark.png",
        ensemble,
        deterministic,
        kimber_curves,
        hsu,
    )
    _write_reports(OUTPUT_DIR, models, verdict, rain_reset_days)
    print(json.dumps(verdict, indent=2))
    print(f"Reports written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
