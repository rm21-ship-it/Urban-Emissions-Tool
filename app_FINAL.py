# -*- coding: utf-8 -*-
"""
VKT to Emissions Web Tool — Streamlit App (FINAL v4 — DENSITY MODEL + PER-CAPITA FOCUS)
All model parameters loaded from JSON files exported by aligned pipeline.
Only GRID_INTENSITY hardcoded (external source: Ember/IEA).

KEY CHANGES vs. v3:
  1. DENSITY MODEL: ln_area replaced with ln_density = ln(pop/area) as model predictor.
     - Coefficients JSON now contains ln_density_S/M/L instead of ln_area_S/M/L
     - predict_vkt() computes density internally from user-supplied pop + area
     - User inputs are UNCHANGED (still population + area in km²)

  2. PER-CAPITA FOCUS: Total VKT and total emissions rows removed from results display.
     - Only per-capita VKT and per-capita CO2e are shown (avoids penalising city growth)

  3. PER-CAPITA-ADJUSTED SAVINGS BREAKDOWN:
     - dem_adjusted = (baseline_em_per_capita - future_em_per_capita) x future_population
     - This compares: "future city at baseline per-capita inefficiency" vs actual future city
     - Densification and EV effects both computed on the same per-capita-adjusted basis
     - Real-world equivalencies (cars, trees, social cost) reflect dem_adjusted

CANONICAL MODEL EQUATION:
  ln(VKT_i) = B0 + B1*ln(pop_i) + B2*ln(density_i)
              + Gj*SizeBand_j + Dk*Country_k
              + B3j*ln(pop_i)*SizeBand_j + B4j*ln(density_i)*SizeBand_j + Ei
  where density_i = population_i / area_km2_i  (people per km2)

Required files (same directory):
  - vkt_model_coefficients.json
  - country_fixed_effects.json
  - country_emission_intensity.json
  - city_emission_intensity.json (optional)

To run: pip install streamlit numpy && streamlit run app_FINAL_v4.py
"""

import streamlit as st
import numpy as np
import json
import os

# ===============================================================================
# DATA LOADING
# ===============================================================================

