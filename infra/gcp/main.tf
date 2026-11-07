locals {
  name   = "pramana-${var.environment}"
  labels = { app = "pramana", environment = var.environment, managed_by = "terraform" }

  registry = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
  py_image = "${local.registry}/pramana-py:${var.image_tag}"
  web_img  = "${local.registry}/pramana-web:${var.image_tag}"

  # Secrets created empty here; values are added by hand in Secret Manager, never in Terraform state.
  secret_names = [
    "database-url",
    "migration-database-url",
    "gnani-api-key",
    "participant-signing-key",
    "sim-operator-key",
    "sim-oracle-key",
    "google-oauth-client-id",
    "google-oauth-client-secret",
    "email-api-key",
  ]
  runtime_secret_names = setsubtract(toset(local.secret_names), toset([
    "sim-oracle-key", "migration-database-url",
  ]))
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudkms.googleapis.com",
    "artifactregistry.googleapis.com",
    "compute.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Images ------------------------------------------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "pramana"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.apis]
}

# --- Service accounts (one per process, least privilege) -----------------------------------------

resource "google_service_account" "svc" {
  for_each     = toset(["web", "api", "media", "worker", "sim", "migrate"])
  account_id   = "${local.name}-${each.key}"
  display_name = "Pramana ${var.environment} ${each.key}"
}

# --- Secrets -------------------------------------------------------------------------------------

resource "google_secret_manager_secret" "s" {
  for_each  = toset(local.secret_names)
  secret_id = "${local.name}-${each.key}"
  labels    = local.labels
  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "core_reads" {
  for_each = {
    for pair in setproduct(["api", "media", "worker"], local.runtime_secret_names) :
    "${pair[0]}-${pair[1]}" => { sa = pair[0], secret = pair[1] }
  }
  secret_id = google_secret_manager_secret.s[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.svc[each.value.sa].email}"
}

resource "google_secret_manager_secret_iam_member" "migrator_reads" {
  secret_id = google_secret_manager_secret.s["migration-database-url"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.svc["migrate"].email}"
}

resource "google_secret_manager_secret_iam_member" "sim_reads" {
  for_each  = toset(["sim-operator-key", "sim-oracle-key"])
  secret_id = google_secret_manager_secret.s[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.svc["sim"].email}"
}

# --- KMS: envelope encryption of personal data (ADR 0022) -----------------------------------------

resource "google_kms_key_ring" "ring" {
  name       = local.name
  location   = var.region
  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key" "personal_data" {
  name            = "personal-data"
  key_ring        = google_kms_key_ring.ring.id
  rotation_period = "7776000s" # 90 days
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "core_uses_key" {
  for_each      = toset(["api", "media", "worker"])
  crypto_key_id = google_kms_crypto_key.personal_data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.svc[each.key].email}"
}
