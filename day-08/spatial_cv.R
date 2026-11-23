# Day 8: spatial cross-validation for a malaria prevalence model in Kenya
# Run from the repo root: Rscript day-08/spatial_cv.R  (or section by section in Positron)
# Every function is called as package::function; see Day 6 for the convention.

source("map_style.R")
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

# Step 1: PfPR surveys from MAP, standardised to ages 2-10
pr_file <- file.path(data_dir, "kenya_pfpr.csv")
if (!file.exists(pr_file)) {
  raw <- malariaAtlas::getPR(country = "Kenya", species = "Pf")
  readr::write_csv(as.data.frame(raw), pr_file)
}

counties <- sf::st_read("data/day-02/kenya_adm1.geojson", quiet = TRUE) |>
  sf::st_make_valid()

surveys <- readr::read_csv(pr_file, show_col_types = FALSE) |>
  dplyr::filter(
    !is.na(latitude), !is.na(longitude), # DHS points come without coordinates
    !is.na(lower_age), !is.na(upper_age),
    examined >= 10, year_start >= 2005
  ) |>
  dplyr::mutate(
    pfpr = malariaAtlas::convertPrevalence(positive / examined, lower_age, upper_age, 2, 10)
  ) |>
  sf::st_as_sf(coords = c("longitude", "latitude"), crs = 4326, remove = FALSE) |>
  sf::st_filter(counties)
message(sprintf(
  "%d surveys at %d distinct locations, %d to %d",
  nrow(surveys), dplyr::n_distinct(surveys$longitude, surveys$latitude),
  min(surveys$year_start), max(surveys$year_start)
))

# Step 2: Covariates at every survey location
elevation_file <- file.path(data_dir, "elevation_ken.tif")
if (!file.exists(elevation_file)) {
  elevation <- geodata::elevation_30s(country = "KEN", path = data_dir)
  terra::writeRaster(elevation, elevation_file, overwrite = TRUE)
}

chirps <- terra::rast("data/day-02/chirps_kenya_monthly.nc")
months <- terra::time(chirps)
baseline <- months >= as.Date("1991-01-01") & months <= as.Date("2020-12-31")
stopifnot(sum(baseline) == 360)

covariates <- list(
  elevation_m = terra::rast(elevation_file),
  rain_mm_year = terra::mean(chirps[[which(baseline)]], na.rm = TRUE) * 12,
  travel_min = terra::rast("data/day-06/travel_time_minutes.tif")[["walking"]],
  log_pop_km2 = log1p(terra::aggregate(
    terra::rast("data/day-04/ken_pop_2026_100m.tif"),
    fact = 10, fun = "sum", na.rm = TRUE
  ))
)
survey_points <- terra::vect(surveys)
for (name in names(covariates)) {
  surveys[[name]] <- terra::extract(covariates[[name]], survey_points, ID = FALSE)[, 1]
}
features <- c(names(covariates), "year_start")
surveys <- dplyr::filter(surveys, dplyr::if_all(dplyr::all_of(features), \(x) !is.na(x)))

survey_data <- sf::st_drop_geometry(surveys)
xy <- sf::st_coordinates(sf::st_transform(surveys, kenya_crs)) # metres
message(nrow(survey_data), " surveys with every covariate")
readr::write_csv(
  dplyr::mutate(survey_data, x_m = xy[, 1], y_m = xy[, 2]),
  file.path(data_dir, "model_data.csv")
)

# Step 3: One model, many ways to test it
fit_predict <- function(train, test) {
  model <- ranger::ranger(
    x = train[features], y = train$pfpr, case.weights = train$examined,
    num.trees = 300, seed = 1
  )
  stats::predict(model, test[features])$predictions
}

cv_predictions <- function(folds) {
  predicted <- numeric(nrow(survey_data))
  for (k in unique(folds)) {
    test <- folds == k
    predicted[test] <- fit_predict(survey_data[!test, ], survey_data[test, ])
  }
  predicted
}

rmse <- function(predicted) sqrt(mean((predicted - survey_data$pfpr)^2))

random_folds <- function() sample(rep_len(seq_len(k_folds), nrow(survey_data)))

block_folds <- function(size_km) {
  block <- paste(floor(xy[, 1] / (size_km * 1000)), floor(xy[, 2] / (size_km * 1000)))
  blocks <- unique(block)
  fold_of_block <- sample(rep_len(seq_len(k_folds), length(blocks)))
  fold_of_block[match(block, blocks)]
}

