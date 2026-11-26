# helpers.R — Shared functions for the India Semiconductor Tracker
# All data loading, transformation, and HTML rendering lives here.

library(yaml)
library(dplyr)
library(tidyr)
library(glue)
library(htmltools)

# Helper for null-coalescing
`%||%` <- function(a, b) if (!is.null(a)) a else b

# ---- Load and flatten facilities YAML into a tibble ----
load_facilities <- function(path = "data/facilities.yml") {
  raw <- yaml::read_yaml(path)

  rows <- lapply(raw$facilities, function(f) {
    tibble(
      id                    = f$id,
      name                  = f$name,
      company               = f$company,
      category              = f$category %||% "Commercial (ISM Approved)",
      partners              = paste(f$partners, collapse = ", "),
      city                  = f$location$city,
      state                 = f$location$state,
      lat                   = f$location$lat,
      lon                   = f$location$lon,
      type                  = f$type,
      capability            = f$capability %||% "Not disclosed",
      technology            = f$technology %||% "",
      investment_inr        = if (!is.null(f$investment) && !is.null(f$investment$total_inr)) f$investment$total_inr else NA_real_,
      status                = f$status,
      status_detail         = f$status_detail %||% "",
      complexity_tech       = f$complexity$technology_difficulty %||% 1,
      complexity_foreign    = f$complexity$foreign_dependence %||% 1,
      complexity_capital    = f$complexity$capital_intensity %||% 1,
      date_announced        = as.Date(f$dates$announced %||% NA),
      date_approved         = as.Date(f$dates$approved %||% NA),
      date_construction     = as.Date(f$dates$construction_start %||% NA),
      date_completion       = as.Date(f$dates$date_completion %||% NA),
      date_original_expect  = as.Date(f$dates$original_expected_completion %||% NA),
      delay_confirmed       = f$delay_confirmed %||% FALSE,
      notes                 = f$notes %||% "",
      significance          = f$narrative$significance %||% "",
      what_it_makes         = f$narrative$what_it_makes %||% "",
      why_it_matters        = f$narrative$why_it_matters %||% "",
      completion_source_url   = f$dates$original_completion_source$url %||% "",
      completion_source_title = f$dates$original_completion_source$title %||% ""
    )
  })

  df <- bind_rows(rows)

  # Apply jitter to coordinates for specific clusters
  # Increase jitter to ~1.5km (0.015 degrees) to ensure visibility
  set.seed(42)
  df <- df %>%
    mutate(
      lat = lat + runif(n(), -0.015, 0.015),
      lon = lon + runif(n(), -0.015, 0.015)
    )

  # Composite technical complexity score:
  # 55% Technology Difficulty + 45% Capital Intensity
  df <- df %>%
    mutate(
      complexity_score = round((complexity_tech * 0.55) + (complexity_capital * 0.45), 1)
    )

  # Timeliness Score: Slippage in months
  today <- Sys.Date()
  df <- df %>%
    mutate(
      slippage_months = case_when(
        status == "Operational" & !is.na(date_completion) & !is.na(date_original_expect) ~
          as.numeric(date_completion - date_original_expect) / 30.44,
        status == "Under Construction" & !is.na(date_original_expect) & today > date_original_expect ~
          as.numeric(today - date_original_expect) / 30.44,
        TRUE ~ 0
      ),
      slippage_months = round(pmax(0, slippage_months), 1),
      # -1 is a sentinel: delay confirmed but no revised date yet
      slippage_months = if_else(delay_confirmed & slippage_months == 0, -1, slippage_months)
    )

  df
}

# ---- Format investment for UI surfaces ----
format_investment <- function(investment_inr, category = "Commercial (ISM Approved)", short = FALSE) {
  if (category == "Research & Strategic") {
    return(if (short) "Strategic" else "Strategic / Government funded")
  }

  if (is.na(investment_inr) || investment_inr <= 0) {
    return("Not disclosed")
  }

  suffix <- if (short) " cr" else " crore"
  paste0("\u20b9", format(investment_inr, big.mark = ","), suffix)
}

