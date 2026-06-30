# Calibration Source Bibliography

Retrieval date for web sources: 2026-06-30.

## PV Soiling And Rain Cleaning

- Kimber, A., Mitchell, L., Nogradi, S., and Wenger, H. "The effect of soiling on large grid-connected photovoltaic systems in California and the Southwest region of the United States." IEEE WCPEC, 2006. Used as a provenance source for the Kimber-style empirical soiling/rain-reset framing. DOI or IEEE URL should be refreshed before publication use.
- Ilse, K. et al. "Techno-Economic Assessment of Soiling Losses and Mitigation Strategies for Solar Power Generation." Joule, 2019. DOI/source locator: https://doi.org/10.1016/j.joule.2019.08.019. Used for global soiling-economics context, not as a direct Riyadh measurement.
- NASA POWER documentation: https://power.larc.nasa.gov/docs/. Used for the project's Riyadh weather-provider context; not a soiling measurement source.
- NREL/NLR PV soiling information page: https://www.nrel.gov/pv/soiling.html. Used as a broad reference that soiling varies by location, weather, and cleaning conditions.

## Dust Events And Saudi Applicability

- Saudi/Gulf dust-storm climatology papers and official meteorological context should be used for the next refinement pass. The current registry treats seasonal and dust-event values as inferred because no single Riyadh site-deposition dataset was available in this worktree.
- NASA POWER and Riyadh 2025 validation outputs in `PROGRESS.md` provide weather context, but not dust deposition or measured soiling-ratio data.

## Bird Droppings And Localized Obstruction

- General PV soiling and partial-obstruction literature identifies biological droppings as a localized soiling mode. No Saudi utility-scale bird-dropping frequency, coverage, persistence, or power-loss source was found for this T5 pass.
- The bird-dropping parameters are therefore assumed/provisional and require site observation, image labels, or maintenance logs.

## Computer Vision

- DeepSolarEye and related PV image-inspection literature were used only as weak evidence for provisional detector-performance ranges. Source locator for refresh: https://arxiv.org/search/cs?query=DeepSolarEye&searchtype=all.
- T2 must replace these values with a measured confusion matrix on the selected inspection imagery and model.

## Drone Inspection And Cleaning

- DJI Matrice 350 RTK official specifications: https://enterprise.dji.com/matrice-350-rtk/specs. Used for a quoted maximum flight-time bound; the central registry value is derated for payload, heat, wind, and battery aging.
- Cleaning rate, labor hours, and water use are inferred placeholders until T2 or T3 provides a cleaning method, contractor quote, or measured time-and-motion data.

## Coatings, Dew, Cooling, And Water Collection

- MIT News article on electrostatic water-free PV dust removal: https://news.mit.edu/2022/solar-panels-dust-magnets-0311. Used as context that dry cleaning and dust adhesion are active research areas, not as the selected SolarClean coating.
- Science Advances electrostatic PV dust-removal article: https://www.science.org/doi/10.1126/sciadv.abm0078. Used for dust-removal context and the importance of humidity/moisture.
- Hydrophobic/nanotextured self-cleaning coating and radiative/hydrogel cooling literature were used as broad evidence. T3 must replace registry values with the selected KAUST-inspired coating evidence, product data, or test data before decision use.

## Economics

- Saudi Electricity Company tariff page/source locator: https://www.se.com.sa/en-us/Customers/Pages/TariffRates.aspx.
- Water and Electricity Regulatory Authority source locator: https://wera.gov.sa/en-us/.
- Saudi National Water Company tariff source locator: https://www.nwc.com.sa/English/OurServices/Pages/Tariffs.aspx.
- Saudi Central Bank source locator for rate context: https://www.sama.gov.sa/en-US/Pages/default.aspx.
- General Authority for Statistics source locator for labor market context: https://www.stats.gov.sa/en.

The economics registry values are blocked placeholders until T3 confirms tariff class, water delivery mode, project WACC, equipment quotes, and useful-life assumptions.
