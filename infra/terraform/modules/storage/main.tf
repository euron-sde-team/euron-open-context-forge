# One private bucket for payloads too large to keep in Postgres: background job inputs
# and results, benchmark reports, and run content when STORE_CONTENT is on. Rows hold
# only the object key. Everything here is transient working data, so it expires on a
# fixed schedule instead of being versioned and kept.
resource "aws_s3_bucket" "payloads" {
  #checkov:skip=CKV_AWS_144:Cross-region replication is pointless for transient, expiring job payloads.
  #checkov:skip=CKV_AWS_18:Access logging targets a separate log bucket an operator chooses; CloudTrail data events cover object access (docs/guides/operations.md).
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications.
  #checkov:skip=CKV_AWS_21:Payloads are transient and expire after expiration_days; versioning would only keep expired copies.
  bucket        = "${var.name_prefix}-payloads"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "payloads" {
  bucket                  = aws_s3_bucket.payloads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "payloads" {
  bucket = aws_s3_bucket.payloads.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "payloads" {
  bucket = aws_s3_bucket.payloads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != null ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "payloads" {
  bucket = aws_s3_bucket.payloads.id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  # Job payloads and results, and stored run content (STORE_CONTENT), carry conversation
  # content: keep them only as long as a client plausibly needs them. The API answers 410
  # content_expired for an object the lifecycle removed.
  dynamic "rule" {
    for_each = toset(["jobs/", "runs/"])
    content {
      id     = "expire-${trim(rule.value, "/")}"
      status = "Enabled"
      filter {
        prefix = rule.value
      }
      expiration {
        days = var.expiration_days
      }
    }
  }

  # Benchmark reports hold synthetic data only; keep them longer for comparison.
  rule {
    id     = "expire-benchmarks"
    status = "Enabled"
    filter {
      prefix = "benchmarks/"
    }
    expiration {
      days = var.report_expiration_days
    }
  }
}

# Only needed when a browser fetches objects with JavaScript; a presigned download link
# opened as a navigation needs none, so the default is no CORS at all.
resource "aws_s3_bucket_cors_configuration" "payloads" {
  count  = length(var.cors_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.payloads.id
  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = var.cors_origins
    allowed_headers = ["*"]
    expose_headers  = ["Content-Disposition", "Content-Length", "ETag"]
    max_age_seconds = 3600
  }
}

data "aws_iam_policy_document" "payloads" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.payloads.arn, "${aws_s3_bucket.payloads.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "payloads" {
  count      = var.enforce_tls ? 1 : 0
  bucket     = aws_s3_bucket.payloads.id
  policy     = data.aws_iam_policy_document.payloads.json
  depends_on = [aws_s3_bucket_public_access_block.payloads]
}