# ---- Map status to display colour ----
status_color <- function(status) {
  switch(status,
    "Operational"        = "#2f6b4a",
    "Under Construction" = "#1565C0",
    "Approved"           = "#f1a222",
    "Announced"          = "#8C8480",
    "On Hold"            = "#a3282d",
    "Cancelled"          = "#a3282d",
    "#8C8480"
  )
}

# ---- Map facility type to marker colour ----
type_color <- function(type, category = "Commercial (ISM Approved)") {
  if (category == "Research & Strategic") return("#455A64")
  if (category == "OSAT (Non-ISM)") return("#00796B")
  switch(type,
    "Fab"                    = "#620d3c",
    "Assembly & Packaging"   = "#2f6b6b",
    "Compound Semiconductor" = "#6A1B9A",
    "Research Fab"           = "#455A64",
    "#757575"
  )
}

# ---- Render an HTML status badge ----
status_badge_html <- function(status, detail = "") {
  css_class <- switch(status,
    "Operational"        = "badge-operational",
    "Under Construction" = "badge-construction",
    "Approved"           = "badge-approved",
    "MoU Signed"         = "badge-approved",
    "Announced"          = "badge-announced",
    "On Hold"            = "badge-onhold",
    "Cancelled"          = "badge-cancelled",
    "badge-announced"
  )
  title_attr <- if (nchar(detail) > 0) paste0(' title="', detail, '"') else ""
  glue('<span class="status-badge {css_class}"{title_attr}>{status}</span>')
}

# ---- Render a complexity bar ----
complexity_bar_html <- function(score) {
  filled <- round(score)
  segments <- vapply(1:5, function(i) {
    cls <- if (i <= filled) "complexity-segment filled" else "complexity-segment"
    glue('<span class="{cls}"></span>')
  }, character(1))
  glue('<span class="complexity-bar" title="Technical Complexity: {score}/5">{paste(segments, collapse = "")}</span>')
}

# ---- Convert a date to Indian fiscal year label (e.g. "FY2026-27") ----
fy_label <- function(d) {
  if (is.na(d)) return(NA_character_)
  yr <- as.integer(format(d, "%Y"))
  mo <- as.integer(format(d, "%m"))
  if (mo >= 4) paste0("FY", yr, "-", formatC((yr + 1L) %% 100L, width = 2, flag = "0"))
  else         paste0("FY", yr - 1L, "-", formatC(yr %% 100L, width = 2, flag = "0"))
}

# ---- Render a slippage badge ----
# revised_label: e.g. "FY2026-27" when a new completion date is known; NA otherwise
slippage_badge_html <- function(months, revised_label = NA) {
  if (months < 0) return('<span class="slippage-badge badge-major-delay">Delay (TBD)</span>')
  if (months == 0) return('<span class="slippage-badge badge-on-track">On track</span>')
  css <- if (months < 6) "badge-minor-delay" else "badge-major-delay"
  if (!is.na(revised_label)) {
    glue('<span class="slippage-badge {css}">{months}m slip → {revised_label}</span>')
  } else {
    glue('<span class="slippage-badge {css}">{months}m overdue ↗</span>')
  }
}

# ---- Render a progress bar ----
progress_bar_html <- function(status, date_construction, date_completion) {
  today <- Sys.Date()
  if (status == "Operational") {
    pct <- 100
    label <- "Complete"
    bar_color <- "#2f6b4a"
  } else if (!is.na(date_construction) && !is.na(date_completion)) {
    total_days <- as.numeric(date_completion - date_construction)
    elapsed <- as.numeric(today - date_construction)
    pct <- min(100, max(0, round(elapsed / total_days * 100)))
    remaining_months <- max(0, round(as.numeric(date_completion - today) / 30.44))
    label <- paste0(pct, "% (~", remaining_months, "m left)")
    bar_color <- "#1565C0"
  } else {
    pct <- 0; label <- "TBD"; bar_color <- "#8C8480"
  }
  glue('<div class="progress-container" title="{label}"><div class="progress-bar" style="background:{bar_color};width:{pct}%"></div><span class="progress-label">{label}</span></div>')
}

