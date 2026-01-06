# Terraform (AWS) 배포 가이드 — Dubbi E2E Service

이 디렉터리는 **AWS 상에서 Dubbi e2e-service를 운영 배포**하기 위한 Terraform 구성입니다.

핵심 목표:
- **API(FastAPI)** + **Worker(Celery)** 를 **ECS Fargate**로 운영
- **RDS(PostgreSQL)** + **ElastiCache Redis** 구성
- **대용량 파일(스크린샷/trace.zip/pdf 등 아티팩트)** 은 컨테이너 로컬 디스크가 아니라 **EFS**에 저장
  - EFS Lifecycle 정책으로 IA(저비용) 이동을 켜서 비용 효율화
- (선택) **Frontend**는 S3(+CloudFront)로 정적 배포

> 현재 애플리케이션은 기본적으로 로컬 파일시스템에 아티팩트를 저장합니다.
> Terraform은 이를 위해 EFS를 `/data`로 마운트하고,
> `ARTIFACT_ROOT=/data/artifacts`, `SCENARIO_ROOT=/data/scenario_store`, `AUTH_STATE_ROOT=/data/auth_state_store`로 주입합니다.

---

## 준비물
- AWS 계정 및 자격증명(예: `AWS_PROFILE`, `AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY`)
- 기존 VPC + Subnet(퍼블릭/프라이빗)  
  - 이 Terraform은 **기존 네트워크를 입력 변수로 받아** 리소스를 얹는 형태입니다.
- 컨테이너 이미지(ECR 또는 외부 레지스트리)
  - `api_image`, `worker_image` 변수로 주입

---

## 빠른 시작

1) 변수 파일 작성

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

2) 초기화/적용

```bash
cd infra/terraform
terraform init
terraform apply
```

3) 출력된 ALB DNS로 접속
- `api_base_url` output 확인

---

## 주요 운영 포인트

### 대용량 파일(아티팩트) 저장
- 러너가 생성하는 PNG/PDF/ZIP 등의 파일이 많기 때문에,
  **Fargate ephemeral storage**에 두면 디스크 부족/유실 위험이 큽니다.
- 따라서 **EFS를 마운트**하여 아티팩트를 영속 저장합니다.

### storageState(로그인 우회 세션)
- FE/Extension이 업로드한 storageState는 `AUTH_STATE_ROOT`에 저장됩니다.
- 이 값도 EFS에 저장되므로, 배포 환경에서 여러 태스크/재기동에도 안정적으로 유지됩니다.

---

## 디렉터리 구조
- `main.tf`: 리소스 정의(ECS/ALB/RDS/Redis/EFS/Logs)
- `variables.tf`: 입력 변수
- `outputs.tf`: 출력
- `terraform.tfvars.example`: 예시 값


