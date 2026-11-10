# One HTTPS origin: the load balancer routes paths to services (PRODUCTION.md §3.3, §13.3).
#   /             -> web
#   /api/core/*   -> api   (prefix stripped, so the core sees its own paths)
#   /api/sim/*    -> sim   (prefix stripped)
#   /media/*      -> media (per-question WebSockets)
#   /telephony/*  -> media (phone bridge, R3)

resource "google_compute_region_network_endpoint_group" "neg" {
  for_each              = toset(["web", "api", "media", "sim"])
  name                  = "${local.name}-${each.key}"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = each.key == "web" ? google_cloud_run_v2_service.web.name : google_cloud_run_v2_service.svc[each.key].name
  }
}

resource "google_compute_security_policy" "edge" {
  name = "${local.name}-edge"

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "default allow"
  }

  # Sign-in endpoints: per-IP rate limit (PRODUCTION.md §3.9).
  rule {
    action   = "throttle"
    priority = 1000
    match {
      expr {
        expression = "request.path.startsWith('/api/core/v1/auth/')"
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 30
        interval_sec = 60
      }
    }
    description = "rate limit sign-in"
  }
}

resource "google_compute_backend_service" "be" {
  for_each              = google_compute_region_network_endpoint_group.neg
  name                  = "${local.name}-${each.key}"
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.edge.id
  backend {
    group = each.value.id
  }
  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

resource "google_compute_url_map" "edge" {
  name            = local.name
  default_service = google_compute_backend_service.be["web"].id

  host_rule {
    hosts        = ["*"]
    path_matcher = "paths"
  }

  path_matcher {
    name            = "paths"
    default_service = google_compute_backend_service.be["web"].id

    route_rules {
      priority = 1
      match_rules {
        prefix_match = "/api/core/"
      }
      service = google_compute_backend_service.be["api"].id
      route_action {
        url_rewrite {
          path_prefix_rewrite = "/"
        }
      }
    }

    route_rules {
      priority = 2
      match_rules {
        prefix_match = "/api/sim/"
      }
      service = google_compute_backend_service.be["sim"].id
      route_action {
        url_rewrite {
          path_prefix_rewrite = "/"
        }
      }
    }

    route_rules {
      priority = 3
      match_rules {
        prefix_match = "/media/"
      }
      service = google_compute_backend_service.be["media"].id
    }

    route_rules {
      priority = 4
      match_rules {
        prefix_match = "/telephony/"
      }
      service = google_compute_backend_service.be["media"].id
    }
  }
}

resource "google_compute_global_address" "edge" {
  name = local.name
}

resource "google_compute_managed_ssl_certificate" "edge" {
  count = var.domain == "" ? 0 : 1
  name  = local.name
  managed {
    domains = [var.domain]
  }
}

resource "google_compute_target_https_proxy" "edge" {
  count            = var.domain == "" ? 0 : 1
  name             = local.name
  url_map          = google_compute_url_map.edge.id
  ssl_certificates = [google_compute_managed_ssl_certificate.edge[0].id]
}

resource "google_compute_global_forwarding_rule" "https" {
  count                 = var.domain == "" ? 0 : 1
  name                  = "${local.name}-https"
  target                = google_compute_target_https_proxy.edge[0].id
  ip_address            = google_compute_global_address.edge.id
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
