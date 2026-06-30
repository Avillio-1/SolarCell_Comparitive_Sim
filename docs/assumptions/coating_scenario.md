# T3 Coating Scenario Assumptions

The named coating paper was not available as a PDF or extracted text in the
workspace. The implementation uses only the prompt-provided paper facts as
calibration anchors.

Prompt-derived anchors:

- 91.3% solar transmittance.
- 0.90 emissivity across the 8-13 um atmospheric window.
- 167 degree contact angle and 3 degree sliding angle.
- Six-month coated-panel power loss near 1.5%, compared with about 28% uncoated.
- Outdoor water yield near 128 g/m2 per night under the tested conditions.
- Nighttime humidity range of 72-92%.
- 400 C, 30 minute thermal treatment.

Commercial assumptions are provisional. The coating is never treated as free.
Material loading, industrial process cost, field application labor, maintenance,
and scalable retrofit feasibility require T5 evidence. The paper's 400 C
treatment means direct field application to installed PV modules is not
demonstrated.

The paper-calibration config uses a dedicated high-humidity CSV fixture to
reproduce the prompt-provided water-yield target. Riyadh simulations use their
actual configured weather and do not hard-code the paper target as a universal
Riyadh value.

Condensed water, potentially collectable water, and actually collected water are
reported separately. The coating scenario assigns no water revenue.
