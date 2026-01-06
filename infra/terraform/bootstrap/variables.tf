variable "aws_region" {
  type        = string
  default     = "ap-northeast-3"
  description = "AWS region"
}

variable "project" {
  type        = string
  default     = "dubbi-e2e"
  description = "리소스 prefix"
}

variable "github_owner" {
  type        = string
  default     = "Dubbi96"
}

variable "github_repo" {
  type        = string
  default     = "E2E-Senario"
}

variable "tfstate_bucket_name" {
  type        = string
  description = "Terraform state S3 bucket name (전역 유니크 필요)"
}

variable "tfstate_dynamodb_table_name" {
  type        = string
  default     = "terraform-locks"
}

variable "ecr_repo_api" {
  type        = string
  default     = "dubbi-e2e-api"
}

variable "ecr_repo_worker" {
  type        = string
  default     = "dubbi-e2e-worker"
}

variable "ecr_keep_last_images" {
  type        = number
  default     = 50
  description = "ECR lifecycle: 최신 N개만 유지"
}

variable "tags" {
  type    = map(string)
  default = {}
}


