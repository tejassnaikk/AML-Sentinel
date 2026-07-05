terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project   = "aml-sentinel"
      managed_by = "terraform"
    }
  }
}

resource "random_id" "suffix" {
  byte_length = 3
}

locals {
  layers = ["bronze", "silver", "gold", "scripts"]
}

resource "aws_s3_bucket" "medallion" {
  for_each = toset(local.layers)
  bucket   = "aml-sentinel-${each.key}-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "medallion" {
  for_each                = aws_s3_bucket.medallion
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_sns_topic" "alerts" {
  name = "aml-sentinel-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

output "buckets" {
  value = { for k, b in aws_s3_bucket.medallion : k => b.bucket }
}

output "sns_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
