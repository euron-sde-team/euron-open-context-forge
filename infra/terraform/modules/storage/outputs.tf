output "bucket_name" {
  description = "Payloads bucket name (PAYLOADS_BUCKET)."
  value       = aws_s3_bucket.payloads.bucket
}

output "bucket_arn" {
  description = "Payloads bucket ARN, for IAM policies."
  value       = aws_s3_bucket.payloads.arn
}
