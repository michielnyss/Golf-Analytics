library(readxl)
library(writexl)
library(tidyverse)
library(dplyr)
library(tidyr)
library(patchwork)
library(ggplot2)
library(GGally)
library(patchwork)


make_boxplot <- function(
    data,
    x_var,
    y_var,
    title        = NULL,
    subtitle     = NULL,
    x_label      = x_var,
    y_label      = y_var,
    palette      = "Set2",
    show_mean    = TRUE,
    show_points  = TRUE,
    jitter_width = 0.15,
    point_alpha  = 0.5,
    flip         = FALSE,
    benchmark    = NULL,
    jitter_mode      = "random",  # "random" | "offline"
    offline_var      = NULL,      # column with lateral miss (m), required for jitter_mode = "offline"
    offline_ref_dist = c(5, 10)   # reference distances (m) to label on the offline axis
) {
  if (jitter_mode == "offline" && is.null(offline_var))
    stop("offline_var must be provided when jitter_mode = 'offline'")

  # -------------------------
  # OFFLINE MODE: numeric group positions + lateral offset
  # -------------------------
  if (jitter_mode == "offline") {
    club_levels  <- sort(unique(data[[x_var]]))
    n_groups     <- length(club_levels)
    # scale so the 90th-percentile miss fills ~40% of the space between clubs
    scale_factor <- 0.4 / quantile(abs(data[[offline_var]]), 0.90, na.rm = TRUE)

    data$.group_pos <- as.numeric(factor(data[[x_var]], levels = club_levels))
    data$.x_pos     <- data$.group_pos + data[[offline_var]] * scale_factor

    if (is.null(subtitle))
      subtitle <- paste0(
        if (show_mean) "\u25c7 = mean  \u00b7  " else "",
        "Dot x-position = lateral miss (m, \u2190left | right\u2192)"
      )

    pal <- colorRampPalette(RColorBrewer::brewer.pal(8, palette))(n_groups)
    names(pal) <- club_levels

    p <- ggplot(data, aes(
      x     = .group_pos,
      y     = .data[[y_var]],
      fill  = .data[[x_var]],
      color = .data[[x_var]],
      group = .data[[x_var]]
    )) +
      geom_boxplot(
        alpha         = 0.4,
        outlier.shape = NA,
        width         = 0.55,
        linewidth     = 0.5
      )

    if (show_points) {
      p <- p + geom_point(
        aes(x = .x_pos),
        size  = 1.2,
        alpha = point_alpha,
        shape = 16
      )
    }

    if (show_mean) {
      p <- p + stat_summary(
        fun    = mean,
        geom   = "point",
        shape  = 23,
        size   = 3,
        fill   = "white",
        stroke = 0.8
      )
    }

    if (!is.null(benchmark)) {
      if (is.list(benchmark) && !is.data.frame(benchmark)) benchmark <- as.data.frame(benchmark)
      benchmark <- benchmark[benchmark[[x_var]] %in% club_levels, , drop = FALSE]
      if (nrow(benchmark) > 0) {
        benchmark$.group_pos <- as.numeric(factor(benchmark[[x_var]], levels = club_levels))
        p <- p + geom_point(
          data        = benchmark,
          aes(x = .group_pos, y = .data[[y_var]]),
          inherit.aes = FALSE,
          shape = 23, size = 3.5, fill = "yellow", color = "black"
        )
      }
    }

    # Reference distance markers on the offline axis
    if (length(offline_ref_dist) > 0) {
      y_min  <- min(data[[y_var]], na.rm = TRUE)
      y_max  <- max(data[[y_var]], na.rm = TRUE)
      y_span <- y_max - y_min

      ref_df <- do.call(rbind, lapply(seq_len(n_groups), function(g) {
        do.call(rbind, lapply(offline_ref_dist, function(d) {
          rbind(
            data.frame(x = g + d * scale_factor, xend = g + d * scale_factor,
                       y = y_min, yend = y_max,
                       lx = g + d * scale_factor, ly = y_min - y_span * 0.04,
                       label = paste0("+", d, "m")),
            data.frame(x = g - d * scale_factor, xend = g - d * scale_factor,
                       y = y_min, yend = y_max,
                       lx = g - d * scale_factor, ly = y_min - y_span * 0.04,
                       label = paste0("-", d, "m"))
          )
        }))
      }))

      p <- p +
        geom_segment(
          data        = ref_df,
          aes(x = x, xend = xend, y = y, yend = yend),
          inherit.aes = FALSE,
          color       = "grey75",
          linewidth   = 0.3,
          linetype    = "dashed"
        ) +
        geom_text(
          data        = ref_df,
          aes(x = lx, y = ly, label = label),
          inherit.aes = FALSE,
          size        = 2.5,
          color       = "grey55",
          vjust       = 1
        )
    }

    p <- p +
      scale_x_continuous(breaks = seq_len(n_groups), labels = club_levels) +
      scale_fill_manual(values  = pal, guide = "none") +
      scale_color_manual(values = pal, guide = "none") +
      theme_minimal(base_size = 12) +
      theme(
        plot.title         = element_text(face = "bold", size = 13),
        plot.subtitle      = element_text(color = "grey50", size = 10),
        axis.title         = element_text(size = 10),
        panel.grid.major.x = element_blank()
      ) +
      labs(title = title, subtitle = subtitle, x = x_label, y = y_label)

    if (flip) p <- p + coord_flip()
    return(p)
  }

  # -------------------------
  # RANDOM JITTER MODE (original behaviour)
  # -------------------------
  if (is.null(subtitle)) {
    parts <- character(0)
    if (show_points) parts <- c(parts, "Dots = individual observations")
    if (show_mean)   parts <- c(parts, "\u25c7 = mean")
    subtitle <- if (length(parts)) paste(parts, collapse = " \u00b7 ") else NULL
  }

  p <- ggplot(data, aes(
    x     = .data[[x_var]],
    y     = .data[[y_var]],
    fill  = .data[[x_var]],
    color = .data[[x_var]]
  )) +
    geom_boxplot(
      alpha         = 0.4,
      outlier.shape = NA,
      width         = 0.55,
      linewidth     = 0.5
    )

  if (show_points) {
    p <- p + geom_jitter(
      width = jitter_width,
      size  = 1.2,
      alpha = point_alpha,
      shape = 16
    )
  }

  if (show_mean) {
    p <- p + stat_summary(
      fun    = mean,
      geom   = "point",
      shape  = 23,
      size   = 3,
      fill   = "white",
      stroke = 0.8
    )
  }

  # -------------------------
  # BENCHMARK LAYER (filtered)
  # -------------------------
  if (!is.null(benchmark)) {

    if (is.list(benchmark) && !is.data.frame(benchmark)) benchmark <- as.data.frame(benchmark)

    benchmark <- benchmark[
      benchmark[[x_var]] %in% unique(data[[x_var]]),
      , drop = FALSE
    ]

    if (nrow(benchmark) > 0) {
      p <- p +
        geom_point(
          data = benchmark,
          aes(x = .data[[x_var]], y = .data[[y_var]]),
          inherit.aes = FALSE,
          shape = 23, size = 3.5, fill = "yellow", color = "black"
        )
    }
  }

  # -------------------------
  # STYLING
  # -------------------------
  n_groups <- length(unique(data[[x_var]]))
  pal <- colorRampPalette(RColorBrewer::brewer.pal(8, palette))(n_groups)

  p <- p +
    scale_fill_manual(values = pal, guide = "none") +
    scale_color_manual(values = pal, guide = "none") +
    theme_minimal(base_size = 12) +
    theme(
      plot.title         = element_text(face = "bold", size = 13),
      plot.subtitle      = element_text(color = "grey50", size = 10),
      axis.title         = element_text(size = 10),
      panel.grid.major.x = element_blank()
    ) +
    labs(title = title, subtitle = subtitle, x = x_label, y = y_label)

  if (flip) p <- p + coord_flip()

  p
}


