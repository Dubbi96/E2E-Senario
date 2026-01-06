output "alb_dns_name" {
  value       = aws_lb.api.dns_name
  description = "API ALB DNS"
}

output "api_base_url" {
  value       = "http://${aws_lb.api.dns_name}"
  description = "API base URL (http, TLS는 별도 구성)"
}

output "efs_id" {
  value       = aws_efs_file_system.data.id
  description = "EFS file system id"
}

output "rds_endpoint" {
  value       = aws_db_instance.postgres.address
  description = "RDS endpoint"
}

output "redis_endpoint" {
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
  description = "Redis endpoint"
}

output "frontend_bucket_name" {
  value       = var.enable_frontend_s3 ? aws_s3_bucket.frontend[0].bucket : ""
  description = "frontend bucket name (if enabled)"
}


