from __future__ import annotations

from dataclasses import asdict, dataclass

from solarclean.config.models import RainfallCleaningConfig, SoilingConfig


@dataclass(frozen=True)
class CalibrationPreset:
    name: str
    label: str
    status: str
    soiling: SoilingConfig
    rainfall: RainfallCleaningConfig
    notes: str

    def to_record(self) -> dict[str, object]:
        record = asdict(self)
        record["soiling"] = self.soiling.model_dump(mode="json")
        record["rainfall"] = self.rainfall.model_dump(mode="json")
        return record


class CalibrationRegistry:
    def __init__(self, presets: tuple[CalibrationPreset, ...]) -> None:
        self._presets = {preset.name: preset for preset in presets}

    @classmethod
    def default(cls) -> CalibrationRegistry:
        return cls(
            (
                CalibrationPreset(
                    name="riyadh_low_soiling",
                    label="Provisional low Riyadh soiling assumption",
                    status="provisional_requires_calibration",
                    soiling=SoilingConfig(
                        base_daily_soiling_loss_fraction=0.0012,
                        dust_event_probability=0.015,
                        dust_event_loss_min_fraction=0.003,
                        dust_event_loss_max_fraction=0.015,
                        minimum_soiling_ratio=0.7,
                        stochastic_std_fraction=0.05,
                        random_seed=42,
                    ),
                    rainfall=RainfallCleaningConfig(
                        partial_rain_threshold_mm=1.0,
                        full_rain_cleaning_threshold_mm=5.0,
                        partial_rain_cleaning_efficiency=0.45,
                        full_rain_cleaning_efficiency=0.95,
                    ),
                    notes=(
                        "Lower-bound engineering assumption awaiting measured Riyadh calibration."
                    ),
                ),
                CalibrationPreset(
                    name="riyadh_medium_soiling",
                    label="Provisional medium Riyadh soiling assumption",
                    status="provisional_requires_calibration",
                    soiling=SoilingConfig(
                        base_daily_soiling_loss_fraction=0.0025,
                        seasonal_multipliers={3: 1.1, 4: 1.15, 5: 1.1},
                        dust_event_probability=0.03,
                        dust_event_loss_min_fraction=0.005,
                        dust_event_loss_max_fraction=0.03,
                        minimum_soiling_ratio=0.55,
                        stochastic_std_fraction=0.1,
                        random_seed=42,
                    ),
                    rainfall=RainfallCleaningConfig(),
                    notes="Default provisional assumption used by configs/riyadh_2025.yaml.",
                ),
                CalibrationPreset(
                    name="riyadh_high_soiling",
                    label="Provisional high Riyadh soiling assumption",
                    status="provisional_requires_calibration",
                    soiling=SoilingConfig(
                        base_daily_soiling_loss_fraction=0.004,
                        seasonal_multipliers={3: 1.2, 4: 1.25, 5: 1.2},
                        dust_event_probability=0.06,
                        dust_event_loss_min_fraction=0.01,
                        dust_event_loss_max_fraction=0.05,
                        minimum_soiling_ratio=0.45,
                        stochastic_std_fraction=0.15,
                        random_seed=42,
                    ),
                    rainfall=RainfallCleaningConfig(
                        partial_rain_threshold_mm=1.5,
                        full_rain_cleaning_threshold_mm=6.0,
                        partial_rain_cleaning_efficiency=0.35,
                        full_rain_cleaning_efficiency=0.9,
                    ),
                    notes="Stress-test assumption, not validated Saudi field calibration.",
                ),
            )
        )

    def get(self, name: str) -> CalibrationPreset:
        try:
            return self._presets[name]
        except KeyError as exc:
            raise KeyError(f"unknown calibration preset: {name}") from exc

    def to_records(self) -> list[dict[str, object]]:
        return [preset.to_record() for preset in self._presets.values()]
