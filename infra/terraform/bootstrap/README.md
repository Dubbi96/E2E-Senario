# Bootstrap (1회) — tfstate + ECR + GitHub OIDC Deploy Role

이 디렉터리는 **최초 1회만** 적용하는 Terraform입니다.

생성하는 것:
- Terraform state용 **S3 bucket** + **DynamoDB lock table**
- Docker 이미지 저장용 **ECR repos** (`dubbi-e2e-api`, `dubbi-e2e-worker`)
- GitHub Actions가 Assume할 **OIDC Provider + IAM Role**

> 이후 배포는 main 브랜치 머지/푸시로 GitHub Actions가 수행합니다.

---

## 0) 전제
- AWS Region: **ap-northeast-3**
- GitHub repo: **Dubbi96/E2E-Senario**

---

## 1) 실행(로컬 1회)
AWS 관리자 권한(또는 동등 권한)이 있는 자격증명으로 실행하세요.

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply
```

---

## 2) 출력값을 GitHub Secrets에 등록
apply 후 출력되는 값을 GitHub repo secrets에 넣습니다.

필수 Secrets:
- `AWS_REGION`: `ap-northeast-3`
- `AWS_ROLE_TO_ASSUME`: (output `github_actions_role_arn`)
- `TFSTATE_BUCKET`: (output `tfstate_bucket`)
- `TFSTATE_DYNAMODB_TABLE`: (output `tfstate_lock_table`)
- `TFSTATE_KEY`: 예) `dubbi-e2e/prod/terraform.tfstate`
- `ECR_REPO_API`: `dubbi-e2e-api`
- `ECR_REPO_WORKER`: `dubbi-e2e-worker`

그리고 배포 Terraform에 필요한 값:
- `TF_PROJECT`: 예) `dubbi-e2e`
- `TF_VPC_ID`, `TF_PUBLIC_SUBNET_IDS`, `TF_PRIVATE_SUBNET_IDS`
- `TF_JWT_SECRET_KEY`, `TF_DB_PASSWORD`


