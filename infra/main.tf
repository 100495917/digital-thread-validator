terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Credentials come from the environment (AWS_ACCESS_KEY_ID,
  # AWS_SECRET_ACCESS_KEY, AWS_PROFILE, or an instance role). Never hardcode
  # them in configuration.
}

variable "aws_region" {
  description = "AWS region for the artifact bucket."
  type        = string
  default     = "eu-central-1"
}

variable "bucket_name" {
  description = "Globally unique name for the pipeline artifact bucket."
  type        = string
  default     = "digital-thread-validator-artifacts"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = var.bucket_name

  tags = {
    Project     = "digital-thread-validator"
    Environment = "shared"
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_logging" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  target_bucket = aws_s3_bucket.artifacts.id
  target_prefix = "access-logs/"
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.artifacts.arn,
          "${aws_s3_bucket.artifacts.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })
}
