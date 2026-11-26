# Validate all tracker YAML files before rendering.
# Catches the mistakes that silently break pages: missing required fields,
# typos in status/category values, malformed dates, and broken cross-references.
#
# Run from the repo root:   Rscript R/validate_data.R
# Exits with status 1 (failing CI) if any error is found.

library(yaml)

errors <- character(0)
err <- function(file, id, msg) {
  errors <<- c(errors, sprintf("%-28s %-32s %s", file, id %||% "<no id>", msg))
}
`%||%` <- function(a, b) if (is.null(a)) b else a

# A date is valid if it is NULL (optional) or parses as YYYY-MM-DD
check_date <- function(file, id, field, value) {
  if (is.null(value)) return(invisible())
  if (length(value) != 1) {
    err(file, id, sprintf("%s has %d values, expected one date", field, length(value)))
    return(invisible())
  }
  ok <- grepl("^\\d{4}-\\d{2}-\\d{2}$", as.character(value)) &&
        !is.na(as.Date(as.character(value), optional = TRUE))
  if (!ok) err(file, id, sprintf("bad date in %s: '%s'", field, value))
}
check_enum <- function(file, id, field, value, allowed) {
  if (is.null(value) || !(value %in% allowed))
    err(file, id, sprintf("%s '%s' not in {%s}", field, value %||% "NULL", paste(allowed, collapse = " | ")))
}
check_required <- function(file, id, item, fields) {
  for (f in fields) if (is.null(item[[f]])) err(file, id, sprintf("missing required field '%s'", f))
}
check_unique_ids <- function(file, items) {
  ids <- vapply(items, function(x) x$id %||% NA_character_, "")
  for (d in unique(ids[duplicated(ids)])) err(file, d, "duplicate id")
  ids
}
check_sources <- function(file, id, sources) {
  for (s in sources %||% list()) {
    if (is.null(s$url) || !grepl("^https?://", s$url)) err(file, id, "source missing a valid url")
    check_date(file, id, "sources.date", s$date)
  }
}

# ---- facilities.yml ---------------------------------------------------------
fac <- read_yaml("data/facilities.yml")$facilities
fac_ids <- check_unique_ids("facilities.yml", fac)
for (x in fac) {
  id <- x$id
  check_required("facilities.yml", id, x, c("id", "name", "company", "category", "type", "status", "location"))
  check_enum("facilities.yml", id, "category", x$category,
             c("Commercial (ISM Approved)", "Research & Strategic", "OSAT (Non-ISM)"))
  check_enum("facilities.yml", id, "type", x$type,
             c("Fab", "Assembly & Packaging", "Compound Semiconductor", "Research Fab"))
  check_enum("facilities.yml", id, "status", x$status,
             c("Announced", "Approved", "Under Construction", "Operational", "On Hold", "Cancelled"))
  for (k in c("technology_difficulty", "foreign_dependence", "capital_intensity")) {
    v <- x$complexity[[k]]
    if (!is.null(v) && !(v %in% 1:5)) err("facilities.yml", id, sprintf("complexity.%s must be 1–5", k))
  }
  for (d in names(x$dates %||% list())) if (!is.list(x$dates[[d]])) check_date("facilities.yml", id, paste0("dates.", d), x$dates[[d]])
  for (m in x$milestones %||% list()) check_date("facilities.yml", id, "milestones.date", m$date)
  check_sources("facilities.yml", id, x$sources)
}

# ---- design.yml -------------------------------------------------------------
des <- read_yaml("data/design.yml")$design_firms
des_ids <- check_unique_ids("design.yml", des)
for (x in des) {
  id <- x$id
  check_required("design.yml", id, x, c("id", "name", "category", "locations"))
  check_enum("design.yml", id, "category", x$category,
             c("Indian Fabless", "GCC Design Centre", "EDA & IP Provider", "Design Services"))
  if (!is.null(x$dli_support))
    check_enum("design.yml", id, "dli_support", x$dli_support, c("PDLI grant", "Listed as DLI beneficiary"))
  # A PDLI grant must match the dli block, and vice versa
  if (!is.null(x$dli$approved) && isTRUE(x$dli$approved) != identical(x$dli_support, "PDLI grant"))
    err("design.yml", id, "dli_support and dli.approved disagree")
  # score_notes keys must name a score the firm actually has
  for (k in names(x$score_notes %||% list())) if (is.null(x$design_score[[k]]))
    err("design.yml", id, sprintf("score_notes.%s has no matching design_score", k))
  check_sources("design.yml", id, x$sources)
}

