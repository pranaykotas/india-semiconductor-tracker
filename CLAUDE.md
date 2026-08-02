# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

**India Semiconductor Manufacturing Tracker** — an interactive Quarto website that tracks all announced semiconductor manufacturing facilities in India (fabs, ATMP, OSAT) under the India Semiconductor Mission and related initiatives.

Maintained by Pranay Kotasthane at the Takshashila Institution.

## Build Commands

```bash
quarto render          # build site into _site/
quarto preview         # live preview with auto-reload
```

**R packages required:** `yaml`, `dplyr`, `tidyr`, `leaflet`, `DT`, `ggplot2`, `scales`, `glue`, `htmltools`

Install all at once:
```r
install.packages(c("yaml", "dplyr", "tidyr", "leaflet", "DT", "ggplot2", "scales", "glue", "htmltools"))
```

## Architecture

- **Quarto website** configured in `_quarto.yml`, output to `_site/`
- **Theme:** Cosmo + `styles.scss` (Takshashila brand tokens synced with `takshashila-base-20260723.css`: Llama maroon `#620d3c`, Marigold gold `#f1a222`, Inter for all text, Roboto Mono for meta/eyebrow)
- **All facility data** lives in a single file: `data/facilities.yml`
- **Design firm data** in `data/design.yml` — Indian fabless firms and GCC design centres (separate schema from facilities)
- **R helper functions** in `R/helpers.R` — loads YAML, computes complexity scores, generates HTML for popups/badges
- **6 main pages + 13 facility profiles:** Map & Overview (`index.qmd`), Timeline (`timeline.qmd`), Technology Nodes (`nodes.qmd`), Chip Design (`design.qmd`), Policy & Budget (`budget.qmd`), About (`about.qmd`)
- **Individual facility pages** in `facilities/` — generated from YAML by `Rscript R/generate_facility_pages.R`

### Data Flow

```
data/facilities.yml  →  R/helpers.R (load_facilities())       →  .qmd pages (map, table, charts)
data/design.yml      →  R/helpers.R (load_design_firms())     →  design.qmd (map, tables, charts)
data/budget.yml      →  R/helpers.R (load_budget())           →  budget.qmd (budget charts, analysis)
```

Routine updates only require editing `data/facilities.yml`, `data/design.yml`, or `data/budget.yml`. No R code changes needed.

### Facility Data Schema

Each facility in `data/facilities.yml` has:
- `id`, `name`, `company`, `partners[]`
- `location` (city, state, lat, lon)
- `type`: `Fab` | `Assembly & Packaging` | `Compound Semiconductor` | `Research Fab`
- `category`: `Commercial (ISM Approved)` | `Research & Strategic`
- `investment` (total_inr in crore)
- `status`: `Announced` | `Approved` | `Under Construction` | `Operational` | `On Hold` | `Cancelled`
- `narrative` (significance, what_it_makes, why_it_matters)
- `milestones[]` (date, event)
- `complexity` (technology_difficulty, foreign_dependence, capital_intensity — each 1–5; composite = tech*0.55 + capital*0.45)
- `dates` (announced, approved, construction_start, original_expected_completion, date_completion)
- `sources[]` (url, title, date)

### Adding a New Facility

Copy an existing entry in `data/facilities.yml`, fill in the fields, run `quarto preview` to verify.

### Community Updates

External contributors submit updates via GitHub Issues using the template at `.github/ISSUE_TEMPLATE/facility-update.yml`. Review and merge manually into `facilities.yml`.

### Key R Functions (`R/helpers.R`)

- `load_facilities(path)` — reads YAML → tibble, computes composite complexity score
- `make_popup(row)` — HTML popup for leaflet markers
- `status_color(status)` / `type_color(type)` — colour mappings
- `status_badge_html(status)` — renders coloured status badge
- `complexity_bar_html(score)` — renders visual complexity indicator
- `load_design_firms(path)` — reads design YAML → tibble (one row per firm, primary location)
- `load_design_locations(path)` — reads design YAML → tibble (one row per location, for mapping)
- `design_category_color(category)` / `design_category_badge(category)` — colour/badge for design firm categories

### Design Firm Data Schema

Each firm in `data/design.yml` has:
- `id`, `name`, `category` (`Indian Fabless` | `DLI Beneficiary` | `GCC Design Centre` | `EDA & IP Provider`)
- `dli_beneficiary` (boolean)
- `parent_company`, `parent_hq` (for GCCs; null for Indian firms)
- `founded` (year of India establishment)
- `india_headcount` (approximate, when known)
- `locations[]` (city, state, lat, lon — supports multiple)
- `product_focus`, `application_domains[]`, `design_scope`, `node_sophistication`
- `dli` (approved, product, grant_inr — for DLI beneficiaries)
- `narrative` (significance, what_it_designs)
- `sources[]` (url, title, date)
