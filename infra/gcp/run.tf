# Five Cloud Run services from two images, plus the migration job (ADR 0025, PRODUCTION.md §3.2).

locals {
  # Settings per service. Instance-based billing (cpu_idle = false) for anything that holds sockets or
  # runs background work; that mode needs at least 512 MiB (checked 2026-11-07).
  services = {
    api    = { image = local.py_image, args = ["core"], port = 8080, cpu_idle = false, timeout = "3600s", concurrency = 200, memory = "1Gi", ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" }
    media  = { image = local.py_image, args = ["core"], port = 8080, cpu_idle = false, timeout = "3600s", concurrency = 50, memory = "1Gi", ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" }
    worker = { image = local.py_image, args = ["core"], port = 8080, cpu_idle = false, timeout = "300s", concurrency = 10, memory = "1Gi", ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY" }
    sim    = { image = local.py_image, args = ["sim"], port = 8080, cpu_idle = true, timeout = "300s", concurrency = 80, memory = "512Mi", ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" }
  }
}

resource "google_cloud_run_v2_service" "svc" {
  for_each            = local.services
  name                = "${local.name}-${each.key}"
  location            = var.region
  ingress             = each.value.ingress
  deletion_protection = var.environment == "production"
  labels              = local.labels
  depends_on          = [google_project_service.apis]

  template {
    service_account                  = google_service_account.svc[each.key].email
    timeout                          = each.value.timeout
    max_instance_request_concurrency = each.value.concurrency

    scaling {
      min_instance_count = var.min_instances[each.key]
      max_instance_count = 10
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY"
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.run.id
      }
    }

    containers {
      image = each.value.image
      args  = each.value.args

      ports {
        container_port = each.value.port
      }

      resources {
        cpu_idle = each.value.cpu_idle
        limits = {
          cpu    = "1"
          memory = each.value.memory
        }
      }

      env {
        name  = "PRAMANA_ENV"
        value = var.environment
      }
      env {
        name  = "PRAMANA_PROCESS"
        value = each.key
      }

      dynamic "env" {
        for_each = contains(["api", "media", "worker"], each.key) ? {
          PRAMANA_MODE = var.environment == "production" ? "production" : "demo"
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = contains(["api", "media", "worker"], each.key) && var.domain != "" ? {
          OIDC_REDIRECT_URL = "https://${var.domain}/api/core/v1/auth/google/callback"
          CORS_ORIGINS      = jsonencode(["https://${var.domain}"])
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = contains(["api", "media", "worker"], each.key) ? toset(["database-url", "gnani-api-key", "participant-signing-key", "sim-operator-key", "google-oauth-client-id", "google-oauth-client-secret"]) : toset([])
        content {
          name = upper(replace(env.value, "-", "_"))
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 2
        period_seconds        = 5
        failure_threshold     = 12
      }
    }
  }

  lifecycle {
    # Image tags are rolled by the deploy pipeline (canary, then 100%), not by Terraform.
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

# The web service is separate so it can read the api and sim addresses at runtime (src/proxy.ts).
resource "google_cloud_run_v2_service" "web" {
  name                = "${local.name}-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = var.environment == "production"
  labels              = local.labels

  template {
    service_account                  = google_service_account.svc["web"].email
    timeout                          = "60s"
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = var.min_instances["web"]
      max_instance_count = 10
    }

    containers {
      image = local.web_img
      ports {
        container_port = 3000
      }
      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      env {
        name  = "PRAMANA_CORE_URL"
        value = google_cloud_run_v2_service.svc["api"].uri
      }
      env {
        name  = "PRAMANA_SIM_URL"
        value = google_cloud_run_v2_service.svc["sim"].uri
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

resource "google_cloud_run_v2_job" "migrate" {
  name                = "${local.name}-migrate"
  location            = var.region
  deletion_protection = false
  labels              = local.labels

  template {
    template {
      service_account = google_service_account.svc["migrate"].email
      max_retries     = 0
      timeout         = "600s"
      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.run.id
        }
      }
      containers {
        image = local.py_image
        args  = ["migrate"]
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.s["migration-database-url"].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
}

# The web service calls api and sim server-side through its proxy; only it may invoke them directly.
resource "google_cloud_run_v2_service_iam_member" "web_invokes" {
  for_each = toset(["api", "sim"])
  name     = google_cloud_run_v2_service.svc[each.key].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.svc["web"].email}"
}

# The load balancer fronts public traffic; Cloud Run's own IAM check is replaced by the core's
# session authentication on those services.
resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = toset(["web", "api", "media", "sim"])
  name     = each.key == "web" ? google_cloud_run_v2_service.web.name : google_cloud_run_v2_service.svc[each.key].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
