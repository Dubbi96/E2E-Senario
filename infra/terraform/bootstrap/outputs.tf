output "github_actions_role_arn" {
  value       = aws_iam_role.github_actions.arn
  description = "GitHub Actions가 Assume할 Role ARN (AWS_ROLE_TO_ASSUME)"
}

output "tfstate_bucket" {
  value       = aws_s3_bucket.tfstate.bucket
  description = "Terraform state bucket name"
}

output "tfstate_lock_table" {
  value       = aws_dynamodb_table.lock.name
  description = "Terraform state lock DynamoDB table name"
}

output "ecr_repo_api_url" {
  value       = aws_ecr_repository.api.repository_url
  description = "ECR repo URL for API"
}

output "ecr_repo_worker_url" {
  value       = aws_ecr_repository.worker.repository_url
  description = "ECR repo URL for worker"
}


