# R script to generate individual facility profile pages from YAML data
# Run: Rscript R/generate_facility_pages.R
source("R/helpers.R")
library(yaml)
library(glue)

facilities <- load_facilities("data/facilities.yml")
raw_facs <- yaml::read_yaml("data/facilities.yml")$facilities

# Ensure facilities directory exists
if (!dir.exists("facilities")) dir.create("facilities")

# Template for the facility page — narrative-first design
template <- '---
title: "{name}"
subtitle: "{company} | {type}"
date: last-modified
---

::: {{.callout-tip}}
## Why This Matters
{significance}
:::

## What does this facility make?

{what_it_makes}

## Why does it matter?

{why_it_matters}

## Key Facts

::: {{.grid}}
::: {{.g-col-8}}

| | |
|---|---|
| **Company** | {company} |
| **Partners** | {partners} |
| **Type** | {type} |
| **Capability** | {capability} |
| **Status** | {status} |
| **Investment** | {investment_text} |
| **Location** | {city}, {state} |
| **Category** | {category} |

:::
::: {{.g-col-4}}

### Technical Complexity
{complexity_bar}
**{complexity_score}/5**

Benchmarked against a 3nm fab (5/5).

### Timeliness
{slippage_badge}

{completion_source_text}
:::
:::

## Project Timeline

{milestones_section}

## Sources

{source_links}

---

::: {{.callout-note}}
## Have an update about this project?
If you have new information, a correction, or a source to add, please [submit it via our form](https://forms.gle/FDESu4jRksmr7FTk7) or [open a GitHub Issue](https://github.com/pranaykotas/india-semiconductor-tracker/issues/new/choose).
:::

<a href="../index.html" class="btn btn-primary">Back to Map</a>
'

# Generate a page for each facility
for (i in 1:nrow(facilities)) {
  f <- facilities[i, ]

  # Find raw YAML entry for this facility (to get milestones and sources)
  this_fac <- Filter(function(x) x$id == f$id, raw_facs)[[1]]

  # Partners text
  partners_text <- if (f$partners != "" && !is.na(f$partners)) f$partners else "None"

  # Investment text
  investment_text <- if (f$investment_inr > 0) {
    paste0("\u20b9", format(f$investment_inr, big.mark = ","), " crore")
  } else {
    "Strategic / Government funded"
  }

  # Milestones section
  if (!is.null(this_fac$milestones) && length(this_fac$milestones) > 0) {
    milestone_lines <- sapply(this_fac$milestones, function(m) {
      date_str <- format(as.Date(m$date), "%d %b %Y")
      paste0("- **", date_str, "** — ", m$event)
    })
    milestones_section <- paste(milestone_lines, collapse = "\n")
  } else {
    milestones_section <- "*No milestones recorded yet.*"
  }

  # Source links
  if (!is.null(this_fac$sources) && length(this_fac$sources) > 0) {
    source_lines <- sapply(this_fac$sources, function(s) {
      date_str <- format(as.Date(s$date), "%d %b %Y")
      paste0("- [", s$title, "](", s$url, ") (", date_str, ")")
    })
    source_links <- paste(source_lines, collapse = "\n")
  } else {
    source_links <- "*No official sources linked yet. [Help us add one.](https://github.com/pranaykotas/india-semiconductor-tracker/issues/new/choose)*"
  }

  # Completion source text
  if (nchar(f$completion_source_url) > 0) {
    orig_date_str <- if (!is.na(f$date_original_expect)) format(f$date_original_expect, "%b %Y") else "TBD"
    completion_source_text <- paste0(
      "Original target: ", orig_date_str,
      " ([source](", f$completion_source_url, "))"
    )
  } else {
    completion_source_text <- ""
  }

  # Narrative fields
  significance <- if (nchar(f$significance) > 0) f$significance else "Details coming soon."
  what_it_makes <- if (nchar(f$what_it_makes) > 0) f$what_it_makes else "*Details coming soon.*"
  why_it_matters <- if (nchar(f$why_it_matters) > 0) f$why_it_matters else "*Details coming soon.*"

  page_content <- glue(template,
    name = f$name,
    company = f$company,
    type = f$type,
    category = f$category,
    city = f$city,
    state = f$state,
    partners = partners_text,
    capability = f$capability,
    status = f$status,
    investment_text = investment_text,
    complexity_bar = complexity_bar_html(f$complexity_score),
    complexity_score = f$complexity_score,
    slippage_badge = slippage_badge_html(f$slippage_months),
    significance = significance,
    what_it_makes = what_it_makes,
    why_it_matters = why_it_matters,
    milestones_section = milestones_section,
    source_links = source_links,
    completion_source_text = completion_source_text
  )

  writeLines(page_content, paste0("facilities/", f$id, ".qmd"))
}

cat("Successfully generated", nrow(facilities), "facility pages.\n")
