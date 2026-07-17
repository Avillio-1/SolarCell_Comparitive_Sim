# T3 Coating Scenario Assumptions

The coating calibration uses the open-access paper
`https://doi.org/10.1002/eem2.70350` and keeps site-wide extrapolations
weather-gated.

Prompt-derived anchors:

- 91.3% coated-glass solar transmittance. This is retained as source
  metadata and is not applied as an 8.7% coating-versus-uncoated PV energy
  penalty.
- The prompt-reported approximately 1.4% transmittance improvement versus
  uncoated glass is also not applied as a PV energy gain without module-level
  evidence.
- 0.90 emissivity across the 8-13 um atmospheric window.
- 167 degree contact angle and 3 degree sliding angle.
- Six-month coated-panel power loss near 1.5%, compared with about 28% uncoated.
  The production soiling model applies additive daily soiling updates, so the
  endpoint-equivalent fixture uses `0.28 / 180 = 0.0015555556` uncoated daily
  loss and `0.015 / 0.28 = 0.0535714` as the coated/uncoated daily accumulation
  ratio.
- Outdoor collected-water yield near 128 g/m2 per night under the tested
  favorable conditions.
- Nighttime humidity range of 72-92%.
- 400 C, 30 minute thermal treatment.

Commercial assumptions are provisional. The coating is never treated as free.
Material loading, industrial process cost, field application labor, maintenance,
and scalable retrofit feasibility require T5 evidence. The paper's 400 C
treatment means direct field application to installed PV modules is not
demonstrated.

The paper-calibration config uses a dedicated high-humidity CSV fixture to
exercise a one-night water-yield scale conversion. It is a smoke fixture, not a
six-month or annual validation. The separate endpoint-equivalent fixture uses
180 production daily updates with passive dew cleaning disabled so the
paper-reported 28% and 1.5% endpoint losses are not double-counted. Riyadh
simulations use their actual configured weather and do not hard-code the paper
target as a universal Riyadh value.

The current weather providers use inclusive hourly ranges (`start <= timestamp
<= end`). Therefore a complete one-day CSV fixture ends at 23:00 on the same
date, and a complete 2025 full-year run ends at 2025-12-31 23:00 in the site
timezone.

The soiling model applies configured seasonal multipliers by calendar month and
falls back to 1.0 for months not listed in a configuration. Missing months are
therefore an explicit neutral fallback, not evidence of measured seasonal
behavior.

Condensed water, potentially collectable water, and actually collected water are
reported separately as whole-farm period totals plus liters per square meter.
The two water efficiencies are sequential. In the `kaust_paper_strong` R&D
preset both are 1.0 because the calibrated 0.0046767 coefficient represents the
paper's measured collected yield (0.128 L/m2 on a favorable night), rather than
an unobserved gross-condensation quantity. The coefficient is still applied only
when modeled humidity, dew point, and coated surface temperature permit
condensation. Collection cost and water revenue remain excluded, and the result
must not be read as 0.128 L/m2 on every night.

`coating.physics.optical_transmittance_multiplier` is a relative
coated-versus-uncoated PV performance multiplier. It is neutral in the central
and paper-calibration presets until product- or module-level evidence supports a
different value. The weak preset's below-1.0 optical multiplier is a low-side
sensitivity assumption, not a measured result from the named coating paper.

The clean energy reference is the clean uncoated PVWatts AC output at the
modeled operating temperature. Dust and bird contamination recovery is bounded
by a cleanliness ratio no greater than 1.0. Coating-specific optical and
thermal physics are allowed to move final coated output above or below the clean
uncoated reference when the configured physics justify it.

The central preset sets `daytime_cooling_fraction` to 0.0 because the prompt
does not establish daytime module cooling. Optimistic daytime cooling remains a
sensitivity assumption, not a central paper-derived value.

The 400 C thermal treatment is treated as compatible with factory preinstallation
for new modules, not as evidence of field reapplication on an existing fleet.
Reapplication is therefore unsupported unless a future replacement,
refurbishment, or demonstrated field process is supplied.