pairwise_plot <- function(
    data,
    columns,
    group_var    = NULL,
    title        = "Pairwise relationships",
    palette      = "Set2",
    upper        = "cor",
    lower        = "points",
    diag         = "densityDiag",
    point_size   = 0.8,
    point_alpha  = 0.6,
    legend_pos   = "bottom"
) {
  # Build mapping: add colour only if group_var is supplied
  mapping <- if (!is.null(group_var)) {
    aes(color = .data[[group_var]], fill = .data[[group_var]], alpha = point_alpha)
  } else {
    aes(alpha = point_alpha)
  }
  
  p <- ggpairs(
    data    = data,
    columns = columns,
    mapping = mapping,
    upper   = list(continuous = wrap(upper, size = 3.5, stars = FALSE)),
    lower   = list(continuous = wrap(lower, size = point_size)),
    diag    = list(continuous = wrap(diag,  alpha = 0.4))
  )
  
  # Apply colour scales only when grouping
  if (!is.null(group_var)) {
    p <- p +
      scale_color_brewer(palette = palette, name = group_var) +
      scale_fill_brewer(palette  = palette, name = group_var)
  }
  
  p +
    theme_minimal(base_size = 11) +
    theme(
      plot.title       = element_text(face = "bold", size = 13),
      strip.text       = element_text(size = 9, face = "bold"),
      legend.position  = legend_pos,
      panel.grid.minor = element_blank()
    ) +
    labs(title = title)
}


