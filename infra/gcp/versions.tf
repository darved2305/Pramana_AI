# Pramana on Google Cloud, asia-south1 (ADR 0025, PRODUCTION.md §13.3).
#
# Nothing here has been applied. CI runs `terraform fmt -check` and `terraform validate` only.
# `terraform apply` needs the user's explicit approval of the plan output and its fixed costs.

terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
  }

  # State lives in a bucket created by hand once per project (see README.md). Supplied at init:
  #   terraform init -backend-config="bucket=<project>-tfstate" -backend-config="prefix=<env>"
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}
