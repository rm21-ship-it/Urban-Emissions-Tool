# 🌍 Urban Emissions Savings Calculator

A Streamlit web app that estimates CO₂e reductions from **urban densification** and **electric vehicle adoption**, powered by a Weighted Least Squares regression model trained on Climate TRACE data across 99 countries.

---

## Quick Start

```bash
pip install streamlit numpy
streamlit run app_FINAL.py
```

---

## What the App Does

Users enter a city's **current** and **future** conditions — population, urban area, and EV share — and the app calculates:

- **VKT (Vehicle Kilometres Travelled) — per capita:** baseline and future per-person figures and the change
- **CO₂e Emissions — per capita:** baseline and future kg CO₂e per person and the change
- **Savings Breakdown:** per-capita-adjusted total savings split into densification vs. EV adoption effects (see Methodology below)
- **Real-World Equivalencies:** cars removed from roads, trees needed to offset, and social cost savings in USD — all based on per-capita-adjusted savings

> **Why per-capita only?** Showing total emissions can make growing cities look worse even when they're becoming more efficient per person. Since restricting growth in one city just pushes it elsewhere, the tool focuses on per-capita efficiency — the metric that reflects compact urban form performance.

---

## Required Files

All five files must be in the **same directory** as `app_FINAL.py`:

| File | Description | Required |
|------|-------------|----------|
| `app_FINAL.py` | Main Streamlit application | ✅ |
| `vkt_model_coefficients.json` | Regression coefficients and size-band thresholds | ✅ |
| `country_fixed_effects.json` | Country-level fixed effects (δ, reference = Afghanistan = 0) | ✅ |
| `country_emission_intensity.json` | Country-median EI in grams CO₂e per km | ✅ |
| `city_emission_intensity.json` | City-specific EI, 10,270 cities (key = `"City\|Country"`) | ✅ (optional fallback exists) |

---

## Model Overview

### Equation

```
ln(VKT_i) = β₀ + β₁·ln(pop_i) + β₂·ln(density_i)
           + γⱼ·SizeBand_j + δₖ·Country_k
           + β₃ⱼ·ln(pop_i)×SizeBand_j + β₄ⱼ·ln(density_i)×SizeBand_j + εᵢ
```

where `density_i = population_i / area_km2_i` (people per km²)

### Key Design Choices

- **WLS with inverse-population weights** — prevents megacities from dominating the loss function; ensures good fit across all city sizes
- **ln_density replaces ln_area** — eliminates multicollinearity between the two continuous predictors (VIF: 3.8 → 1.0, predictor correlation: r = 0.857 → r = 0.153). Predictions are mathematically identical to the old ln_area spec; only coefficient interpretability improves
- **Country fixed effects** — 99 countries, Afghanistan as reference (δ = 0). 90 of 98 estimated effects are statistically significant (p < 0.05)
- **Size-band interactions** — each band (Small / Medium / Large) gets its own population and density elasticity

### Elasticities (from `vkt_model_coefficients.json`)

| Band | Population Threshold | Pop β | Density β | Interpretation |
|------|---------------------|-------|-----------|----------------|
| Small | ≤ 88,335 | 1.583 | −0.605 | Super-linear VKT growth; strongest compactness benefit |
| Medium | 88,335 – 329,480 | 1.283 | −0.512 | Most efficient VKT scaling |
| Large | > 329,480 | 1.036 | −0.206 | Near-proportional; density dividend mostly captured |

Density β is negative: a 1% increase in density reduces VKT by |β|%.

### Performance

| Metric | Value |
|--------|-------|
| Test R² | 0.7848 |
| Training R² | 0.6777 |
| RMSE (log scale) | 0.7932 |
| Aggregate Bias | +2.28% |
| Pearson Correlation | 0.8859 |
| Cities in training | 8,396 |
| Countries | 99 |

---

## JSON File Formats

### `vkt_model_coefficients.json`
```json
{
  "intercept": 7.5948,
  "ln_pop_S": 1.5830,   "ln_pop_M": 1.2825,   "ln_pop_L": 1.0360,
  "ln_density_S": -0.6053, "ln_density_M": -0.5124, "ln_density_L": -0.2065,
  "intercept_dev_S": -3.1635, "intercept_dev_M": -0.5296,
  "size_threshold_S_M": 88335.2,
  "size_threshold_M_L": 329479.8
}
```

### `country_fixed_effects.json`
```json
{ "United States": 2.717, "Afghanistan": 0.0, "Bangladesh": -1.176, ... }
```
Range: −1.18 (Bangladesh) to +2.72 (United States). Cities without a country match fall back to the median fixed effect across all countries.

### `country_emission_intensity.json`
```json
{ "United States": 331.0, "India": 117.7, ..., "_default": 226.2 }
```
Units: **grams CO₂e per vehicle kilometre**. The `_default` key (226.2) is used when a country is not found.

### `city_emission_intensity.json`
```json
{
  "Portland|United States": { "name": "Portland", "country": "United States", "ei": 330.2, "pop": 650000, "area": 375.0 },
  ...
}
```
Key format: `"CityName|Country"`. Contains 10,270 entries derived from Climate TRACE emissions data.

---

## Emission Intensity Lookup Chain