def load_json(filename, required=True):
    script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd()
    filepath = os.path.join(script_dir, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        if required:
            st.error(f"Required file not found: {filename}\nExpected: {filepath}\nRun export_for_web() to generate.")
            st.stop()
        return {}

VKT_MODEL_COEFFICIENTS = load_json('vkt_model_coefficients.json')
COUNTRY_FE = load_json('country_fixed_effects.json')
_country_ei = load_json('country_emission_intensity.json')
EMISSION_INTENSITY = _country_ei
EI_DEFAULT = _country_ei.get('_default', 226.2)
CITY_EI_DATA = load_json('city_emission_intensity.json', required=False)

# ===============================================================================
# GRID INTENSITY (grams CO2 per kWh) — External Sources
# Ember GER 2024-2025, IEA Emission Factors 2025, Our World in Data
# ===============================================================================
GRID_INTENSITY = {
    "Austria": 140, "Belarus": 350, "Belgium": 160, "Czechia": 450, "Denmark": 165,
    "Finland": 130, "France": 56, "Germany": 350, "Greece": 320, "Hungary": 220,
    "Iceland": 28, "Ireland": 280, "Italy": 210, "Netherlands": 250, "Norway": 30,
    "Poland": 660, "Portugal": 180, "Romania": 280, "Russia": 310, "Serbia": 650,
    "Spain": 185, "Sweden": 45, "Switzerland": 58, "Turkey": 380, "Ukraine": 290,
    "United Kingdom": 200,
    "Canada": 120, "Cuba": 550, "Dominican Republic": 450, "El Salvador": 300,
    "Guatemala": 350, "Haiti": 700, "Honduras": 380, "Mexico": 400, "Nicaragua": 350,
    "United States": 380, "Argentina": 240, "Bolivia": 400, "Brazil": 85, "Chile": 220,
    "Colombia": 180, "Ecuador": 250, "Paraguay": 60, "Peru": 250, "Venezuela": 200,
    "China": 530, "Indonesia": 600, "Japan": 450, "Malaysia": 420, "Myanmar": 350,
    "North Korea": 600, "Philippines": 550, "South Korea": 420, "Taiwan": 500,
    "Thailand": 410, "Vietnam": 480,
    "Afghanistan": 450, "Bangladesh": 520, "India": 710, "Nepal": 50,
    "Pakistan": 420, "Sri Lanka": 400,
    "Azerbaijan": 450, "Kazakhstan": 580, "Tajikistan": 50, "Uzbekistan": 500,
    "Algeria": 480, "Egypt": 450, "Iran": 480, "Iraq": 550, "Israel": 420,
    "Jordan": 400, "Libya": 550, "Morocco": 560, "Palestine": 500,
    "Saudi Arabia": 570, "Syria": 500, "Tunisia": 480,
    "United Arab Emirates": 450, "Yemen": 600,
    "Angola": 280, "Benin": 650, "Burkina Faso": 620, "Cameroon": 300,
    "Chad": 700, "Cote d'Ivoire": 450, "Democratic Republic of the Congo": 50,
    "Ethiopia": 35, "Ghana": 350, "Guinea": 350, "Kenya": 350,
    "Madagascar": 550, "Mali": 550, "Mozambique": 120, "Niger": 650,
    "Nigeria": 400, "Senegal": 550, "Sierra Leone": 600, "Somalia": 700,
    "South Africa": 850, "South Sudan": 700, "Sudan": 350, "Tanzania": 400,
    "Togo": 550, "Uganda": 100, "Zambia": 50, "Zimbabwe": 550,
    "Australia": 510, "New Zealand": 95,
    "_default": 450
}

# ===============================================================================
# CONSTANTS (with references)
# ===============================================================================
EV_EFFICIENCY = 0.20        # kWh per km — EPA average BEV
SOCIAL_COST = 100           # USD per tonne CO2e — EPA SC-GHG
TONNES_PER_CAR = 4.6        # tonnes CO2e per year — EPA Equivalencies
TONNES_PER_TREE = 0.021     # tonnes CO2e per year — EPA Equivalencies

SIZE_BAND_LABELS = {'S': 'Small', 'M': 'Medium', 'L': 'Large'}

# ===============================================================================
# HELPER FUNCTIONS
# ===============================================================================

def get_cities_for_country(country):
    return sorted(set(d['name'] for d in CITY_EI_DATA.values() if d['country'] == country))

def count_cities_for_country(country):
    return sum(1 for d in CITY_EI_DATA.values() if d['country'] == country)

def get_city_ei(city_name, country):
    key = f"{city_name}|{country}"
    return CITY_EI_DATA[key]['ei'] if key in CITY_EI_DATA else None

def get_size_band(pop):
    if pop <= VKT_MODEL_COEFFICIENTS['size_threshold_S_M']:
        return 'S'
    elif pop <= VKT_MODEL_COEFFICIENTS['size_threshold_M_L']:
        return 'M'
    return 'L'

def get_country_fe(country):
    return COUNTRY_FE.get(country, np.median(list(COUNTRY_FE.values())))

def get_emission_intensity(city_name, country):
    city_ei = get_city_ei(city_name, country)
    city_count = count_cities_for_country(country)
    if city_ei is not None:
        return city_ei, True, city_count
    return EMISSION_INTENSITY.get(country, EI_DEFAULT), False, city_count

def get_grid_intensity(country):
    return GRID_INTENSITY.get(country, GRID_INTENSITY['_default'])

def predict_vkt(population, area, country):
    band = get_size_band(population)
    c = VKT_MODEL_COEFFICIENTS
    density = population / area                       # people per km2
    ln_vkt = (c['intercept'] + c.get(f'intercept_dev_{band}', 0)
              + c[f'ln_pop_{band}']     * np.log(population)
              + c[f'ln_density_{band}'] * np.log(density)
              + get_country_fe(country))
    return np.exp(ln_vkt)

def calc_emissions(vkt, ei, country, ev_pct):
    ev_ei = get_grid_intensity(country) * EV_EFFICIENCY
    frac = ev_pct / 100
    ice = vkt * (1 - frac) * ei / 1e6
    ev = vkt * frac * ev_ei / 1e6
    return ice + ev, ice, ev

# ===============================================================================
# PAGE CONFIG & STYLING
# ===============================================================================

st.set_page_config(page_title="Urban Emissions Calculator", page_icon="&#127757;", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        padding: 2.5rem 2rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        text-align: center;
        box-shadow: 0 8px 32px rgba(0,0,0,0.15);
    }
    .main-header h1 {
        color: #ffffff;
        font-size: 2.2rem;
        font-weight: 700;
        margin: 0 0 0.4rem 0;
        letter-spacing: -0.5px;
    }
    .main-header p {
        color: #94b8c8;
        font-size: 1.05rem;
        margin: 0;
        font-weight: 400;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        font-family: 'JetBrains Mono', monospace !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.8;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.85rem !important;
        font-family: 'JetBrains Mono', monospace !important;
    }

    .section-header {
        background: linear-gradient(90deg, #f0f7ff 0%, #ffffff 100%);
        border-left: 4px solid #2c5364;
        padding: 0.8rem 1.2rem;
        border-radius: 0 8px 8px 0;
        margin: 1rem 0 0.8rem 0;
        font-size: 1.1rem;
        font-weight: 600;
        color: #1a3040;
    }

    .results-banner {
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        padding: 1.8rem 2rem;
        border-radius: 14px;
        text-align: center;
        margin: 1rem 0;
        box-shadow: 0 6px 24px rgba(0,0,0,0.12);
    }
    .results-banner h2 {
        color: #ffffff;
        font-size: 1.6rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: 1px;
    }
    .results-banner p {
        color: #94b8c8;
        font-size: 1.1rem;
        margin: 0.3rem 0 0 0;
    }

    .badge-city {
        background: linear-gradient(135deg, #d4edda, #c3e6cb);
        border: 1px solid #a3d9a5;
        border-radius: 10px;
        padding: 0.7rem 1.2rem;
        font-size: 0.95rem;
        color: #155724;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }
    .badge-country {
        background: linear-gradient(135deg, #fff3cd, #ffeaa7);
        border: 1px solid #f0d78c;
        border-radius: 10px;
        padding: 0.7rem 1.2rem;
        font-size: 0.95rem;
        color: #856404;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }
    .badge-band {
        background: linear-gradient(135deg, #d1ecf1, #bee5eb);
        border: 1px solid #9ad0d9;
        border-radius: 10px;
        padding: 0.7rem 1.2rem;
        font-size: 0.95rem;
        color: #0c5460;
        font-weight: 500;
    }

    .equiv-card {
        border-radius: 12px;
        padding: 1.2rem;
        text-align: center;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        border: 1px solid rgba(0,0,0,0.06);
    }
    .equiv-card-green {
        background: linear-gradient(135deg, #e8f5e9, #c8e6c9);
        border-color: #a5d6a7;
        color: #1b5e20 !important;
    }
    .equiv-card-red {
        background: linear-gradient(135deg, #ffebee, #ffcdd2);
        border-color: #ef9a9a;
        color: #7f1d1d !important;
    }
    .equiv-number {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0.3rem 0;
        color: inherit !important;
    }
    .equiv-label {
        font-size: 0.85rem;
        font-weight: 500;
        color: inherit !important;
        opacity: 0.75;
    }
    .equiv-icon {
        font-size: 1.6rem;
    }

    .breakdown-card {
        border-radius: 10px;
        padding: 1rem 1.2rem;
        display: flex;
        align-items: center;
        gap: 0.8rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    .breakdown-saved {
        background: linear-gradient(135deg, #e3f2fd, #bbdefb);
        border: 1px solid #90caf9;
        color: #0d47a1;
    }
    .breakdown-added {
        background: linear-gradient(135deg, #fff3e0, #ffe0b2);
        border: 1px solid #ffcc80;
        color: #e65100;
    }

    .change-strip {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        font-size: 0.88rem;
        color: #495057;
        font-family: 'JetBrains Mono', monospace;
        border: 1px solid #e9ecef;
    }

    .styled-divider {
        border: none;
        height: 1px;
        background: linear-gradient(90deg, transparent, #d0d7de, transparent);
        margin: 1.5rem 0;
    }

    .footer-text {
        text-align: center;
        font-size: 0.8rem;
        color: #6c757d;
        padding: 1rem 0;
        line-height: 1.6;
    }
    .footer-text a {
        color: #2c5364;
        text-decoration: none;
        font-weight: 500;
    }

    /* ── Disclaimer block ── */
    .disc-banner {
        background: #f0f4f8;
        border-radius: 10px;
        padding: 0.9rem 1.2rem;
        margin-bottom: 1rem;
        display: flex;
        align-items: flex-start;
        gap: 12px;
        border: 1px solid #d8e2ec;
    }
    .disc-banner p {
        margin: 0;
        font-size: 0.88rem;
        color: #3d5166;
        line-height: 1.65;
    }
    .disc-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
    }
    .disc-card {
        background: #ffffff;
        border-radius: 10px;
        padding: 0.9rem 1rem;
        border: 1px solid #d8e2ec;
    }
    .disc-card p {
        margin: 0;
    }
    .disc-card-label {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #5a7a95;
        font-weight: 600;
        margin-bottom: 4px !important;
    }
    .disc-card-body {
        font-size: 0.85rem;
        color: #3d5166;
        line-height: 1.6;
    }
    .disc-footer {
        font-size: 0.78rem;
        color: #7a8fa0;
        margin: 0.6rem 0 0;
        text-align: center;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ===============================================================================
# HEADER
# ===============================================================================

st.markdown("""
<div class="main-header">
    <h1>&#127757; Urban Emissions Savings Calculator</h1>
    <p>Estimate CO&#8322;e reductions from urban densification and electric vehicle adoption</p>
</div>

<div style="margin: 1rem 0 1.5rem;">
  <div class="disc-banner">
    <span style="font-size: 1.1rem; flex-shrink: 0; margin-top: 2px;">&#128269;</span>
    <p><strong>About this tool &#8212;</strong> An estimation tool that uses population density as a
    coarse proxy for compact urban form and the factors that reduce driving (vehicle kilometres
    travelled). Not intended to replace more accurate transport models &#8212; designed for rapid,
    low-effort estimates.</p>
  </div>

  <div class="disc-grid">
    <div class="disc-card" style="border-left: 3px solid #378ADD;">
      <p class="disc-card-label">Time horizon</p>
      <p class="disc-card-body">Maximum window of <strong>30 years</strong>. Estimates carry
      expected uncertainty of <strong>&#177; 20%</strong>.</p>
    </div>
    <div class="disc-card" style="border-left: 3px solid #EF9F27;">
      <p class="disc-card-label">Atypical cities</p>
      <p class="disc-card-body">Uncertainty is higher for cities uncharacteristic of their
      country &#8212; e.g. New York vs U.S. norms.</p>
    </div>
    <div class="disc-card" style="border-left: 3px solid #1D9E75;">
      <p class="disc-card-label">What density captures</p>
      <p class="disc-card-body">Reflects changes from <strong>reduced trip length</strong> and
      <strong>modal shift</strong> toward non-driving alternatives.</p>
    </div>
    <div class="disc-card" style="border-left: 3px solid #D85A30;">
      <p class="disc-card-label">What the model omits</p>
      <p class="disc-card-body">Wealth, car ownership, and road funding are excluded. Results
      reflect compact form <em>all else being equal</em>.</p>
    </div>
  </div>

  <p class="disc-footer">
    For factors influencing driving, see Appendix R1 &nbsp;&#183;&nbsp;
    Detailed methods about how the tool was created and calibrated can be found in a soon-to-be-published journal article.
  </p>
</div>
""", unsafe_allow_html=True)

# ===============================================================================
# MODEL INFO EXPANDER
# ===============================================================================

c = VKT_MODEL_COEFFICIENTS
with st.expander("About the Model & Data Sources"):
    st.markdown(f"""
**Model:** Weighted Least Squares + Country Fixed Effects + Size-Band Interactions  
**Performance:** Test R2 = 0.7848 | Bias = +2.28% | 8,396 cities across 99 countries

| Band | Population B | Density B | Interpretation |
|------|-------------|-----------|----------------|
| Small (<= {c['size_threshold_S_M']:,.0f}) | {c['ln_pop_S']:.4f} | {c['ln_density_S']:.4f} | Near-linear scaling, strongest compactness benefit |
| Medium | {c['ln_pop_M']:.4f} | {c['ln_density_M']:.4f} | Most efficient VKT scaling |
| Large (> {c['size_threshold_M_L']:,.0f}) | {c['ln_pop_L']:.4f} | {c['ln_density_L']:.4f} | Moderate scaling, smallest compactness benefit |

Density B is negative: denser cities drive less (a 1% increase in density reduces VKT by |B|%).  
Density is computed internally from your population and area inputs -- no extra input required.

**Emission Intensity (EI):** City-level and country-median EI computed from Climate TRACE data as
emission_tonnes x 10^6 / VKT (grams CO2e per kilometre). All cities in the quality-filtered dataset
with valid emissions contribute to both city-level and country-level lookups.
Cities in database: {len(CITY_EI_DATA):,}

**References:**
- [Climate TRACE (2022)](https://climatetrace.org/) -- VKT model training data & vehicle emission intensities
- [Ember GER 2024-2025](https://ember-energy.org/latest-insights/global-electricity-review-2025/) -- Grid carbon intensities (grams CO2 per kWh)
- [IEA Emission Factors 2025](https://www.iea.org/data-and-statistics/data-product/emissions-factors-2025) -- Grid carbon intensities
- [Our World in Data](https://ourworldindata.org/grapher/carbon-intensity-electricity) -- Supplementary grid data
- [EPA SC-GHG](https://www.epa.gov/environmental-economics/scghg) -- Social cost of carbon (100 USD per tonne)
- [EPA Equivalencies](https://www.epa.gov/energy/greenhouse-gas-equivalencies-calculator) -- Cars (4.6 tonnes CO2e per year), Trees (0.021 tonnes CO2e per year)
- [EPA / DOE](https://www.fueleconomy.gov/feg/evtech.shtml) -- Average BEV efficiency (0.20 kWh per kilometre)
    """)

# ===============================================================================
# INPUTS
# ===============================================================================

st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)
countries = sorted(COUNTRY_FE.keys())

col1, col2 = st.columns(2)
with col1:
    st.markdown('<div class="section-header">&#128205; Location</div>', unsafe_allow_html=True)
    country = st.selectbox("Country", countries,
                           index=countries.index("United States") if "United States" in countries else 0)
    cities = get_cities_for_country(country)
    opts = ["— Enter custom city name —"] + cities
    sel = st.selectbox(f"City  ({len(cities)} in database)", opts)
    city_name = st.text_input("Enter city name", "MyCity") if sel == opts[0] else sel

with col2:
    st.markdown('<div class="section-header">&#128202; Current Conditions</div>', unsafe_allow_html=True)
    pop_cur = st.number_input("Current Population", 1_000, 50_000_000, 100_000, 10_000)
    area_cur = st.number_input("Current Urban Area (square kilometres)", 1.0, 10_000.0, 60.0, 10.0)
    ev_cur = st.slider("Current EV Share (%)", 0, 100, 15)

st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)

col3, col4 = st.columns(2)
with col3:
    st.markdown('<div class="section-header">&#128302; Future Scenario</div>', unsafe_allow_html=True)
    pop_fut = st.number_input("Future Population", 1_000, 50_000_000, 105_000, 10_000)
    area_fut = st.number_input("Future Urban Area (square kilometres)", 1.0, 10_000.0, 56.0, 10.0)
with col4:
    st.markdown('<div class="section-header">&#9889; Future EV Adoption</div>', unsafe_allow_html=True)
    ev_fut = st.slider("Future EV Share (%)", 0, 100, 30)
    dpop = (pop_fut - pop_cur) / pop_cur * 100
    darea = (area_fut - area_cur) / area_cur * 100
    dcur = pop_cur / area_cur
    dfut = pop_fut / area_fut
    ddens = (dfut - dcur) / dcur * 100
    st.markdown(
        f'<div class="change-strip">'
        f'Population: <b>{dpop:+.1f}%</b> &nbsp;&#183;&nbsp; '
        f'Area: <b>{darea:+.1f}%</b> &nbsp;&#183;&nbsp; '
        f'Density: <b>{ddens:+.1f}%</b> ({dcur:,.0f} &#8594; {dfut:,.0f} people per square kilometre)'
        f'</div>',
        unsafe_allow_html=True
    )

# ===============================================================================
# EI & SIZE BAND INFO
# ===============================================================================

st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)

ei_val, is_city, n_city = get_emission_intensity(city_name, country)

if is_city:
    st.markdown(
        f'<div class="badge-city">&#128205; City-specific Emission Intensity: '
        f'<b>{ei_val:.1f} grams CO&#8322;e per kilometre</b></div>',
        unsafe_allow_html=True)
elif n_city > 0:
    st.markdown(
        f'<div class="badge-country">&#128506; <b>{country}</b> median Emission Intensity: '
        f'<b>{ei_val:.1f} grams CO&#8322;e per kilometre</b> (based on {n_city} cities)</div>',
        unsafe_allow_html=True)
else:
    st.markdown(
        f'<div class="badge-country">&#127760; Default Emission Intensity: '
        f'<b>{ei_val:.1f} grams CO&#8322;e per kilometre</b></div>',
        unsafe_allow_html=True)

band_cur = get_size_band(pop_cur)
band_fut = get_size_band(pop_fut)
band_text = (f"&#128202; Size Band: <b>{SIZE_BAND_LABELS[band_cur]}</b> "
             f"(Population &#946; = {c[f'ln_pop_{band_cur}']:.3f}, Density &#946; = {c[f'ln_density_{band_cur}']:.3f})")
if band_cur != band_fut:
    band_text += f" &#8594; <b>{SIZE_BAND_LABELS[band_fut]}</b>"
st.markdown(f'<div class="badge-band">{band_text}</div>', unsafe_allow_html=True)

# ===============================================================================
# CALCULATE BUTTON
# ===============================================================================

st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)

if st.button("Calculate Emissions Savings", type="primary", use_container_width=True):

    # -- Compute --
    vkt_c = predict_vkt(pop_cur, area_cur, country)
    vkt_f = predict_vkt(pop_fut, area_fut, country)

    em_c, _, _ = calc_emissions(vkt_c, ei_val, country, ev_cur)
    em_f, _, _ = calc_emissions(vkt_f, ei_val, country, ev_fut)

    em_c_per_cap = em_c / pop_cur
    em_f_per_cap = em_f / pop_fut
    dem_adjusted = (em_c_per_cap - em_f_per_cap) * pop_fut

    em_vo, _, _ = calc_emissions(vkt_f, ei_val, country, ev_cur)
    em_vo_per_cap = em_vo / pop_fut
    vkt_eff = (em_c_per_cap - em_vo_per_cap) * pop_fut
    ev_eff = (em_vo_per_cap - em_f_per_cap) * pop_fut

    # -- Results Banner --
    st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="results-banner">'
        f'<h2>EMISSION SAVINGS RESULTS</h2>'
        f'<p>{city_name}, {country}</p>'
        f'</div>',
        unsafe_allow_html=True)

    # -- VKT Section (per capita only) --
    st.markdown('<div class="section-header">&#128663; Vehicle Kilometres Travelled (VKT) &#8212; Per Capita</div>',
                unsafe_allow_html=True)

    vpc_c = vkt_c / pop_cur
    vpc_f = vkt_f / pop_fut

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Baseline", f"{vpc_c:,.0f} km per person per year")
    with c2:
        st.metric("Future", f"{vpc_f:,.0f} km per person per year")
    with c3:
        vpc_change = vpc_f - vpc_c
        vpc_change_p = vpc_change / vpc_c * 100
        st.metric("Change per Person", f"{vpc_change:,.0f} km per person per year",
                  f"{vpc_change_p:+.1f}%", delta_color="inverse")

    # -- Emissions Section (per capita only) --
    st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">&#127757; CO&#8322;e Emissions &#8212; Per Capita</div>',
                unsafe_allow_html=True)

    epc_c = em_c * 1000 / pop_cur
    epc_f = em_f * 1000 / pop_fut

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Baseline", f"{epc_c:,.0f} kg CO2e per person per year")
    with c2:
        st.metric("Future", f"{epc_f:,.0f} kg CO2e per person per year")
    with c3:
        epc_change = epc_f - epc_c
        epc_change_p = epc_change / epc_c * 100
        st.metric("Change per Person", f"{epc_change:,.0f} kg CO2e per person per year",
                  f"{epc_change_p:+.1f}%", delta_color="inverse")

    # -- Breakdown --
    st.markdown("**Savings Breakdown:**")
    st.markdown(
        '<p style="font-size:0.88rem;color:#6c757d;margin:-0.3rem 0 0.8rem 0;">'
        'Compared to a future city as sprawling as today but scaled to the future population.</p>',
        unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if vkt_eff >= 0:
            st.markdown(
                f'<div class="breakdown-card breakdown-saved">'
                f'<span style="font-size:1.5rem">&#127963;</span>'
                f'<div><b>Densification Effect (VKT efficiency)</b><br>'
                f'<span style="font-family:JetBrains Mono,monospace;font-size:1.1rem">'
                f'{vkt_eff:,.0f}</span> tonnes CO&#8322;e saved per year</div>'
                f'</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="breakdown-card breakdown-added">'
                f'<span style="font-size:1.5rem">&#127963;</span>'
                f'<div><b>Densification Effect (VKT efficiency)</b><br>'
                f'<span style="font-family:JetBrains Mono,monospace;font-size:1.1rem">'
                f'{-vkt_eff:,.0f}</span> tonnes CO&#8322;e added per year</div>'
                f'</div>', unsafe_allow_html=True)
    with c2:
        if ev_eff >= 0:
            st.markdown(
                f'<div class="breakdown-card breakdown-saved">'
                f'<span style="font-size:1.5rem">&#9889;</span>'
                f'<div><b>EV Adoption Effect (fleet electrification)</b><br>'
                f'<span style="font-family:JetBrains Mono,monospace;font-size:1.1rem">'
                f'{ev_eff:,.0f}</span> tonnes CO&#8322;e saved per year</div>'
                f'</div>', unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="breakdown-card breakdown-added">'
                f'<span style="font-size:1.5rem">&#9889;</span>'
                f'<div><b>EV Adoption Effect (fleet electrification)</b><br>'
                f'<span style="font-family:JetBrains Mono,monospace;font-size:1.1rem">'
                f'{-ev_eff:,.0f}</span> tonnes CO&#8322;e added per year</div>'
                f'</div>', unsafe_allow_html=True)

    # -- Equivalencies --
    st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-header">&#127807; Real-World Equivalencies</div>', unsafe_allow_html=True)

    cars = dem_adjusted / TONNES_PER_CAR
    trees = dem_adjusted / TONNES_PER_TREE
    cost = dem_adjusted * SOCIAL_COST

    card_class = "equiv-card-green" if dem_adjusted >= 0 else "equiv-card-red"
    sign = "" if dem_adjusted >= 0 else "-"
    abs_cars = abs(cars)
    abs_trees = abs(trees)
    abs_cost = abs(cost)

    cars_label = "cars removed from roads per year" if dem_adjusted >= 0 else "additional car-equivalents per year"
    if abs_trees >= 1e6:
        trees_str = f"{sign}{abs_trees / 1e6:.1f} million"
    else:
        trees_str = f"{sign}{abs_trees:,.0f}"
    trees_label = "trees (1-year carbon offset)" if dem_adjusted >= 0 else "trees needed to offset increase"

    if abs_cost >= 1e6:
        cost_str = f"{sign}${abs_cost / 1e6:.1f} million USD"
    else:
        cost_str = f"{sign}${abs_cost:,.0f} USD"
    cost_label = "social cost savings per year" if dem_adjusted >= 0 else "social cost increase per year"

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div class="equiv-card {card_class}">'
            f'<div class="equiv-icon">&#128663;</div>'
            f'<div class="equiv-number">{sign}{abs_cars:,.0f}</div>'
            f'<div class="equiv-label">{cars_label}</div>'
            f'</div>', unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div class="equiv-card {card_class}">'
            f'<div class="equiv-icon">&#127807;</div>'
            f'<div class="equiv-number">{trees_str}</div>'
            f'<div class="equiv-label">{trees_label}</div>'
            f'</div>', unsafe_allow_html=True)
    with c3:
        st.markdown(
            f'<div class="equiv-card {card_class}">'
            f'<div class="equiv-icon">&#128176;</div>'
            f'<div class="equiv-number">{cost_str}</div>'
            f'<div class="equiv-label">{cost_label}</div>'
            f'</div>', unsafe_allow_html=True)

# ===============================================================================
# FOOTER
# ===============================================================================

st.markdown('<hr class="styled-divider">', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">'
    'Model: Weighted Least Squares + Country Fixed Effects + Size-Band Interactions &nbsp;&#183;&nbsp; '
    'R&#178; = 0.7848 &nbsp;&#183;&nbsp; Bias = +2.28% &nbsp;&#183;&nbsp; 8,396 cities across 99 countries<br>'
    'Data: <a href="https://climatetrace.org/">Climate TRACE</a> &#183; '
    '<a href="https://ember-energy.org/">Ember</a> &#183; '
    '<a href="https://www.iea.org/">IEA</a> &#183; '
    '<a href="https://www.epa.gov/">EPA</a>'
    '</div>',
    unsafe_allow_html=True)