shot_shape_rose <- function(
    data,
    club_path,
    attack_angle,
    group_var      = NULL,
    title          = "Shot shape rose",
    palette        = "Set2",
    ellipse        = TRUE,
    facet          = FALSE,
    ellipse_level  = 0.75
) {
  mapping <- if (!is.null(group_var)) {
    aes(
      x     = .data[[club_path]],
      y     = .data[[attack_angle]],
      color = .data[[group_var]],
      fill  = .data[[group_var]]
    )
  } else {
    aes(
      x = .data[[club_path]],
      y = .data[[attack_angle]]
    )
  }
  
  p <- ggplot(data, mapping) +
    
    # Reference lines — zero axes
    geom_hline(yintercept = 0, linewidth = 0.4, linetype = "dashed", color = "grey60") +
    geom_vline(xintercept = 0, linewidth = 0.4, linetype = "dashed", color = "grey60") +
    
    # Quadrant labels
    annotate("text", x =  8, y =  8, label = "In-to-out\nUpward",   size = 2.8, color = "grey50", hjust = 0) +
    annotate("text", x = -8, y =  8, label = "Out-to-in\nUpward",   size = 2.8, color = "grey50", hjust = 1) +
    annotate("text", x =  8, y = -8, label = "In-to-out\nDownward", size = 2.8, color = "grey50", hjust = 0) +
    annotate("text", x = -8, y = -8, label = "Out-to-in\nDownward", size = 2.8, color = "grey50", hjust = 1) +
    
    # Individual shots
    geom_point(size = 1.5, alpha = 0.5, shape = 16)
  
  # Confidence ellipses
  if (ellipse) {
    p <- p + stat_ellipse(
      geom  = "polygon",
      level = ellipse_level,
      alpha = 0.12,
      linewidth = 0.6
    )
  }
  
  # Polar coordinates — note: coord_polar maps x to angle, y to radius,
  # but for a shot shape plot we want a standard Cartesian feel with
  # circular grid lines, so we use coord_fixed() + circular reference rings
  p <- p +
    # Circular reference rings at 5 and 10 degrees radius
    annotate("path",
             x = 5 * cos(seq(0, 2 * pi, length.out = 200)),
             y = 5 * sin(seq(0, 2 * pi, length.out = 200)),
             color = "grey80", linewidth = 0.3, linetype = "dotted"
    ) +
    annotate("path",
             x = 10 * cos(seq(0, 2 * pi, length.out = 200)),
             y = 10 * sin(seq(0, 2 * pi, length.out = 200)),
             color = "grey80", linewidth = 0.3, linetype = "dotted"
    ) +
    annotate("text", x = 0, y =  5.3, label = "5°",  size = 2.5, color = "grey60") +
    annotate("text", x = 0, y = 10.3, label = "10°", size = 2.5, color = "grey60") +
    
    coord_fixed(xlim = c(-12, 12), ylim = c(-12, 12)) +
    theme_minimal(base_size = 11) +
    theme(
      plot.title        = element_text(face = "bold", size = 13),
      plot.subtitle     = element_text(color = "grey50", size = 10),
      panel.grid        = element_blank(),
      axis.ticks        = element_blank(),
      legend.position   = "bottom"
    ) +
    labs(
      title    = title,
      subtitle = paste0("Ellipses = ", ellipse_level * 100, "% confidence region"),
      x        = "Club path (degrees)  ←out-to-in  |  in-to-out→",
      y        = "Attack angle (degrees)  ↓downward  |  upward↑",
      color    = group_var,
      fill     = group_var
    )
  
  if (!is.null(group_var)) {
    p <- p +
      scale_color_brewer(palette = palette) +
      scale_fill_brewer(palette  = palette)
  }
  
  if (facet && !is.null(group_var)) {
    p <- p + facet_wrap(vars(.data[[group_var]]))
  }
  
  p
}


