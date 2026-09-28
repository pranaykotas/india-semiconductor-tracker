# R script to generate individual design-firm profile pages from YAML data
# Run: Rscript R/generate_design_pages.R
source("R/helpers.R")
library(yaml)
library(glue)

firms <- load_design_firms("data/design.yml")
raw_firms <- yaml::read_yaml("data/design.yml")$design_firms

if (!dir.exists("design-firms")) dir.create("design-firms")

template <- '---
title: "{name}"
subtitle: "{category}{parent_suffix}"
date: last-modified
---

::: {{.callout-tip}}
## Why This Matters
{significance}
:::

## What does this firm design?

{what_it_designs}

## Key Facts

| | |
|---|---|
| **Category** | {category} |
| **Parent Company** | {parent_text} |
| **Founded** | {founded_text} |
| **India Headcount** | {headcount_text} |
| **Locations** | {cities} |
| **Product Focus** | {product_focus} |
| **Application Domains** | {application_domains} |
| **Design Scope** | {design_scope} |
| **Node Sophistication** | {node_text} |
| **DLI Beneficiary** | {dli_text} |

### Design Score
{score_bar} **{composite_text}**

## Sources

{source_links}

---

::: {{.callout-note}}
## Have an update about this firm?
If you have new information, a correction, or a source to add, please [submit it via our form](https://forms.gle/FDESu4jRksmr7FTk7) or [open a GitHub Issue](https://github.com/pranaykotas/india-semiconductor-tracker/issues/new/choose).
:::

<a href="../design.html" class="btn btn-primary">Back to Design Tracker</a>
'

for (i in 1:nrow(firms)) {
  f <- firms[i, ]
  this_firm <- Filter(function(x) x$id == f$id, raw_firms)[[1]]

  parent_text <- if (!is.na(f$parent_company)) paste0(f$parent_company, " (", f$parent_hq, ")") else "None (Indian-origin)"
  parent_suffix <- if (!is.na(f$parent_company)) paste0(" | ", f$parent_company) else ""
  founded_text <- if (!is.na(f$founded)) as.character(f$founded) else "Unknown"
  headcount_text <- if (!is.na(f$india_headcount)) paste0("~", format(f$india_headcount, big.mark = ",")) else "Not publicly disclosed"
  cities_text <- if (nchar(f$cities) > 0) f$cities else "Not yet documented"
  product_focus_text <- if (nchar(f$product_focus) > 0) f$product_focus else "*Details coming soon.*"
  domains_text <- if (nchar(f$application_domains) > 0) f$application_domains else "Not yet documented"
  design_scope_text <- if (nchar(f$design_scope) > 0) f$design_scope else "Not yet documented"
  node_text <- if (nchar(f$node_sophistication) > 0) f$node_sophistication else "Not applicable / not disclosed"
  dli_text <- if (isTRUE(f$dli_beneficiary)) "Yes" else "No"

  composite_text <- if (!is.na(f$design_composite)) paste0(f$design_composite, "/5") else "Not yet scored"
  score_bar <- design_score_bar_html(f$design_composite)

  significance <- if (nchar(f$significance) > 0) f$significance else "Details coming soon — this firm is tracked via the DLI beneficiary list but has not yet been independently researched."
  what_it_designs <- if (nchar(f$what_it_designs) > 0) f$what_it_designs else "*Details coming soon.*"

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
    founded_text = founded_text,
    headcount_text = headcount_text,
    cities = cities_text,
    product_focus = product_focus_text,
    application_domains = domains_text,
    design_scope = design_scope_text,
    node_text = node_text,
    dli_text = dli_text,
    score_bar = score_bar,
    composite_text = composite_text,
    significance = significance,
    what_it_designs = what_it_designs,
    source_links = source_links
  )

  writeLines(page_content, paste0("design-firms/", f$id, ".qmd"))
}

cat("Successfully generated", nrow(firms), "design firm pages.\n")
