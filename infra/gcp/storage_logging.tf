# Object storage (question audio, exports, daily hash anchors) and log retention in India.

resource "google_storage_bucket" "audio" {
  name                        = "${var.project_id}-${local.name}-audio"
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  # Question audio is content-addressed and immutable; unused objects go after 90 days (§3.7).
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 90
      age                        = 90
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "anchors" {
  name                        = "${var.project_id}-${local.name}-anchors"
  location                    = upper(var.region)
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  # Daily event-log head hashes and exports cannot be deleted for a year (§3.5, §13.8).
  retention_policy {
    retention_period = 31536000
  }
}

resource "google_storage_bucket_iam_member" "core_audio" {
  for_each = toset(["api", "media", "worker"])
  bucket   = google_storage_bucket.audio.name
  role     = "roles/storage.objectUser"
  member   = "serviceAccount:${google_service_account.svc[each.key].email}"
}

resource "google_storage_bucket_iam_member" "worker_anchors" {
  bucket = google_storage_bucket.anchors.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.svc["worker"].email}"
}

# CERT-In: ICT logs kept in India for at least 180 days.
resource "google_logging_project_bucket_config" "india" {
  project        = var.project_id
  location       = var.region
  bucket_id      = "${local.name}-logs"
  retention_days = var.log_retention_days
  depends_on     = [google_project_service.apis]
}

resource "google_logging_project_sink" "india" {
  name                   = "${local.name}-to-india"
  destination            = "logging.googleapis.com/${google_logging_project_bucket_config.india.id}"
  filter                 = ""
  unique_writer_identity = true
}
