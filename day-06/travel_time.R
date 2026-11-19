# Travel time to the nearest public health facility in Kenya

source("map_style.R")

data_dir <- "data/day-06"
out_dir <- "day-06"
fig_dir <- file.path(out_dir, "figures")
dir.create(data_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(fig_dir, recursive = TRUE, showWarnings = FALSE)

# Kenya's bounding box plus buffer for allowance
kenya_bbox <- matrix(
  c(33.5, -5.0, 42.5, 5.5),
  nrow = 2,
  dimnames = list(c("x", "y"), c("min", "max"))
)

thresholds <- c(30, 60, 120)
time_breaks <- c(0, 15, 30, 60, 120, 240, Inf)
time_labels <- c("< 15 m", "15-30 m", "30-60 m", "1-2 h", "2-4 h", "> 4 h")

# Download friction surfaces from Malaria Atlas Project
get_surface <- function(dataset_id, file) {
  if (!file.exists(file)) {
    surface <- malariaAtlas::getRaster(
      dataset_id = dataset_id,
      extent = kenya_bbox
    )
    terra::writeRaster(surface, file, overwrite = TRUE
    )
  }
  terra::rast(file)
}

friction <- list(
  walking = get_surface(
    "Accessibility__202001_Global_Walking_Only_Friction_Surface",
    file.path(data_dir, "friction_walking.tif")
  ),
  motorised = get_surface(
    "Accessibility__202001_Global_Motorized_Friction_Surface",
    file.path(data_dir, "friction_motorised.tif")
  )
)

print(friction$walking)
print(terra::global(friction$walking, range, na.rm = TRUE)) # minutes per meter

# Counties, facilities and people on the friction grid
counties <- sf::st_read(
  "data/day-02/kenya_adm1.geojson",
  quiet = TRUE) |>
  sf::st_make_valid() |>
  dplyr::select(county = shapeName)

facilities <- readr::read_csv(
  "data/day-03/ssa_facilities.csv",
  show_col_types = FALSE) |>
  dplyr::filter(country == "Kenya") |>
  sf::st_as_sf(coords = c("lon", "lat"), crs = 4326) |>
  sf::st_filter(counties)

message(nrow(facilities), " public facilities inside Kenya's counties")

pop_100m <- terra::rast("data/day-04/ken_pop_2026_100m.tif")

pop_km <- terra::aggregate(
  pop_100m,
  fact = 10,
  fun = "sum",
  na.rm = TRUE) |>
  terra::resample(
    friction$walking,
    method = "near"
)

kept <- terra::global(
  pop_km,
  "sum",
  na.rm = TRUE)[1, 1] /
  terra::global(pop_100m, "sum", na.rm = TRUE)[1, 1]

message(sprintf("population kept on the 1 km grid: %.2f%%", 100 * kept))

# Travel time
travel_time <- function(friction, points) {
  sources <- terra::rasterize(
    terra::vect(points), friction, field = 1)
  cost <- terra::ifel(
    !is.na(sources), 0, friction
  )
  terra::costDist(cost, target = 0)
}

tt <- terra::rast(lapply(friction, travel_time, points = facilities))
names(tt) <- names(friction)
terra::writeRaster(
  tt,
  file.path(data_dir, "travel_time_minutes.tif"),
  overwrite = TRUE
)

# Accessibility
county_v <- terra::vect(counties)
county_sum <- function(r)
  terra::zonal(r, county_v, fun = "sum", na.rm = TRUE)[, 1]

county_pop <- county_sum(pop_km)
access <- dplyr::tibble(county = counties$county, population = county_pop)

for (mode in names(tt)) {
  for (m in thresholds) {
    within <- county_sum(pop_km * (tt[[mode]] <= m))
    access[[paste0(mode, "_pct_within_", m)]] <- 100 * within / county_pop
  }
  reachable <- !is.na(tt[[mode]])
  access[[paste0(mode, "_mean_minutes_")]] <-
    county_sum(pop_km * tt[[mode]]) / county_sum(pop_km * reachable)
}

access <- access |>
  dplyr::mutate(
    dplyr::across(
      dplyr::where(
        is.numeric) & !population, \(x) round(x, 1))) |>
  dplyr::arrange(walking_pct_within_60)

readr::write_csv(access, file.path(out_dir, "county_access.csv"))

national <- sapply(names(tt), function(mode) {
  100 * terra::global(pop_km * (tt[[mode]] <= 60), "sum", na.rm = TRUE)[1, 1] /
    terra::global(pop_km, "sum", na.rm = TRUE)[1, 1]
})

print(round(national, 1))
print(utils::head(access, 10))

# Travel time figure 1: walking vs motorised
tt_kenya <- terra::crop(terra::mask(tt, county_v), county_v)

class_colours <- ahadi_sequential(length(time_labels) + 1)[-1]

grDevices::png(file.path(
  fig_dir, "travel_time_maps.png"),
  width = 2600,
  height = 1300,
  res = 200)

graphics::par(
  mfrow = c(1, 2),
  fg = ahadi[["navy"]],
  col.main = ahadi[["navy"]]
)

for (mode in names(tt)) {
  classes <- terra::classify(
    tt_kenya[[mode]],
    rcl = time_breaks,
    include.lowest = TRUE,
    right = FALSE
  )
  levels(classes) <- data.frame(
    id = seq_along(time_labels) - 1,
    travel_time = time_labels)
  terra::plot(
    classes,
    col = class_colours,
    all_levels = TRUE,
    axes = FALSE,
    mar = c(1, 1, 3, 7),
    main = paste("Travel time to nearest public facility,", mode),
    plg = list(title = "Travel time")
  )
  terra::lines(county_v, col = ahadi_neutral[["mid_gray"]], lwd = 0.4)
}
grDevices::dev.off()

# Figure 2: Burden-stricken counties
worst <- access |>
  dplyr::slice_head(n = 10) |>
  dplyr::mutate(
    walking = 100 - walking_pct_within_60,
    motorised = 100 - motorised_pct_within_60
  ) |>
  dplyr::select(county, walking, motorised) |>
  tidyr::pivot_longer(-county, names_to = "mode", values_to = "pct_over_60") |>
  dplyr::mutate(
    county = factor(county, levels = rev(access$county[1:10])),
    mode = factor(mode, levels = c("walking", "motorised"))
  )

p <- ggplot2::ggplot(
  worst,
  ggplot2::aes(x = pct_over_60, y = county, fill = mode)) +
  ggplot2::geom_col(
    position = ggplot2::position_dodge(width = 0.75), width = 0.7) +
  ggplot2::scale_fill_manual(
    values = c(
      walking = ahadi[["golden_yellow"]],
      motorised = ahadi[["navy"]]),
    name = NULL
  ) +
  ggplot2::scale_x_continuous(
    limits = c(0, 100),
    expand = ggplot2::expansion(mult = c(0, 0.03))
  ) +
  ggplot2::labs(
    title = "Share of people over an hour from a public facility",
    x = "% of county population more than 60 minutes away", y = NULL
  ) +
  theme_ahadi()

ggplot2::ggsave(
  file.path(fig_dir, "worst_counties.png"),
  p,
  width = 10,
  height = 5.5,
  dpi = 200
)

# Validation plot against MAP's own published travel-time map
map_tt <- get_surface(
  "Accessibility__202001_Global_Walking_Only_Travel_Time_To_Healthcare",
  file.path(data_dir, "map_walking_travel_time.tif")
) |>
  terra::resample(tt$walking, method = "near")

pairs <- as.data.frame(c(tt$walking, map_tt, pop_km), na.rm = TRUE)

names(pairs) <- c("ours", "map", "people")

pairs <- pairs[pairs$people > 0, ]
message(sprintf(
  "populated cells: %d | correlation of log travel times: %.2f | median ours/MAP: %.2f",
  nrow(pairs),
  stats::cor(log1p(pairs$ours), log1p(pairs$map)),
  stats::median((pairs$ours + 1) / (pairs$map + 1))
)
)
