# Get OCI Object Storage namespace
data "oci_objectstorage_namespace" "tenant_namespace" {
  compartment_id = var.compartment_ocid
}

data "oci_core_subnet" "selected_compute_subnet" {
  subnet_id = var.compute_subnet_id
}

data "template_file" "cloud_init_file" {
  template = file("./cloud_init/bootstrap.template.yaml")

  vars = {
    comp_id       = var.compartment_ocid
    bucket        = var.oci_bucket_name
    db_conn       = base64gzip("admin/${var.adb_password}@${lower(var.adb_name)}_high")
    db_pass       = var.adb_password
    adb_pass      = var.adb_password
    db_dsn        = "${lower(var.adb_name)}_high"
    adb_name      = var.adb_name
    adb_ocid      = oci_database_autonomous_database.generated_database_autonomous_database.id
    wallet        = data.external.wallet_files.result.wallet_content
    oci_region    = var.region
    oci_namespace = data.oci_objectstorage_namespace.tenant_namespace.namespace
    compute_subnet_is_private = data.oci_core_subnet.selected_compute_subnet.prohibit_public_ip_on_vnic
  }
}


data "template_cloudinit_config" "cloud_init" {
  gzip          = true
  base64_encode = true

  part {
    filename     = "bootstrap.yaml"
    content_type = "text/cloud-config"
    content      = data.template_file.cloud_init_file.rendered
  }
}
