# Day 8: spatial cross-validation for a malaria prevalence model in Kenya
# Run from the repo root: Rscript day-08/spatial_cv.R  (or section by section in Positron)
# Every function is called as package::function; see Day 6 for the convention.

source("R/ahadi_style.R")
set.seed(2026)

data_dir <- "data/day-08"
out_dir <- "day-08"
fig_dir <- file.path(out_dir, "figures")
dir.create(data_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(fig_dir, recursive = TRUE, showWarnings = FALSE)

kenya_crs <- "EPSG:21037" # metres, for blocks and distances
k_folds <- 5
n_repeats <- 5
block_sizes_km <- c(10, 25, 50, 100, 200)
