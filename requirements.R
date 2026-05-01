# Install all packages required by Golfstats.R
packages <- c(
  "readxl",       # read Excel input data
  "writexl",      # write Excel output tables
  "tidyverse",    # core data manipulation (dplyr, tidyr, ggplot2, ...)
  "dplyr",        # data wrangling
  "tidyr",        # reshaping data
  "ggplot2",      # base visualisation
  "GGally",       # pairwise / correlation matrix plots
  "patchwork",    # compose multiple ggplot panels
  "RColorBrewer"  # colour palettes
)

install.packages(setdiff(packages, rownames(installed.packages())))