launch_condition_triangle <- function(data, club_type, windows_lookup) {
  
  library(ggplot2)
  library(patchwork)
  library(dplyr)
  
  # Get windows for selected club
  windows <- windows_lookup[[club_type]]
  
  if (is.null(windows)) {
    stop(paste("No launch windows defined for", club_type))
  }
  
  club_data <- data %>%
    filter(`Club Type` == club_type)
  
  p1 <- ggplot(club_data, aes(x = `Ball Speed [km/h]`, y = `Launch Angle [deg]`)) +
    annotate("rect",
             xmin = windows$speed[1], xmax = windows$speed[2],
             ymin = windows$launch[1], ymax = windows$launch[2],
             alpha = 0.15, fill = "green") +
    geom_point(alpha = 0.6, color = "steelblue") +
    geom_vline(xintercept = windows$speed, linetype = "dashed", color = "red") +
    geom_hline(yintercept = windows$launch, linetype = "dashed", color = "red") +
    theme_minimal() +
    labs(title = "Ball Speed vs Launch Angle")
  
  p2 <- ggplot(club_data, aes(x = `Ball Speed [km/h]`, y = `Spin Rate [rpm]`)) +
    annotate("rect",
             xmin = windows$speed[1], xmax = windows$speed[2],
             ymin = windows$spin[1], ymax = windows$spin[2],
             alpha = 0.15, fill = "green") +
    geom_point(alpha = 0.6, color = "darkgreen") +
    geom_vline(xintercept = windows$speed, linetype = "dashed", color = "red") +
    geom_hline(yintercept = windows$spin, linetype = "dashed", color = "red") +
    theme_minimal() +
    labs(title = "Ball Speed vs Spin Rate")
  
  p3 <- ggplot(club_data, aes(x = `Launch Angle [deg]`, y = `Spin Rate [rpm]`)) +
    annotate("rect",
             xmin = windows$launch[1], xmax = windows$launch[2],
             ymin = windows$spin[1], ymax = windows$spin[2],
             alpha = 0.15, fill = "green") +
    geom_point(alpha = 0.6, color = "purple") +
    geom_vline(xintercept = windows$launch, linetype = "dashed", color = "red") +
    geom_hline(yintercept = windows$spin, linetype = "dashed", color = "red") +
    theme_minimal() +
    labs(title = "Launch Angle vs Spin Rate")
  
  (p1 | p2) / p3 +
    plot_annotation(title = paste("Launch Condition Triangle -", club_type))
}


compute_means_table <- function(data, grouper) {
  numeric_cols <- names(data)[sapply(data, is.numeric)]
  data %>%
    group_by(.data[[grouper]]) %>%
    summarise(across(all_of(numeric_cols), ~ mean(.x, na.rm = TRUE)), .groups = "drop")
}


compare_to_benchmark <- function(
    data,
    benchmark,
    grouper,
    mode          = "hybrid",   # "absolute" | "percent" | "hybrid"
    input         = "mean",     # "mean" (pre-summarised) | "raw" (shot-level)
    metric_labels = NULL
) {
  if (input == "raw") {
    data    <- data %>% mutate(.shot_id = row_number())
    id_cols <- c(".shot_id", grouper)
    bm_ref  <- compute_means_table(benchmark, grouper)  # one row per club
  } else {
    id_cols <- grouper
    bm_ref  <- benchmark
  }

  shared_cols <- intersect(
    setdiff(names(data),   id_cols),
    setdiff(names(bm_ref), grouper)
  )

  my_long <- data %>%
    select(all_of(c(id_cols, shared_cols))) %>%
    pivot_longer(-all_of(id_cols), names_to = "Metric", values_to = "You")

  bm_long <- bm_ref %>%
    select(all_of(c(grouper, shared_cols))) %>%
    pivot_longer(-all_of(grouper), names_to = "Metric", values_to = "Benchmark")

  # join on (grouper, Metric): each shot gets the benchmark for its club type
  # left_join keeps all shots; clubs with no benchmark row get NA deltas
  comparison <- my_long %>%
    left_join(bm_long, by = c(grouper, "Metric")) %>%
    mutate(
      Delta   = You - Benchmark,
      PctDiff = (You - Benchmark) / Benchmark * 100
    )

  if (mode == "hybrid") {
    comparison <- comparison %>%
      mutate(
        .fill_raw = ifelse(is.finite(PctDiff), PctDiff, Delta),
        label     = ifelse(is.finite(PctDiff),
                           sprintf("%+.1f%%", PctDiff),
                           sprintf("%+.1f",   Delta))
      )
  } else {
    label_fmt <- switch(mode,
      absolute = function(x) sprintf("%+.1f",  x),
      percent  = function(x) sprintf("%+.1f%%", x),
      stop("Unknown mode '", mode, "'. Supported: 'absolute', 'percent', 'hybrid'")
    )
    fill_col <- switch(mode, absolute = "Delta", percent = "PctDiff")
    comparison <- comparison %>%
      mutate(
        .fill_raw = .data[[fill_col]],
        label     = label_fmt(.data[[fill_col]])
      )
  }

  comparison <- comparison %>%
    mutate(
      MetricShort = if (!is.null(metric_labels))
        ifelse(Metric %in% names(metric_labels), metric_labels[Metric], Metric)
      else
        Metric
    )

  attr(comparison, "mode") <- mode
  comparison
}


