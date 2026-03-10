locals {
  instance_public_ip = try(trimspace(oci_core_instance.generated_oci_core_instance.public_ip), "")
  instance_access_ip = local.instance_public_ip != "" ? local.instance_public_ip : oci_core_instance.generated_oci_core_instance.private_ip
}

output "autonomous_data_warehouse_admin_password" {
  #   value = random_string.autonomous_data_warehouse_admin_password.result
  value = var.adb_password
}

output "autonomous_data_warehouse_ocid" {
  description = "Autonomous Database OCID"
  value       = oci_database_autonomous_database.generated_database_autonomous_database.id
}

output "adb_ocid" {
  description = "Autonomous Database OCID"
  value       = oci_database_autonomous_database.generated_database_autonomous_database.id
}

output "autonomous_data_warehouse_high_connection_string" {
  value = lookup(
    oci_database_autonomous_database.generated_database_autonomous_database.connection_strings[0].all_connection_strings,
    "HIGH",
    "unavailable",
  )
}

output "ssh_to_instance" {
  description = "convenient command to ssh to the instance"
  value       = "ssh -o ServerAliveInterval=10 ubuntu@${local.instance_access_ip}"
}

output "application_url" {
  description = "URL to access the Denpyo Toroku application"
  value       = "http://${local.instance_access_ip}"
}

output "document_bucket_name" {
  description = "Document storage bucket name"
  value       = var.oci_bucket_name
}
