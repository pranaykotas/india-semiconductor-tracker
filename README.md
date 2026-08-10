# India Semiconductor Tracker

An interactive, open-source tracker for India's semiconductor sector — manufacturing facilities (fabs, ATMP/OSAT), chip design firms, and policy developments.

**Live site:** [fabs.pranaykotas.com](https://fabs.pranaykotas.com)

Maintained by [Pranay Kotasthane](https://pranaykotas.com) at the [Takshashila Institution](https://takshashila.org.in). For broader analysis, see the [Siliconpolitik Project](https://takshashila.org.in/pages/research-areas/focus-areas/siliconpolitik.html).

---

## What It Tracks

- **16 facilities** across commercial ISM-approved, private non-ISM, and research & strategic categories
- **Status** (Announced → Approved → Under Construction → Operational)
- **Slippage** — delay in months from original announced completion date
- **Technical Complexity** — weighted score benchmarked against a 3nm fab (5/5)
- **Investment** and **milestones** with source links for every entry

---

## How to Contribute

The tracker depends on community contributions to stay accurate. There are two ways:

### Option 1 — Quick update (no account needed)

**[Submit via Google Form](https://forms.gle/FDESu4jRksmr7FTk7)** — takes 2 minutes. Use this for:
- Status changes (construction started, facility inaugurated, production begun)
- Corrections to investment figures, dates, or capability descriptions
- New facility announcements

### Option 2 — GitHub Issue (for detailed contributions)

**[Open an Issue](https://github.com/pranaykotas/india-semiconductor-tracker/issues/new/choose)** using the facility update template. Include:
- Which facility (or details of a new one)
- What changed
- A source URL — PIB press release, company announcement, or credible news report

All submissions are reviewed before being merged into `data/facilities.yml`.

---

## Repository Structure

```
data/
  facilities.yml      # Single source of truth — all facility data
  budget.yml          # ISM scheme budget allocations
  shp/                # GeoJSON boundary files for India map

R/
  helpers.R           # Data loading, complexity/slippage calculations, HTML rendering
  generate_facility_pages.R  # Generates individual facility .qmd pages from YAML

facilities/           # Auto-generated facility profile pages (do not edit directly)

*.qmd                 # Main site pages: index, timeline, nodes, budget, about
styles.scss           # Custom CSS
_quarto.yml           # Site configuration
```

### Data flow

```
data/facilities.yml  →  R/helpers.R  →  .qmd pages (map, table, charts)
                     →  R/generate_facility_pages.R  →  facilities/*.qmd
```

**Routine updates only require editing `data/facilities.yml`.** No R code changes needed.

---

## Adding or Updating a Facility

All facility data lives in `data/facilities.yml`. Each entry follows this structure:

```yaml
- id: facility-id
  name: "Full Facility Name"
  company: "Company Name"
  category: "Commercial (ISM Approved)"   # or "Research & Strategic" / "OSAT (Non-ISM)"
  partners: ["Partner Name, Country"]
  location:
    city: "City"
    state: "State"
    lat: 22.123
    lon: 72.456
  type: "Assembly & Packaging"            # Fab / Assembly & Packaging / Compound Semiconductor
  capability: "Brief capability description"
  investment:
    total_inr: 3307                       # in crore
  status: "Under Construction"            # Announced / Approved / Under Construction / Operational
  status_detail: "Optional tooltip text"  # shown on hover in the overview table
  delay_confirmed: true                   # set if known to be delayed before target date passes
  narrative:
    significance: "One sentence — why should a non-expert care?"
    what_it_makes: "What does this facility produce?"
    why_it_matters: "Broader strategic significance"
  milestones:
    - date: "2024-03-13"
      event: "Description of milestone"
  complexity:
    technology_difficulty: 2              # 1–5, benchmarked against 3nm fab = 5
    foreign_dependence: 3
    capital_intensity: 3
  dates:
    announced: "2024-02-29"
    approved: "2024-02-29"
    construction_start: "2024-03-13"
    original_expected_completion: "2026-12-31"
    date_completion: "2027-03-31"         # actual or revised expected date
  sources:
    - url: "https://pib.gov.in/..."
      title: "Source title"
      date: "2024-03-13"
```

After editing the YAML, run:

```bash
Rscript R/generate_facility_pages.R   # regenerate facility pages
quarto render                          # build the site
```

The site also rebuilds automatically every Monday via GitHub Actions.

---

## Local Development

**Requirements:** R, Quarto, and the following R packages:

```r
install.packages(c(
  "yaml", "dplyr", "tidyr", "leaflet", "DT",
  "ggplot2", "scales", "glue", "htmltools",
  "sf", "rnaturalearth", "ragg"
))
```

**Build and preview:**

```bash
quarto preview    # live preview with auto-reload
quarto render     # full build to _site/
```

---

## Licence

Data and visualisations are available under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). You are free to use, share, and adapt with attribution.