plot_benchmark_heatmap <- function(
    comparison,
    grouper,
    title = "Performance vs benchmark",
    mode  = NULL
) {
  if (is.null(mode)) mode <- attr(comparison, "mode")
  if (is.null(mode)) mode <- "hybrid"

  # Normalise per metric so fill encodes distance from benchmark within each metric
  comparison <- comparison %>%
    group_by(Metric) %>%
    mutate(.fill = {
      cap_m <- max(abs(.fill_raw), na.rm = TRUE)
      if (is.na(cap_m) || cap_m == 0) 0 else abs(.fill_raw) / cap_m
    }) %>%
    ungroup()

  ggplot(comparison, aes(x = MetricShort, y = fct_rev(.data[[grouper]]), fill = .fill)) +
    geom_tile(color = "white", linewidth = 0.6) +
    geom_text(aes(label = label), size = 3.2, fontface = "bold") +
    scale_fill_gradient(
      low    = "white",
      high   = "#d73027",
      limits = c(0, 1),
      guide  = "none"
    ) +
    labs(
      title    = title,
      subtitle = switch(mode,
        absolute = "Cell = absolute delta  ·  White = on benchmark / Red = far from benchmark",
        percent  = "Cell = % delta  ·  White = on benchmark / Red = far from benchmark",
        hybrid   = "Cell = % delta (absolute where benchmark = 0)  ·  White = on benchmark / Red = far from benchmark"
      ),
      x = NULL,
      y = NULL
    ) +
    theme_minimal(base_size = 13) +
    theme(
      axis.text.x     = element_text(angle = 30, hjust = 1),
      panel.grid      = element_blank(),
      legend.position = "right"
    )
}


table_benchmark_comparison <- function(comparison, grouper, mode = NULL, digits = 1) {
  if (is.null(mode)) mode <- attr(comparison, "mode")
  if (is.null(mode)) mode <- "hybrid"

  is_raw  <- ".shot_id" %in% names(comparison)
  id_cols <- if (is_raw) c(".shot_id", grouper) else grouper

  comparison <- comparison %>%
    mutate(
      cell_value = switch(mode,
        absolute = sprintf("%+.1f",   round(Delta,   digits)),
        percent  = sprintf("%+.1f%%", round(PctDiff, digits)),
        hybrid   = ifelse(is.finite(PctDiff),
                          sprintf("%+.1f%%", round(PctDiff, digits)),
                          sprintf("%+.1f",   round(Delta,   digits))),
        stop("Unknown mode '", mode, "'. Use 'absolute', 'percent', or 'hybrid'")
      )
    )

  tbl <- comparison %>%
    select(all_of(c(id_cols, "MetricShort", "cell_value"))) %>%
    pivot_wider(names_from = MetricShort, values_from = cell_value) %>%
    arrange(.data[[grouper]])

  if (is_raw) names(tbl)[names(tbl) == ".shot_id"] <- "Shot"
  tbl
}


