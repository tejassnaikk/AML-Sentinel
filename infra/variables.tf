variable "region" {
  default = "us-east-1"
}

variable "alert_email" {
  description = "Email for SNS pipeline alerts"
  type        = string
}
