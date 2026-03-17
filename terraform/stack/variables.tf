variable "availability_domain" {
  default = "bxtG:AP-OSAKA-1-AD-1"
}

variable "region" {
  description = "OCI Region (Resource Managerが自動設定)"
  type        = string
  default     = "ap-osaka-1"
}

variable "compartment_ocid" {
  default = ""
}

variable "adb_name" {
  default = "AIDOCADB"
}

variable "adb_display_name" {
  default = ""
}

variable "adb_password" {
  default = ""
}

variable "license_model" {
  default = ""
}

variable "adb_use_private_subnet" {
  description = "Whether to use a private subnet for Autonomous Database"
  type        = bool
  default     = false
}

variable "adb_subnet_id" {
  description = "Private subnet OCID for Autonomous Database (used when private subnet is enabled)"
  type        = string
  default     = ""
}

variable "instance_display_name" {
  default = "DENPYO_INSTANCE"
}

variable "instance_shape" {
  default = "VM.Standard.E4.Flex"
}

variable "instance_flex_shape_ocpus" {
  default = 2
}

variable "instance_flex_shape_memory" {
  default = 16
}

variable "instance_boot_volume_size" {
  default = 100
}

variable "instance_boot_volume_vpus" {
  default = 20
}

variable "instance_image_source_id" {
  default = "ocid1.image.oc1.ap-osaka-1.aaaaaaaa7sbmd5q54w466eojxqwqfvvp554awzjpt2behuwsiefrxnwomq5a"
}

variable "compute_subnet_id" {
  description = "Subnet OCID used for Compute instance"
  type        = string
  default     = ""
}

variable "ssh_authorized_keys" {
  default = ""
}

variable "oci_bucket_name" {
  default     = "denpyo-toroku"
  description = "OCI Object Storage bucket name for document storage"
}