shot_birdview_facet <- function(
    data,
    bezier_n = 40,
    ncol     = 4,
    title    = "Ball flight – bird's eye view"
) {
  club_levels_present <- intersect(club_order, unique(data$`Club Type`))

  data <- data %>%
    mutate(
      .shot_id   = row_number(),
      .club_type = factor(`Club Type`, levels = club_levels_present),
      shot_shape = factor(`Shot Shape`, levels = c("Draw", "Straight", "Fade"))
    )

  t_seq <- seq(0, 1, length.out = bezier_n)

  # Quadratic Bézier: P0=(0,0), P1 along launch direction, P2=carry landing
  curve_df <- pmap_dfr(
    list(
      shot_id    = data$.shot_id,
      club_type  = as.character(data$.club_type),
      shape      = as.character(data$shot_shape),
      x2         = data$`Carry Deviation Distance [m]`,
      y2         = data$`Carry Distance [m]`,
      launch_deg = data$`Launch Direction [deg]`
    ),
    function(shot_id, club_type, shape, x2, y2, launch_deg) {
      launch_rad <- launch_deg * pi / 180
      x1 <- sin(launch_rad) * y2 * 0.6
      y1 <- cos(launch_rad) * y2 * 0.6
      data.frame(
        .shot_id   = shot_id,
        .club_type = club_type,
        shot_shape = shape,
        bx = 2*(1-t_seq)*t_seq * x1 + t_seq^2 * x2,
        by = 2*(1-t_seq)*t_seq * y1 + t_seq^2 * y2
      )
    }
  )

  curve_df$.club_type <- factor(curve_df$.club_type, levels = club_levels_present)
  curve_df$shot_shape <- factor(curve_df$shot_shape, levels = c("Draw", "Straight", "Fade"))

  shape_colors <- c("Draw" = "#e06c00", "Straight" = "#2ca02c", "Fade" = "#5b5ea6")

  ggplot() +
    geom_vline(xintercept = 0, linetype = "dashed", color = "grey70", linewidth = 0.4) +
    geom_path(
      data = curve_df,
      aes(x = bx, y = by, group = .shot_id, color = shot_shape),
      alpha = 0.45, linewidth = 0.45
    ) +
    geom_point(
      data = data,
      aes(x = `Carry Deviation Distance [m]`, y = `Carry Distance [m]`, color = shot_shape),
      size = 1.5, alpha = 0.85
    ) +
    annotate("point", x = 0, y = 0, shape = 3, size = 3, color = "grey40") +
    scale_color_manual(values = shape_colors, name = "Shot shape") +
    facet_wrap(vars(.club_type), ncol = ncol, scales = "free_y") +
    theme_minimal(base_size = 11) +
    theme(
      plot.title       = element_text(face = "bold", size = 13),
      plot.subtitle    = element_text(color = "grey50", size = 10),
      panel.grid.minor = element_blank(),
      legend.position  = "bottom",
      strip.text       = element_text(face = "bold", size = 9)
    ) +
    labs(
      title    = title,
      subtitle = "Draw: Spin Axis < -5°  ·  Fade: Spin Axis > +5°  ·  Curve = quadratic Bézier from launch direction",
      x        = "Lateral deviation (m)  ←left  |  right→",
      y        = "Carry distance (m)"
    )
}


