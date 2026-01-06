locals {
  enable_frontend = var.enable_frontend_s3
}

# Optional: CloudFront는 운영에서 강력 추천이지만, 인증서/도메인/Route53까지 자동화하면 복잡도가 크게 증가합니다.
# 여기서는 "S3 업로드 + (선택) CloudFront" 중 S3만으로도 동작하도록 구성합니다.

resource "aws_s3_bucket_website_configuration" "frontend" {
  count  = local.enable_frontend ? 1 : 0
  bucket = aws_s3_bucket.frontend[0].id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

resource "aws_s3_bucket_versioning" "frontend" {
  count  = local.enable_frontend ? 1 : 0
  bucket = aws_s3_bucket.frontend[0].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  count  = local.enable_frontend ? 1 : 0
  bucket = aws_s3_bucket.frontend[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 비용 최적화를 위한 수명주기(오래된 빌드 객체 정리)
resource "aws_s3_bucket_lifecycle_configuration" "frontend" {
  count  = local.enable_frontend ? 1 : 0
  bucket = aws_s3_bucket.frontend[0].id

  rule {
    id     = "cleanup-old-builds"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}


