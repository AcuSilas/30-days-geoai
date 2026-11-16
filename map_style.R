# AHADI house style for R figures: the same palette as src/geokit/style.py.
# Use with: source("R/ahadi_style.R")

ahadi <- c(
  navy = "#0F2333",
  bright_blue = "#5EAADD",
  golden_yellow = "#FFC225",
  light_blue = "#AADEE9",
  light_green = "#B3CB72",
  dark_yellow = "#AA9B33",
  gray_blue = "#628DA5"
)

ahadi_neutral <- c(
  pale_yellow = "#FFF3D3",
  lightest_gray = "#F8FBFD",
  light_gray = "#F2F2F3",
  mid_gray = "#DAD9D9",
  text_gray = "#5B5E67"
)

# Continuous ramps, light to dark, matching geokit's colour maps
ahadi_sequential <- grDevices::colorRampPalette(c(
  ahadi_neutral[["lightest_gray"]], ahadi[["light_blue"]], ahadi[["bright_blue"]],
  ahadi[["gray_blue"]], ahadi[["navy"]]
))
ahadi_vegetation <- grDevices::colorRampPalette(c(
  ahadi_neutral[["pale_yellow"]], ahadi[["golden_yellow"]], ahadi[["light_green"]],
  ahadi[["gray_blue"]], ahadi[["navy"]]
))
ahadi_diverging <- grDevices::colorRampPalette(c(
  ahadi[["dark_yellow"]], ahadi[["golden_yellow"]], ahadi_neutral[["light_gray"]],
  ahadi[["bright_blue"]], ahadi[["navy"]]
))

theme_ahadi <- function(base_size = 11) {
  ggplot2::theme_minimal(base_size = base_size) +
    ggplot2::theme(
      text = ggplot2::element_text(colour = ahadi[["navy"]]),
      plot.title = ggplot2::element_text(face = "bold", colour = ahadi[["navy"]]),
      axis.text = ggplot2::element_text(colour = ahadi_neutral[["text_gray"]]),
      axis.title = ggplot2::element_text(colour = ahadi_neutral[["text_gray"]]),
      panel.grid.major = ggplot2::element_line(colour = ahadi_neutral[["light_gray"]]),
      panel.grid.minor = ggplot2::element_blank(),
      legend.position = "bottom"
    )
}