# ---- Build leaflet popup HTML ----
make_popup <- function(row) {
  sig_html <- if (nchar(row$significance) > 0) {
    glue('<div class="popup-significance">{row$significance}</div>')
  } else ""

  inv_html <- glue('<div class="popup-row"><span class="popup-label">Investment:</span> {format_investment(row$investment_inr, row$category)}</div>')

  glue('
    <div class="facility-popup">
      <h4>{row$name}</h4>
      {sig_html}
      <div class="popup-row"><span class="popup-label">Company:</span> {row$company}</div>
      <div class="popup-row"><span class="popup-label">Capability:</span> {row$capability}</div>
      {inv_html}
      <div class="popup-row"><span class="popup-label">Status:</span> {status_badge_html(row$status)}</div>
      <div class="popup-row"><span class="popup-label">Complexity:</span> {complexity_bar_html(row$complexity_score)}</div>
      <div class="popup-row" style="margin-top:6px;"><a href="facilities/{row$id}.html" class="btn-detail">Full Profile →</a></div>
    </div>
  ')
}

# ---- Build hover label ----
make_label <- function(row) {
  glue('<strong>{row$name}</strong><br/>{row$company} | {row$capability}')
}

# ---- Load and flatten design firms YAML into a tibble ----
load_design_firms <- function(path = "data/design.yml") {
  raw <- yaml::read_yaml(path)

  rows <- lapply(raw$design_firms, function(f) {
    locs <- f$locations
    has_locs <- length(locs) > 0
    primary <- if (has_locs) locs[[1]] else list(lat = NA_real_, lon = NA_real_)
    cities <- if (has_locs) paste(sapply(locs, function(l) l$city), collapse = ", ") else ""
    states <- if (has_locs) paste(unique(sapply(locs, function(l) l$state)), collapse = ", ") else ""

    tibble(
      id                = f$id,
      name              = f$name,
      category          = f$category,
      # DLI tier: "PDLI grant" | "Listed as DLI beneficiary" | NA (see design.qmd)
      dli_support       = f$dli_support %||% NA_character_,
      # C2S (Chips to Startup) R&D project with an academic partner, if any
      c2s_partner       = f$c2s$partner %||% NA_character_,
      c2s_project       = f$c2s$project %||% NA_character_,
      parent_company    = f$parent_company %||% NA_character_,
      parent_hq         = f$parent_hq %||% NA_character_,
      founded           = f$founded %||% NA_integer_,
      india_headcount   = f$india_headcount %||% NA_integer_,
      product_focus     = f$product_focus %||% "",
      application_domains = paste(f$application_domains, collapse = ", "),
      design_scope      = f$design_scope %||% "",
      node_sophistication = f$node_sophistication %||% "",
      dli_product       = f$dli$product %||% NA_character_,
      dli_grant_inr     = f$dli$grant_inr %||% NA_real_,
      significance      = f$narrative$significance %||% "",
      what_it_designs   = f$narrative$what_it_designs %||% "",
      primary_lat       = primary$lat,
      primary_lon       = primary$lon,
      cities            = cities,
      states            = states,
      n_locations       = length(locs),
      # Design score dimensions, read by name (each 1–5; NA if not scored).
      # Indian firms use ip_ownership + market_readiness; GCCs use strategic_depth + india_scale.
      ip_ownership        = f$design_score$ip_ownership        %||% NA_real_,
      strategic_depth     = f$design_score$strategic_depth     %||% NA_real_,
      domain_difficulty   = f$design_score$domain_difficulty   %||% NA_real_,
      design_completeness = f$design_score$design_completeness %||% NA_real_,
      market_readiness    = f$design_score$market_readiness    %||% NA_real_,
      india_scale         = f$design_score$india_scale         %||% NA_real_
    )
  })

  df <- bind_rows(rows)

  # Two scores instead of one composite, so ambition and delivery are not averaged away:
  #   Ambition = what the firm attempts: domain difficulty + IP ownership
  #              (GCCs: domain difficulty + strategic depth of the India centre)
  #   Progress = what it has delivered: design completeness + market readiness
  #              (GCCs: design completeness + India scale)
  df <- df %>%
    mutate(
      is_gcc = category == "GCC Design Centre",
      ambition = round(ifelse(is_gcc, (domain_difficulty + strategic_depth) / 2,
                                      (domain_difficulty + ip_ownership) / 2), 1),
      progress = round(ifelse(is_gcc, (design_completeness + india_scale) / 2,
                                      (design_completeness + market_readiness) / 2), 1)
    )

  set.seed(43)
  df <- df %>%
    mutate(
      primary_lat = primary_lat + runif(n(), -0.015, 0.015),
      primary_lon = primary_lon + runif(n(), -0.015, 0.015)
    )

  df
}

# ---- Load all design firm locations (one row per location) for mapping ----
load_design_locations <- function(path = "data/design.yml") {
  raw <- yaml::read_yaml(path)

  rows <- lapply(raw$design_firms, function(f) {
    if (length(f$locations) == 0) return(list())
    lapply(f$locations, function(loc) {
      tibble(
        id       = f$id,
        name     = f$name,
        category = f$category,
        city     = loc$city,
        state    = loc$state,
        lat      = loc$lat,
        lon      = loc$lon,
        product_focus = f$product_focus %||% "",
        design_scope  = f$design_scope %||% ""
      )
    })
  })

  df <- bind_rows(unlist(rows, recursive = FALSE))

  set.seed(44)
  df <- df %>%
    mutate(
      lat = lat + runif(n(), -0.06, 0.06),
      lon = lon + runif(n(), -0.06, 0.06)
    )

  df
}

# ---- Map design category to marker colour ----
design_category_color <- function(category) {
  switch(category,
    "Indian Fabless"     = "#620d3c",
    "GCC Design Centre"  = "#1565C0",
    "EDA & IP Provider"  = "#f1a222",
    "Design Services"    = "#8C8480",
    "#8C8480"
  )
}

# ---- Design score bar (reuses complexity-bar CSS) ----
design_score_bar_html <- function(score, label = "Design Score") {
  if (is.na(score)) return('<span class="complexity-bar" title="Not yet scored">—</span>')
  filled <- round(score)
  segments <- vapply(1:5, function(i) {
    cls <- if (i <= filled) "complexity-segment filled" else "complexity-segment"
    glue('<span class="{cls}"></span>')
  }, character(1))
  glue('<span class="complexity-bar" title="{label}: {score}/5">{paste(segments, collapse = "")}</span>')
}

# ---- DLI support badge (PDLI grant vs listed on the Chips-DLI portal without a grant) ----
dli_support_badge <- function(tier) {
  if (is.na(tier)) return("")
  css_class <- if (tier == "PDLI grant") "badge-operational" else "badge-approved"
  glue('<span class="status-badge {css_class}">{tier}</span>')
}

# ---- Design category badge ----
design_category_badge <- function(category) {
  css_class <- switch(category,
    "Indian Fabless"     = "badge-approved",
    "GCC Design Centre"  = "badge-construction",
    "EDA & IP Provider"  = "badge-onhold",
    "Design Services"    = "badge-announced",
    "badge-announced"
  )
  glue('<span class="status-badge {css_class}">{category}</span>')
}

# ---- Build leaflet popup for design firms ----
make_design_popup <- function(row) {
  parent_html <- if (!is.na(row$parent_company)) {
    glue('<div class="popup-row"><span class="popup-label">Parent:</span> {row$parent_company} ({row$parent_hq})</div>')
  } else ""

  headcount_html <- if (!is.na(row$india_headcount)) {
    glue('<div class="popup-row"><span class="popup-label">India headcount:</span> ~{format(row$india_headcount, big.mark = ",")}</div>')
  } else ""

  glue('
    <div class="facility-popup">
      <h4>{row$name}</h4>
      <div class="popup-row">{design_category_badge(row$category)}</div>
      {parent_html}
      <div class="popup-row"><span class="popup-label">Focus:</span> {row$product_focus}</div>
      <div class="popup-row"><span class="popup-label">Scope:</span> {row$design_scope}</div>
      <div class="popup-row"><span class="popup-label">Node:</span> {row$node_sophistication}</div>
      {headcount_html}
      <div class="popup-row" style="margin-top:6px;"><a href="design-firms/{row$id}.html" class="btn-detail">Full Profile →</a></div>
    </div>
  ')
}

# ---- Load and flatten equipment/materials YAML into a tibble ----
load_equipment <- function(path = "data/equipment_materials.yml") {
  raw <- yaml::read_yaml(path)

  rows <- lapply(raw$equipment_materials, function(f) {
    tibble(
      id                = f$id,
      name              = f$name,
      category          = f$category,
      parent_company    = f$parent_company %||% NA_character_,
      parent_hq         = f$parent_hq %||% NA_character_,
      city              = f$location$city,
      state             = f$location$state,
      lat               = f$location$lat,
      lon               = f$location$lon,
      investment_inr    = if (!is.null(f$investment) && !is.null(f$investment$total_inr)) f$investment$total_inr else NA_real_,
      investment_usd_m  = if (!is.null(f$investment) && !is.null(f$investment$total_usd_million)) f$investment$total_usd_million else NA_real_,
      status            = f$status,
      supplies_to       = paste(f$supplies_to, collapse = ", "),
      significance      = f$narrative$significance %||% "",
      what_it_supplies  = f$narrative$what_it_supplies %||% ""
    )
  })

  df <- bind_rows(rows)

  set.seed(45)
  df <- df %>%
    mutate(
      lat = lat + runif(n(), -0.015, 0.015),
      lon = lon + runif(n(), -0.015, 0.015)
    )

  df
}

# ---- Format equipment/materials investment (₹ crore and/or $ million) ----
format_equipment_investment <- function(inr, usd_m) {
  parts <- c()
  if (!is.na(inr) && inr > 0) parts <- c(parts, paste0("₹", format(inr, big.mark = ","), " crore"))
  if (!is.na(usd_m) && usd_m > 0) parts <- c(parts, paste0("$", format(usd_m, big.mark = ","), "M"))
  if (length(parts) == 0) return("Not disclosed")
  paste(parts, collapse = " / ")
}

# ---- Map equipment/materials category to marker colour ----
equipment_category_color <- function(category) {
  switch(category,
    "Equipment Manufacturer"    = "#620d3c",
    "Gases & Chemicals"         = "#1565C0",
    "Materials & Substrates"    = "#2f6b4a",
    "Infrastructure & Services" = "#f1a222",
    "#8C8480"
  )
}

# ---- Equipment/materials category badge ----
equipment_category_badge <- function(category) {
  css_class <- switch(category,
    "Equipment Manufacturer"    = "badge-approved",
    "Gases & Chemicals"         = "badge-construction",
    "Materials & Substrates"    = "badge-operational",
    "Infrastructure & Services" = "badge-onhold",
    "badge-announced"
  )
  glue('<span class="status-badge {css_class}">{category}</span>')
}

# ---- Build leaflet popup for equipment/materials firms ----
make_equipment_popup <- function(row) {
  parent_html <- if (!is.na(row$parent_company)) {
    glue('<div class="popup-row"><span class="popup-label">Parent:</span> {row$parent_company} ({row$parent_hq})</div>')
  } else ""

  glue('
    <div class="facility-popup">
      <h4>{row$name}</h4>
      <div class="popup-row">{equipment_category_badge(row$category)}</div>
      {parent_html}
      <div class="popup-row"><span class="popup-label">Investment:</span> {format_equipment_investment(row$investment_inr, row$investment_usd_m)}</div>
      <div class="popup-row"><span class="popup-label">Status:</span> {status_badge_html(row$status)}</div>
      <div class="popup-row"><span class="popup-label">Supplies:</span> {row$what_it_supplies}</div>
      <div class="popup-row" style="margin-top:6px;"><a href="equipment-firms/{row$id}.html" class="btn-detail">Full Profile →</a></div>
    </div>
  ')
}

# ---- Load budget ----
load_budget <- function(path = "data/budget.yml") {
  raw <- yaml::read_yaml(path)
  rows <- lapply(raw$schemes, function(s) {
    alloc_rows <- lapply(s$allocations, function(a) {
      tibble(scheme_id = s$id, scheme_name = s$name, year = a$year, type = a$type, amount = a$amount)
    })
    bind_rows(alloc_rows)
  })
  bind_rows(rows)
}

# =====================================================================
# Analysis & Writing, Scorecard, Signposts (added Nov 2026)
# =====================================================================

# ---- Load writing list (data/writing.yml) → tibble, newest first ----
load_writing <- function(path = "data/writing.yml") {
  raw <- yaml::read_yaml(path)$writing
  bind_rows(lapply(raw, function(w) tibble(
    id = w$id, title = w$title,
    authors = paste(w$authors, collapse = " & "),
    outlet = w$outlet, date = as.Date(w$date), type = w$type,
    url = w$url, local_page = w$local_page %||% NA_character_,
    policy = w$policy %||% NA_character_, summary = trimws(w$summary)
  ))) %>% arrange(desc(date))
}

# ---- Load recommendation scorecard (data/scorecard.yml) ----
load_scorecard <- function(path = "data/scorecard.yml") {
  raw <- yaml::read_yaml(path)$recommendations
  bind_rows(lapply(raw, function(r) tibble(
    id = r$id, recommendation = r$recommendation,
    first_made = r$first_made,
    repeated = list(unlist(r$repeated) %||% character(0)),
    verdict = r$verdict, what_happened = trimws(r$what_happened)
  )))
}

# ---- Verdict badge for scorecard (reuses status badge colours) ----
verdict_badge_html <- function(verdict) {
  css_class <- switch(verdict,
    "Adopted"        = "badge-operational",
    "Partly adopted" = "badge-approved",
    "Not adopted"    = "badge-onhold",
    "Open"           = "badge-announced",
    "badge-announced"
  )
  glue('<span class="status-badge {css_class}">{verdict}</span>')
}

# ---- Load signposts (data/signposts.yml) → list(last_reviewed, tibble) ----
load_signposts <- function(path = "data/signposts.yml") {
  raw <- yaml::read_yaml(path)
  tbl <- bind_rows(lapply(raw$signposts, function(s) {
    ups <- s$updates %||% list()
    latest <- if (length(ups)) ups[[length(ups)]] else NULL
    tibble(
      id = s$id, signpost = s$signpost, why = s$why,
      due = if (is.null(s$due)) as.Date(NA) else as.Date(s$due),
      status = s$status, resolves_when = s$resolves_when,
      related = s$related %||% NA_character_,
      latest_date = if (is.null(latest)) as.Date(NA) else as.Date(latest$date),
      latest_note = if (is.null(latest)) NA_character_ else latest$note
    )
  }))
  list(last_reviewed = as.Date(raw$last_reviewed), signposts = tbl)
}

# ---- Signpost status badge ----
signpost_badge_html <- function(status) {
  css_class <- switch(status,
    "Met"     = "badge-operational",
    "Pending" = "badge-construction",
    "Slipped" = "badge-approved",
    "Missed"  = "badge-onhold",
    "badge-announced"
  )
  glue('<span class="status-badge {css_class}">{status}</span>')
}