shot_sideview_facet <- function(
    data,
    show_roll = TRUE,
    bezier_n  = 60,
    ncol      = 4,
    title     = "Ball flight – side view"
) {
  club_levels_present <- intersect(club_order, unique(data$`Club Type`))

  data <- data %>%
    mutate(
      .shot_id   = row_number(),
      .club_type = factor(`Club Type`, levels = club_levels_present),
      shot_shape = factor(`Shot Shape`, levels = c("Draw", "Straight", "Fade"))
    )

  t_seq <- seq(0, 1, length.out = bezier_n)

  # Quadratic Bézier: P0=(0,0), P1 via launch angle + apex, P2=(carry,0)
  # y_P1 = 2*apex so apex at t=0.5 equals measured apex height
  # x_P1 = y_P1/tan(launch) so the initial tangent matches the launch angle
  curve_df <- pmap_dfr(
    list(
      shot_id    = data$.shot_id,
      club_type  = as.character(data$.club_type),
      shape      = as.character(data$shot_shape),
      carry      = data$`Carry Distance [m]`,
      apex       = data$`Apex Height [m]`,
      launch_deg = data$`Launch Angle [deg]`
    ),
    function(shot_id, club_type, shape, carry, apex, launch_deg) {
      launch_rad <- launch_deg * pi / 180
      y1 <- 2 * apex
      x1 <- if (launch_deg > 1) min(y1 / tan(launch_rad), carry * 0.85) else carry * 0.5
      data.frame(
        .shot_id   = shot_id,
        .club_type = club_type,
        shot_shape = shape,
        bx = 2*(1-t_seq)*t_seq * x1 + t_seq^2 * carry,
        by = 2*(1-t_seq)*t_seq * y1
      )
    }
  )

  curve_df$.club_type <- factor(curve_df$.club_type, levels = club_levels_present)
  curve_df$shot_shape <- factor(curve_df$shot_shape, levels = c("Draw", "Straight", "Fade"))

  roll_df <- data %>%
    filter(`Total Distance [m]` > `Carry Distance [m]`) %>%
    transmute(
      .shot_id   = .shot_id,
      .club_type = .club_type,
      shot_shape = shot_shape,
      x_start    = `Carry Distance [m]`,
      x_end      = `Total Distance [m]`
    )

  shape_colors <- c("Draw" = "#e06c00", "Straight" = "#2ca02c", "Fade" = "#5b5ea6")

  p <- ggplot() +
    geom_hline(yintercept = 0, color = "grey70", linewidth = 0.3) +
    geom_path(
      data = curve_df,
      aes(x = bx, y = by, group = .shot_id, color = shot_shape),
      alpha = 0.45, linewidth = 0.45
    ) +
    geom_point(
      data = data,
      aes(x = `Carry Distance [m]`, y = 0, color = shot_shape),
      size = 1.2, alpha = 0.7, shape = 16
    ) +
    annotate("point", x = 0, y = 0, shape = 3, size = 3, color = "grey40")

  if (show_roll && nrow(roll_df) > 0) {
    p <- p + geom_segment(
      data = roll_df,
      aes(x = x_start, xend = x_end, y = 0, yend = 0, color = shot_shape),
      linetype  = "dotted",
      alpha     = 0.6,
      linewidth = 0.7
    )
  }

  subtitle_parts <- c(
    "Orange = Draw  ·  Green = Straight  ·  Purple = Fade",
    if (show_roll) "Dotted tail = roll" else NULL
  )

  p +
    scale_color_manual(values = shape_colors, name = "Shot shape") +
    facet_wrap(vars(.club_type), ncol = ncol, scales = "free") +
    theme_minimal(base_size = 11) +
    theme(
      plot.title       = element_text(face = "bold", size = 13),
      plot.subtitle    = element_text(color = "grey50", size = 10),
      panel.grid.minor = element_blank(),
      legend.position  = "bottom",
      strip.text       = element_text(face = "bold", size = 9)
    ) +
    labs(
      title    = title,
      subtitle = paste(subtitle_parts, collapse = "  ·  "),
      x        = "Distance (m)",
      y        = "Height (m)"
    )
}


# ------------------------------
#              MAIN
# ------------------------------


# 1. Data stuff

# 1a. loading
setwd("C:/Users/michi/anaconda_projects/Golf-Analytics/")
dir.create("graphs", showWarnings = FALSE)
dir.create("tables", showWarnings = FALSE)

training <- read_excel(
  "data.xlsx",
  sheet = "Michiel",
  range = "A1:AF300"
)

benchmarkData <- read_excel(
  "data.xlsx",
  sheet = "Benchmark",
  range = "A1:R13"
)

club_order <- c("Driver", "3 Wood", "5 Wood", "7 Wood",
                "5 Iron", "6 Iron", "7 Iron", "8 Iron", "9 Iron",
                "Gap Wedge", "Pitching Wedge", "Sand Wedge", "Lob Wedge")


# 1b. cleaning

garminData <- as.data.frame(training) %>%
  filter(!if_all(everything(), is.na)) %>%
  arrange(factor(`Club Type`, levels = club_order))

garminData["Roll Distance [m]"] <- garminData$`Total Distance [m]` - garminData$`Carry Distance [m]`
garminData["Swing Tempo"]  <- garminData$`Backswing Time [sec]` / garminData$`Downswing Time [sec]`
garminData["Shot Shape"]  <- factor(
  case_when(
    garminData$`Spin Axis [deg]` < -5 ~ "Draw",
    garminData$`Spin Axis [deg]` >  5 ~ "Fade",
    TRUE                               ~ "Straight"
  ),
  levels = c("Draw", "Straight", "Fade")
)


