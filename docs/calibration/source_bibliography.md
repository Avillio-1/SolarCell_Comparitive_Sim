# Calibration Source Bibliography

Retrieval date for web sources: 2026-06-30; literature-v3 refresh: 2026-07-18.

## PV Soiling And Rain Cleaning

- Jones, R. K., Baras, A., Al Saeeri, A., Al Qahtani, A., Al Amoudi, A., Al Shaya, Y., Alodan, M., Al-Hsaien, S. "Optimized Cleaning Cost and Schedule Based on Observed Soiling Conditions for Photovoltaic Plants in Central Saudi Arabia." IEEE Journal of Photovoltaics 6(3):730-738, 2016. https://doi.org/10.1109/JPHOTOV.2016.2535308. K.A.CARE 3-year soiling campaign at Rumah (central Saudi Arabia, near Riyadh); the closest published measured-soiling evidence to the simulated site.
- "The Impact of Soiling on PV Module Performance in Saudi Arabia." Energies 15(21):8033, 2022. https://doi.org/10.3390/en15218033. Reports 30-day soiling losses of 2-18% across PV technologies at Rumah near Riyadh (~0.0007-0.006/day), used to anchor the dry soiling-rate central value and high bound.
- Adinoyi, M. J., Said, S. A. M. "Effect of dust accumulation on the power outputs of solar photovoltaic modules." Renewable Energy 60:633-636, 2013. https://www.sciencedirect.com/science/article/abs/pii/S0960148113003078. Dhahran long-exposure result: >50% power reduction after 6+ months without cleaning; anchors the minimum soiling-ratio floor.
- Bessa, J. G., Micheli, L., Almonacid, F., Fernández, E. F. "Monitoring photovoltaic soiling: assessment, challenges, and perspectives of current and potential strategies." iScience 24(3):102165, 2021. https://doi.org/10.1016/j.isci.2021.102165 (open access: https://pmc.ncbi.nlm.nih.gov/articles/PMC7960939/). Multi-site rain-cleaning thresholds (~1-5 mm/day) and arid soiling-rate ranges (e.g. Atacama <0.05 to >0.4%/day).
- Kimber, A., Mitchell, L., Nogradi, S., Wenger, H. "The effect of soiling on large grid-connected photovoltaic systems in California and the Southwest region of the United States." IEEE WCPEC, 2006. Provenance for the Kimber-style empirical soiling/rain-reset model. The installed `pvlib.soiling.kimber` implementation (pvlib 0.15.2) defaults to cleaning_threshold 6 mm, soiling_loss_rate 0.0015/day, max_soiling 0.3.
- Ilse, K. et al. "Techno-Economic Assessment of Soiling Losses and Mitigation Strategies for Solar Power Generation." Joule, 2019. https://doi.org/10.1016/j.joule.2019.08.019. Global soiling-economics context, not a direct Riyadh measurement.
- NASA POWER documentation: https://power.larc.nasa.gov/docs/. Weather-provider context; not a soiling measurement source.
- NREL PV soiling information page: https://www.nrel.gov/pv/soiling.html. Broad reference that soiling varies by location, weather, and cleaning conditions.

## Dust Events And Saudi Applicability

- "Spatial and Temporal Variations in the Incidence of Dust Storms in Saudi Arabia Revealed from In Situ Observations." Geosciences 9(4):162, 2019. https://doi.org/10.3390/geosciences9040162. Central Saudi Arabia (Riyadh region): ~7.6 severe dust storms/year, ~76 blowing-dust days/year, April frequency peak, February-June season. Anchors dust-event probability and the spring seasonal multipliers.
- "Synoptic characteristics of the spatial variability of spring dust storms over Saudi Arabia." Atmósfera 36(3), 2023. https://www.scielo.org.mx/scielo.php?script=sci_arttext&pid=S0187-62362023000300124. Supporting spring dust-season synoptic evidence.
- NASA POWER and Riyadh 2025 validation outputs in `PROGRESS.md` provide weather context, but not dust deposition or measured soiling-ratio data.

## Bird Droppings And Localized Obstruction

- General PV soiling and partial-obstruction literature identifies biological droppings as a localized soiling mode. No Saudi utility-scale bird-dropping frequency, coverage, persistence, or power-loss source was found for this T5 pass.
- The bird-dropping parameters are therefore assumed/provisional and require site observation, image labels, or maintenance logs.

## Computer Vision

- "SolPowNet: Dust Detection on Photovoltaic Panels Using Convolutional Neural Networks." Electronics 14(21):4230. https://doi.org/10.3390/electronics14214230. Dusty/clean classification on an 842-image curated dataset: 98.8% accuracy, 100% recall, 97.1% precision.
- "Deep Learning-Based Dust Detection on Solar Panels: A Low-Cost Sustainable Solution for Increased Solar Power Generation." Sustainability 16(19):8664, 2024. https://doi.org/10.3390/su16198664. Compact CNN 99.9% accuracy with ~5 ms inference.
- These curated-benchmark results anchor the *ceiling* of detector performance; the registry centrals deliberately derate them for drone altitude, glare, and field imagery. DeepSolarEye and related literature remain background context: https://arxiv.org/search/cs?query=DeepSolarEye&searchtype=all.
- T2 must replace these values with a measured confusion matrix on the selected inspection imagery and model.