# ---- equipment_materials.yml -----------------------------------------------
eq <- read_yaml("data/equipment_materials.yml")$equipment_materials
invisible(check_unique_ids("equipment_materials.yml", eq))
for (x in eq) {
  id <- x$id
  check_required("equipment_materials.yml", id, x, c("id", "name", "category", "status", "location"))
  check_enum("equipment_materials.yml", id, "category", x$category,
             c("Equipment Manufacturer", "Gases & Chemicals", "Materials & Substrates", "Infrastructure & Services"))
  check_enum("equipment_materials.yml", id, "status", x$status,
             c("Announced", "MoU Signed", "Under Construction", "Operational"))
  for (s in unlist(x$supplies_to)) if (!(s %in% fac_ids))
    err("equipment_materials.yml", id, sprintf("supplies_to '%s' is not a facility id", s))
  for (m in x$milestones %||% list()) check_date("equipment_materials.yml", id, "milestones.date", m$date)
  check_sources("equipment_materials.yml", id, x$sources)
}

# ---- budget.yml -------------------------------------------------------------
bud <- read_yaml("data/budget.yml")$schemes
for (s in bud) {
  for (f in unlist(s$related_facilities)) if (!(f %in% fac_ids))
    err("budget.yml", s$id, sprintf("related_facilities '%s' is not a facility id", f))
  for (a in s$allocations %||% list()) {
    if (!grepl("^FY\\d{2}$", a$year %||% "")) err("budget.yml", s$id, sprintf("bad year '%s'", a$year))
    check_enum("budget.yml", s$id, "allocation type", a$type, c("BE", "RE", "Actual"))
    if (!is.numeric(a$amount)) err("budget.yml", s$id, sprintf("non-numeric amount for %s %s", a$year, a$type))
  }
}

# ---- writing.yml, scorecard.yml, signposts.yml ------------------------------
wr <- read_yaml("data/writing.yml")$writing
wr_ids <- check_unique_ids("writing.yml", wr)
for (x in wr) {
  check_required("writing.yml", x$id, x, c("id", "title", "authors", "outlet", "date", "type", "url", "summary"))
  check_enum("writing.yml", x$id, "type", x$type, c("Op-ed", "Blog", "Talk"))
  check_date("writing.yml", x$id, "date", x$date)
  if (!is.null(x$local_page) && !file.exists(x$local_page))
    err("writing.yml", x$id, sprintf("local_page '%s' does not exist", x$local_page))
}

sc <- read_yaml("data/scorecard.yml")$recommendations
invisible(check_unique_ids("scorecard.yml", sc))
for (x in sc) {
  check_enum("scorecard.yml", x$id, "verdict", x$verdict, c("Adopted", "Partly adopted", "Not adopted", "Open"))
  for (w in c(x$first_made, unlist(x$repeated))) if (!(w %in% wr_ids))
    err("scorecard.yml", x$id, sprintf("'%s' is not a writing.yml id", w))
}

sp_raw <- read_yaml("data/signposts.yml")
check_date("signposts.yml", "last_reviewed", "last_reviewed", sp_raw$last_reviewed)
invisible(check_unique_ids("signposts.yml", sp_raw$signposts))
for (x in sp_raw$signposts) {
  check_required("signposts.yml", x$id, x, c("id", "signpost", "why", "status", "resolves_when"))
  check_enum("signposts.yml", x$id, "status", x$status, c("Pending", "Met", "Missed", "Slipped"))
  check_date("signposts.yml", x$id, "due", x$due)
  if (!is.null(x$related) && !(x$related %in% c(fac_ids, des_ids)))
    err("signposts.yml", x$id, sprintf("related '%s' is not a facility or design-firm id", x$related))
  for (u in x$updates %||% list()) check_date("signposts.yml", x$id, "updates.date", u$date)
}

# ---- Report -----------------------------------------------------------------
if (length(errors)) {
  cat(sprintf("Data validation FAILED with %d error(s):\n\n", length(errors)))
  cat(errors, sep = "\n")
  quit(status = 1)
} else {
  cat("Data validation passed: all YAML files OK.\n")
}
