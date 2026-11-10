# Cloud SQL for PostgreSQL: regional HA, point-in-time recovery, private IP only (PRODUCTION.md §13.3, §13.8).

resource "google_compute_network" "vpc" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "run" {
  name                     = "${local.name}-run"
  network                  = google_compute_network.vpc.id
  region                   = var.region
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_global_address" "sql_range" {
  name          = "${local.name}-sql-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "sql" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.sql_range.name]
}

resource "google_sql_database_instance" "pg" {
  name                = local.name
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = true
  depends_on          = [google_service_networking_connection.sql]

  settings {
    tier              = var.db_tier
    availability_type = "REGIONAL"
    edition           = "ENTERPRISE"
    disk_autoresize   = true
    disk_type         = "PD_SSD"
    user_labels       = local.labels

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "20:30" # 02:00 IST
      location                       = var.backup_region
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
      }
    }

    maintenance_window {
      day  = 7 # Sunday
      hour = 21
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    insights_config {
      query_insights_enabled = true
    }
  }
}

resource "google_sql_database" "pramana" {
  name     = "pramana"
  instance = google_sql_database_instance.pg.name
}

# Runtime services connect as IAM users mapped to the non-superuser pramana_app role (ADR 0015).
resource "google_sql_user" "iam" {
  for_each = toset(["api", "media", "worker", "migrate"])
  name     = trimsuffix(google_service_account.svc[each.key].email, ".gserviceaccount.com")
  instance = google_sql_database_instance.pg.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_project_iam_member" "sql_client" {
  for_each = toset(["api", "media", "worker", "migrate"])
  project  = var.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${google_service_account.svc[each.key].email}"
}

resource "google_project_iam_member" "sql_instance_user" {
  for_each = toset(["api", "media", "worker", "migrate"])
  project  = var.project_id
  role     = "roles/cloudsql.instanceUser"
  member   = "serviceAccount:${google_service_account.svc[each.key].email}"
}