irons = c("5 Iron", "6 Iron", "7 Iron", "8 Iron", "9 Iron")
ironData <- garminData %>%
  filter(`Club Type` %in% irons)

wedges <- c("Gap Wedge", "Lob Wedge", "Pitching Wedge", "Sand Wedge")
wedgeData <- garminData %>%
  filter(`Club Type` %in% wedges)

woods <- c("Driver", "3 Wood", "5 Wood", "7 Wood")
woodData <- garminData %>%
  filter(`Club Type` %in% woods)


# 1. BOXPLOT

# 1a. Distances vs Benchamrk

p1 <- make_boxplot(garminData, "Club Type", "Carry Distance [m]",
                   title = "Carry distance by club", y_label = "Meters", benchmark = benchmarkData)
p2 <- make_boxplot(garminData, "Club Type", "Total Distance [m]",
                   title = "Total distance by club", y_label = "Meters")
p1 / p2

ggsave("graphs/boxplot_distance_by_club.png", plot = p1 / p2, width = 16, height = 10)

# 1b. 2D offline mode (carry distance vs lateral miss)

p_offline <- make_boxplot(
  data        = ironData,
  x_var       = "Club Type",
  y_var       = "Carry Distance [m]",
  offline_var = "Carry Deviation Distance [m]",
  jitter_mode = "offline",
  title       = "Carry distance & lateral miss – Irons",
  y_label     = "Carry distance (m)",
  x_label     = "Club  (\u2190 left miss  |  right miss \u2192)"
)

p_offline
ggsave("graphs/boxplot_offline_irons.png", p_offline, width = 14, height = 7)

# 2. Tables

# 2a. Mean values versus Benchmark

meansPivot    <- compute_means_table(garminData,   "Club Type")
benchmarkMeans <- compute_means_table(benchmarkData, "Club Type")

metric_labels <- c(
  "Club Speed [km/h]"              = "Club Speed",
  "Attack Angle [deg]"             = "Attack Angle",
  "Ball Speed [km/h]"              = "Ball Speed",
  "Smash Factor"                   = "Smash Factor",
  "Launch Angle [deg]"             = "Launch Angle",
  "Spin Rate [rpm]"                = "Spin Rate",
  "Apex Height [m]"                = "Apex Height",
  "Carry Distance [m]"             = "Carry Dist",
  "Swing Tempo"                    = "Swing Tempo",
  "Spin Axis [deg]"                = "Spin Axis",
  "Club Path [deg]"                = "Club Path",
  "Club Face [deg]"                = "Club Face",
  "Face to Path [deg]"             = "Face to Path",
  "Launch Direction [deg]"         = "Launch Dir",
  "Sidespin [rpm]"                 = "Sidespin",
  "Carry Deviation Angle [deg]"    = "Carry Dev Angle",
  "Carry Deviation Distance [m]"   = "Carry Dev Dist"
)

# 2b. Heatmap

comparison_means <- compare_to_benchmark(
  data          = meansPivot,
  benchmark     = benchmarkMeans,
  grouper       = "Club Type",
  mode          = "hybrid",
  input         = "mean",
  metric_labels = metric_labels
)

p_heatmap <- plot_benchmark_heatmap(
  comparison_means,
  grouper = "Club Type",
  title   = "My performance vs benchmark"
)

p_heatmap

ggsave("graphs/heatmap_vs_benchmark.png", p_heatmap, width = 12, height = 8)


# 2c. raw values against benchmark

comparison_raw <- compare_to_benchmark(
  data          = garminData,
  benchmark     = benchmarkData,
  grouper       = "Club Type",
  mode          = "hybrid",
  input         = "raw",
  metric_labels = metric_labels
)

benchcomap <- table_benchmark_comparison(comparison_raw, grouper = "Club Type", mode = "absolute")
write_xlsx(benchcomap, "tables/benchmark_comparison_raw.xlsx")




# 3. Graphs

# 3a. Ball flight
p_birdview <- shot_birdview_facet(wedgeData)
p_sideview <- shot_sideview_facet(wedgeData, show_roll = FALSE)

p_birdview
p_sideview

ggsave("graphs/birdview_wedges.png",  p_birdview, width = 14, height = 10)
ggsave("graphs/sideview_wedges.png",  p_sideview, width = 14, height = 10)





