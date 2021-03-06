#!/usr/bin/env R
# Simple R stats run script
# Author: David Young, 2020

# Usage:
#   Rscript --verbose clrstats/run.R
# Adjust profiles in clrstats.R before running

kWorkDir <- "clrstats"
if (dir.exists(kWorkDir)) {
  # change working directory
  setwd(kWorkDir)
}

# load all source changes and run stats
devtools::load_all(file.path(getwd(), "R"))
runStats()
