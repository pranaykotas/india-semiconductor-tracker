# Contributing to the India Semiconductor Tracker

We welcome contributions from researchers, industry experts, and the public to keep this tracker accurate and up-to-date.

## How to Contribute

### 1. Update Facility Data
If you have new information about a project (e.g., a new expected completion date or an updated investment figure):
- Edit `data/facilities.yml`.
- Ensure you include an official source (like a PIB link) in the `sources` list for the facility.
- Create a Pull Request with a clear description of the change.

### 2. Add a New Facility
To add a new facility:
- Append a new entry to `data/facilities.yml` following the existing schema.
- Run `Rscript R/generate_facility_pages.R` to create its profile page.
- Submit a Pull Request.

### 3. Report a Bug or Error
If you spot an error on the site or a bug in a visualization:
- [Open a GitHub Issue](https://github.com/pranaykotas/india-semiconductor-tracker/issues/new) with details and supporting evidence.

## Data Schema
- **Technical Complexity:** 1 (Low) to 5 (High). 
- **Original Completion Date:** The first officially announced completion target.
- **Slippage:** Calculated automatically as months beyond the original target.

Thank you for helping us track India's semiconductor journey!
