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
| **DLI Support** | {dli_text} |

### Design Scores

{score_block}

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
  # PDLI grant = financial support (24 projects); "Listed" = on the Chips-DLI portal beneficiary list without a grant
  dli_text <- if (is.na(f$dli_support)) "—" else if (f$dli_support == "PDLI grant") paste0("PDLI grant", if (!is.na(f$dli_product)) paste0(" — ", f$dli_product) else "") else "Listed as DLI beneficiary on chips-dli.gov.in (no PDLI grant)"

  # Two scores (see design.qmd): Ambition = what the firm attempts; Progress = what it has delivered.
  # Each row shows the bar, the score and the two dimensions it averages.
  score_row <- function(label, score, parts) {
    paste0("| **", label, "** | ", design_score_bar_html(score, label), " ", score, "/5 | ", parts, " |")
  }
  if (is.na(f$ambition) || is.na(f$progress)) {
    score_block <- "*Not yet scored.*"
  } else if (isTRUE(f$is_gcc)) {
    score_block <- paste(
      "| | Score | Made up of |", "|---|---|---|",
      score_row("Ambition", f$ambition, paste0("Domain difficulty ", f$domain_difficulty, ", strategic depth ", f$strategic_depth)),
      score_row("Progress", f$progress, paste0("Design completeness ", f$design_completeness, ", India scale ", f$india_scale)),
      sep = "\n")
  } else {
    score_block <- paste(
      "| | Score | Made up of |", "|---|---|---|",
      score_row("Ambition", f$ambition, paste0("Domain difficulty ", f$domain_difficulty, ", IP ownership ", f$ip_ownership)),
      score_row("Progress", f$progress, paste0("Design completeness ", f$design_completeness, ", market readiness ", f$market_readiness)),
      sep = "\n")
  }

  significance <- if (nchar(f$significance) > 0) f$significance else "Details coming soon — this firm is tracked via the DLI beneficiary list but has not yet been independently researched."
  what_it_designs <- if (nchar(f$what_it_designs) > 0) f$what_it_designs else "*Details coming soon.*"

  if (!is.null(this_firm$sources) && length(this_firm$sources) > 0) {
    source_lines <- sapply(this_firm$sources, function(s) {
      # Omit the date suffix when a source has no known publication date
      if (is.null(s$date)) return(paste0("- [", s$title, "](", s$url, ")"))
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
    score_block = score_block,
    significance = significance,
    what_it_designs = what_it_designs,
    source_links = source_links
  )

  writeLines(page_content, paste0("design-firms/", f$id, ".qmd"))
}

cat("Successfully generated", nrow(firms), "design firm pages.\n")
