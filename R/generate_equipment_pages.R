# R script to generate individual equipment/materials firm profile pages from YAML data
# Run: Rscript R/generate_equipment_pages.R
source("R/helpers.R")
library(yaml)
library(glue)

equip <- load_equipment("data/equipment_materials.yml")
raw_firms <- yaml::read_yaml("data/equipment_materials.yml")$equipment_materials

if (!dir.exists("equipment-firms")) dir.create("equipment-firms")

template <- '---
title: "{name}"
subtitle: "{category}{parent_suffix}"
date: last-modified
---

::: {{.callout-tip}}
## Why This Matters
{significance}
:::

## What does this facility supply?

{what_it_supplies}

## Key Facts

| | |
|---|---|
| **Category** | {category} |
| **Parent Company** | {parent_text} |
| **Location** | {city}, {state} |
| **Investment** | {investment_text} |
| **Status** | {status} |
| **Supplies** | {supplies_text} |

## Project Timeline

{milestones_section}

## Sources

{source_links}

---

::: {{.callout-note}}
## Have an update about this facility?
If you have new information, a correction, or a source to add, please [submit it via our form](https://forms.gle/FDESu4jRksmr7FTk7) or [open a GitHub Issue](https://github.com/pranaykotas/india-semiconductor-tracker/issues/new/choose).
:::

<a href="../equipment.html" class="btn btn-primary">Back to Equipment & Materials</a>
'

for (i in 1:nrow(equip)) {
  f <- equip[i, ]
  this_firm <- Filter(function(x) x$id == f$id, raw_firms)[[1]]

  parent_text <- if (!is.na(f$parent_company)) paste0(f$parent_company, " (", f$parent_hq, ")") else "None (Indian-origin)"
  parent_suffix <- if (!is.na(f$parent_company)) paste0(" | ", f$parent_company) else ""
  investment_text <- format_equipment_investment(f$investment_inr, f$investment_usd_m)
  supplies_text <- if (nchar(f$supplies_to) > 0) f$supplies_to else "General / not tied to one facility"
  significance <- if (nchar(f$significance) > 0) f$significance else "Details coming soon."
  what_it_supplies <- if (nchar(f$what_it_supplies) > 0) f$what_it_supplies else "*Details coming soon.*"

  if (!is.null(this_firm$milestones) && length(this_firm$milestones) > 0) {
    milestone_lines <- sapply(this_firm$milestones, function(m) {
      date_str <- tryCatch(format(as.Date(m$date), "%d %b %Y"), error = function(e) m$date)
      paste0("- **", date_str, "** — ", m$event)
    })
    milestones_section <- paste(milestone_lines, collapse = "\n")
  } else {
    milestones_section <- "*No milestones recorded yet.*"
  }

  if (!is.null(this_firm$sources) && length(this_firm$sources) > 0) {
    source_lines <- sapply(this_firm$sources, function(s) {
      date_str <- tryCatch(format(as.Date(s$date), "%d %b %Y"), error = function(e) s$date)
      paste0("- [", s$title, "](", s$url, ") (", date_str, ")")
    })
    source_links <- paste(source_lines, collapse = "\n")
  } else {
    source_links <- "*No sources linked yet. [Help us add one.](https://github.com/pranaykotas/india-semiconductor-tracker/issues/new/choose)*"
  }

  page_content <- glue(template,
    name = f$name,
    category = f$category,
    parent_suffix = parent_suffix,
    parent_text = parent_text,
    city = f$city,
    state = f$state,
    investment_text = investment_text,
    status = f$status,
    supplies_text = supplies_text,
    significance = significance,
    what_it_supplies = what_it_supplies,
    milestones_section = milestones_section,
    source_links = source_links
  )

  writeLines(page_content, paste0("equipment-firms/", f$id, ".qmd"))
}

cat("Successfully generated", nrow(equip), "equipment/materials firm pages.\n")
