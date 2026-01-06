variable "project" {
  type        = string
  description = "리소스 이름 prefix"
  default     = "dubbi-e2e"
}

variable "aws_region" {
  type        = string
  description = "AWS region"
  default     = "ap-northeast-3"
}

variable "vpc_id" {
  type        = string
  description = "기존 VPC ID"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "ALB용 public subnet IDs (최소 2개 권장)"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "ECS/RDS/Redis/EFS용 private subnet IDs (최소 2개 권장)"
}

variable "api_image" {
  type        = string
  description = "API 컨테이너 이미지 (예: ECR URI)"
}

variable "worker_image" {
  type        = string
  description = "Worker(Celery) 컨테이너 이미지 (예: ECR URI)"
}

variable "api_desired_count" {
  type        = number
  default     = 1
}

variable "worker_desired_count" {
  type        = number
  default     = 1
}

variable "api_cpu" {
  type        = number
  default     = 512
  description = "Fargate CPU units (256/512/1024...)"
}

variable "api_memory" {
  type        = number
  default     = 1024
  description = "Fargate memory (MiB)"
}

variable "worker_cpu" {
  type        = number
  default     = 1024
}

variable "worker_memory" {
  type        = number
  default     = 2048
}

variable "api_container_port" {
  type        = number
  default     = 8000
}

variable "playwright_headless" {
  type        = bool
  default     = true
  description = "서버 환경 headless 기본값"
}

variable "jwt_secret_key" {
  type        = string
  description = "FastAPI JWT secret (운영에서는 Secrets Manager 권장)"
  sensitive   = true
}

variable "public_base_url" {
  type        = string
  description = "서비스 외부 Base URL (웹훅/링크용)"
  default     = ""
}

variable "db_instance_class" {
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage_gb" {
  type        = number
  default     = 20
}

variable "db_username" {
  type        = string
  default     = "postgres"
}

variable "db_password" {
  type        = string
  sensitive   = true
}

variable "db_name" {
  type        = string
  default     = "e2e"
}

variable "redis_node_type" {
  type        = string
  default     = "cache.t4g.micro"
}

variable "redis_engine_version" {
  type        = string
  default     = "7.0"
}

variable "efs_lifecycle_to_ia_days" {
  type        = number
  default     = 7
  description = "EFS lifecycle: N일 후 IA로 이동"
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "enable_frontend_s3" {
  type        = bool
  default     = false
  description = "frontend 정적 배포(S3/CloudFront) 리소스 생성 여부"
}

variable "frontend_domain_name" {
  type        = string
  default     = ""
  description = "CloudFront에 붙일 도메인(선택). Route53/ACM은 이 TF에서 자동 구성하지 않음."
}


