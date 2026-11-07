variable "project_id" {
  description = "Google Cloud project id. Never committed; pass with -var or a local tfvars file."
  type        = string
}

variable "environment" {
  description = "staging or production."
  type        = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "region" {
  description = "Primary region (Mumbai)."
  type        = string
  default     = "asia-south1"
}

variable "backup_region" {
  description = "Region for cross-region backup copies (Delhi)."
  type        = string
  default     = "asia-south2"
}

variable "domain" {
  description = "Public domain for the managed certificate. Empty means no certificate yet (domain to be decided)."
  type        = string
  default     = ""
}

variable "image_tag" {
  description = "Git SHA of the images to deploy (one image per SHA, built once)."
  type        = string
  default     = "latest"
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to deploy through workload identity federation."
  type        = string
  default     = "darved2305/pramana"
}

variable "db_tier" {
  description = "Cloud SQL machine tier. Starting size; tune from load tests."
  type        = string
  default     = "db-custom-2-7680"
}

variable "min_instances" {
  description = "Minimum instances per Cloud Run service."
  type        = map(number)
  default = {
    web    = 0
    api    = 1
    media  = 1
    worker = 1
    sim    = 0
  }
}

variable "log_retention_days" {
  description = "CERT-In requires ICT logs kept in India for a rolling 180 days."
  type        = number
  default     = 365
  validation {
    condition     = var.log_retention_days >= 180
    error_message = "Log retention must be at least 180 days (CERT-In)."
  }
}
