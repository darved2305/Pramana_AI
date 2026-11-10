output "edge_ip" {
  description = "Point the domain's A record here once a domain is chosen."
  value       = google_compute_global_address.edge.address
}

output "image_registry" {
  value = local.registry
}

output "database_instance" {
  value = google_sql_database_instance.pg.connection_name
}

output "workload_identity_provider" {
  description = "For google-github-actions/auth in the deploy workflow."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  value = google_service_account.deployer.email
}