When computing emissions the app resolves EI in priority order:

1. **City-specific** — exact match on `"CityName|Country"` in `city_emission_intensity.json`
2. **Country median** — match on country name in `country_emission_intensity.json`
3. **Global default** — 226.2 g CO₂e/km (the `_default` value in the country file)

The badge displayed below the city/country inputs shows which tier was used ("City-specific", country median with city count, or default).

---

## Emissions Calculation

```
Total CO₂e (tonnes/year) = VKT × [(1 − EV_frac) × EI_ice + EV_frac × EI_ev] / 1,000,000

EI_ice  = Emission intensity from JSON lookup (g CO₂e/km)
EI_ev   = Grid intensity (g CO₂/kWh) × EV efficiency (0.20 kWh/km)
EV_frac = EV share / 100
```

Grid carbon intensities are hardcoded in `GRID_INTENSITY` (sourced from Ember GER 2024–2025 and IEA 2025) because they come from an external source and update independently of the VKT model pipeline.

### Per-Capita-Adjusted Savings

Results are reported in per-capita terms only (total VKT and total emissions rows are intentionally excluded). The savings breakdown uses a **per-capita-adjusted** approach that answers: *"how much less does the future compact city emit compared to a city of the same future size but with today's per-capita inefficiency?"*

```
dem_adjusted = (em_baseline_per_capita − em_future_per_capita) × future_population

where:
  em_baseline_per_capita = total_baseline_emissions / current_population
  em_future_per_capita   = total_future_emissions   / future_population
```

This avoids penalising city growth: a city that grows its population while improving per-capita efficiency will show positive savings, because the comparison baseline is "a city of that same future size but as inefficient as today."

### Savings Breakdown

The per-capita-adjusted total is decomposed into two effects:

- **Densification effect** = `(em_baseline_per_cap − em_counterfactual_per_cap) × future_pop`
  where `em_counterfactual` = emissions using future VKT but current EV share (isolates VKT change)
- **EV adoption effect** = `(em_counterfactual_per_cap − em_future_per_cap) × future_pop`
  (isolates the shift in EV share at fixed future VKT)

Both effects sum to `dem_adjusted`. Real-world equivalencies (cars, trees, social cost) all reflect `dem_adjusted`.

---

## Constants and References

| Constant | Value | Source |
|----------|-------|--------|
| EV efficiency | 0.20 kWh/km | EPA / DOE average BEV |
| Social cost of carbon | $100 USD/tonne CO₂e | EPA SC-GHG |
| Car equivalency | 4.6 tonnes CO₂e/year | EPA Equivalencies |
| Tree equivalency | 0.021 tonnes CO₂e/year | EPA Equivalencies |

---

## Inputs Reference

| Input | Where | Notes |
|-------|-------|-------|
| Country | Sidebar / Location | Drives country FE and EI fallback |
| City name | Sidebar / Location | Used for city-specific EI lookup |
| Current Population | Current Conditions | Used for size band and VKT prediction |
| Current Urban Area (km²) | Current Conditions | Combined with pop to compute density |
| Current EV Share (%) | Current Conditions | Slider 0–100% |
| Future Population | Future Scenario | Can be different size band from current |
| Future Urban Area (km²) | Future Scenario | Smaller area = higher density = less VKT |
| Future EV Share (%) | Future EV Adoption | Slider 0–100% |

The density change summary (Δ population, Δ area, Δ density) is displayed live as inputs change.

---

## Data Sources

| Data | Source |
|------|--------|
| VKT training data and vehicle emission intensities | [Climate TRACE (2022)](https://climatetrace.org/) |
| Grid carbon intensities | [Ember GER 2024–2025](https://ember-energy.org/) / [IEA 2025](https://www.iea.org/) |
| Social cost of carbon | [EPA SC-GHG](https://www.epa.gov/environmental-economics/scghg) |
| Car and tree equivalencies | [EPA Equivalencies Calculator](https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator) |
| BEV efficiency | [EPA / DOE](https://www.fueleconomy.gov/feg/evtech.shtml) |

---

## Limitations

- **City-level uncertainty is high.** The model achieves 98% accuracy in aggregate but individual city predictions can be far off, especially for small or atypical cities. Use results for directional scenario comparison rather than precise city forecasts.
- **Country fixed effects are static.** The δ values capture historical national context (vehicle ownership rates, fuel prices, road infrastructure, cultural norms). Policy shifts not reflected in the training data are not captured.
- **EV grid emissions use 2024–2025 grid intensity.** As grids decarbonise, the EV emission benefit will grow over time; this tool does not model grid trajectory.
- **No land use or modal shift modelling.** The density effect captures the empirical relationship between urban compactness and total VKT. It does not separately model walking, cycling, or transit mode share.

---

## File History

| Version | Key Changes |
|---------|------------|
| app_FINAL_v4.py (current) | Per-capita-only display (totals removed); per-capita-adjusted savings breakdown and equivalencies; `ln_density` predictor |
| app_FINAL_new.py (v3) | `ln_density` replaces `ln_area` as predictor; density computed internally; `city_emission_intensity.json` added; dual current/future input architecture |
| app_FINAL.py (v2) | `ln_area` predictor (VIF = 3.8); single population snapshot; country-level EI only |