# Step 4: Random vs spatial block cross-validation
results <- list()
for (r in seq_len(n_repeats)) {
  results[[length(results) + 1]] <- data.frame(
    block_km = 0, repeat_id = r, rmse = rmse(cv_predictions(random_folds()))
  )
  for (size in block_sizes_km) {
    results[[length(results) + 1]] <- data.frame(
      block_km = size, repeat_id = r, rmse = rmse(cv_predictions(block_folds(size)))
    )
  }
}
results <- dplyr::bind_rows(results)
summary_table <- results |>
  dplyr::group_by(block_km) |>
  dplyr::summarise(mean_rmse = mean(rmse), sd_rmse = stats::sd(rmse), .groups = "drop") |>
  dplyr::mutate(strategy = ifelse(block_km == 0, "random", paste(block_km, "km blocks")))
print(summary_table)
readr::write_csv(results, file.path(out_dir, "cv_results.csv"))

# Step 5: Figure 1: estimated error grows when tests are far from training data
p1 <- ggplot2::ggplot(results, ggplot2::aes(x = factor(block_km), y = rmse)) +
  ggplot2::geom_point(
    colour = ahadi[["gray_blue"]], alpha = 0.6, size = 2,
    position = ggplot2::position_jitter(width = 0.08, height = 0, seed = 1)
  ) +
  ggplot2::stat_summary(
    fun = mean, geom = "line", group = 1, colour = ahadi[["navy"]], linewidth = 0.9
  ) +
  ggplot2::stat_summary(fun = mean, geom = "point", colour = ahadi[["navy"]], size = 3) +
  ggplot2::scale_x_discrete(labels = c("Random", paste(block_sizes_km, "km"))) +
  ggplot2::labs(
    title = "Cross-validated error of a PfPR model",
    subtitle = "By how surveys are split. 5 repeats each.",
    x = "Cross-validation: random folds, or spatial blocks of this size",
    y = "RMSE (PfPR 2-10)"
  ) +
  theme_ahadi()
ggplot2::ggsave(file.path(fig_dir, "rmse_by_block_size.png"), p1, width = 9, height = 5, dpi = 200)

# Step 6: Figure 2: do the tests look like the real prediction task?
nearest_km <- function(from, to) {
  d2 <- outer(from[, 1], to[, 1], "-")^2 + outer(from[, 2], to[, 2], "-")^2
  sqrt(apply(d2, 1, min)) / 1000
}

test_distances <- function(folds) {
  unlist(lapply(unique(folds), function(k) {
    nearest_km(xy[folds == k, , drop = FALSE], xy[folds != k, , drop = FALSE])
  }))
}

populated <- terra::mask(covariates$log_pop_km2, terra::vect(counties))
targets <- terra::spatSample(populated, 3000, method = "random", na.rm = TRUE, xy = TRUE)
target_xy <- sf::st_coordinates(sf::st_transform(
  sf::st_as_sf(targets, coords = c("x", "y"), crs = 4326), kenya_crs
))

distances <- dplyr::bind_rows(
  data.frame(set = "Where the model must predict", km = nearest_km(target_xy, xy)),
  data.frame(set = "Random CV test points", km = test_distances(random_folds())),
  data.frame(set = "50 km block CV test points", km = test_distances(block_folds(50)))
)
print(dplyr::summarise(dplyr::group_by(distances, set), median_km = stats::median(km)))

p2 <- ggplot2::ggplot(distances, ggplot2::aes(x = km + 0.1, colour = set)) +
  ggplot2::stat_ecdf(linewidth = 1) +
  ggplot2::scale_x_log10(breaks = c(0.1, 1, 10, 100), labels = c("0", "1", "10", "100")) +
  ggplot2::scale_colour_manual(values = c(
    "Where the model must predict" = ahadi[["navy"]],
    "Random CV test points" = ahadi[["golden_yellow"]],
    "50 km block CV test points" = ahadi[["bright_blue"]]
  ), breaks = c(
    "Where the model must predict", "Random CV test points", "50 km block CV test points"
  ), name = NULL) +
  ggplot2::labs(
    title = "Distance from each point to the nearest training survey",
    subtitle = "(cumulative share)",
    x = "Distance to nearest training survey (km, log scale)", y = "Share of points"
  ) +
  theme_ahadi()
ggplot2::ggsave(
  file.path(fig_dir, "distance_to_training.png"), p2,
  width = 9, height = 5, dpi = 200
)