## Drone Inspection And Cleaning

- DJI Matrice 350 RTK official specifications: https://enterprise.dji.com/matrice-350-rtk/specs. Used for a quoted maximum flight-time bound; the central registry value is derated for payload, heat, wind, and battery aging.
- CEEW estimate of Indian utility PV cleaning water use, 3-5 liters/panel/wash (up to 7-8), via the Polywater water-use summary: https://www.polywater.com/wp-content/uploads/2021/08/SPW-Intl-blog-Water-Use-IndiaCA.pdf. Anchors the water-per-panel envelope; the central value assumes a water-efficient method.
- Cleaning rate and labor hours remain inferred placeholders until T2 or T3 provides a cleaning method, contractor quote, or measured time-and-motion data.

## Coatings, Dew, Cooling, And Water Collection

- "Anti-Soiling Coatings for Enhancement of PV Panel Performance in Desert Environment: A Critical Review and Market Overview." Materials 15(20):7139, 2022. https://doi.org/10.3390/ma15207139 (open access: https://pmc.ncbi.nlm.nih.gov/articles/PMC9609821/). Key anchors: long-term field soiling reduction 20-50% (short-term up to 80%); hydrophilic coatings outperformed hydrophobic by ~2.5x on dust reduction in one comparison; silica-coated modules aged 3.5 years outdoors without solid degradation (+3.9% output for optimized silica on CIGS); "minimal reflection loss"; no published per-m2 cost data — coating capex therefore remains provisional.
- MIT News article on electrostatic water-free PV dust removal: https://news.mit.edu/2022/solar-panels-dust-magnets-0311. Used as context that dry cleaning and dust adhesion are active research areas, not as the selected SolarClean coating.
- Science Advances electrostatic PV dust-removal article: https://www.science.org/doi/10.1126/sciadv.abm0078. Used for dust-removal context and the importance of humidity/moisture.
- Hydrophobic/nanotextured self-cleaning coating and radiative/hydrogel cooling literature were used as broad evidence. T3 must replace registry values with the selected KAUST-inspired coating evidence, product data, or test data before decision use.
- The prompt-quoted 91.3% coated-glass solar transmittance is retained as
  source metadata only. It is not evidence for an 8.7% coating-versus-uncoated
  PV energy penalty. The active optical multiplier must be a relative
  coated-versus-uncoated PV performance value.
- The prompt-quoted six-month 28% uncoated and 1.5% coated power-loss endpoints
  are represented only in the endpoint-equivalent fixture. The endpoint-derived
  ratio is not treated as a standalone dust-adhesion measurement and must not be
  combined with passive-cleaning efficiency in the same calibration fixture.
- The prompt-quoted 128 g/m2/night water yield is a favorable-condition collected
  water result. The production model reports gross condensation, physically
  collectable water, and actually harvested water separately.

## Economics

- Saudi Electricity Company tariff page/source locator: https://www.se.com.sa/en-us/Customers/Pages/TariffRates.aspx.
- Utility-scale Saudi PV PPA benchmarks (energy-value floor for a BOO plant): Sakaka 300 MW at 7 halalas/kWh (~1.87 USc/kWh), https://www.vision2030.gov.sa/en/explore/projects/sakaka-solar-power-plant; Sudair 1.5 GW at ~1.239 USc/kWh; Shuaibah 600 MW world-record ~1.04 USc/kWh, https://reneweconomy.com.au/saudi-solar-plant-locks-in-new-record-low-price-for-power-1-04c-kwh/.
- Water and Electricity Regulatory Authority source locator: https://wera.gov.sa/en-us/.
- Saudi water tariff structure (commercial 9 SAR/m3 flat; industrial 6 SAR/m3 above 50 m3/month, plus sewerage and VAT): SWA bill calculator, https://www.swa.gov.sa/en/services/service-calculator/water-bill-calculator; NWC source locator: https://www.nwc.com.sa/English/OurServices/Pages/Tariffs.aspx.
- IRENA, "The cost of financing for renewable power" (2023): https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2023/May/IRENA_The_cost_of_financing_renewable_power_2023.pdf. Utility renewable WACC survey (~3.8-12%) anchoring the discount-rate band.
- General Authority for Statistics labor market data: https://www.stats.gov.sa/en. 2024 average non-Saudi worker wage ~4,376 SAR/month (~21 SAR/hour at 48 h/week) anchors the cleaning-labor rate envelope.
- Saudi Central Bank source locator for rate context: https://www.sama.gov.sa/en-US/Pages/default.aspx.

The economics registry values remain blocked until T3 confirms tariff class/offtake structure, water delivery mode, project WACC, equipment quotes, and useful-life assumptions. Note in particular: under PPA offtake (0.039-0.070 SAR/kWh benchmarks above), the central 0.18 SAR/kWh retail-offset valuation overstates the value of avoided soiling loss by roughly 3-4x, so mitigation rankings must be re-checked at the PPA-valued low bound.
