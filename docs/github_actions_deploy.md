## GitHub main 머지 → 자동 배포 (GitHub Actions)

이 레포는 main 브랜치에 push(=머지 포함)되면:
- Docker 이미지(API/Worker)를 빌드하여 **ECR에 push**
- Terraform으로 **ECS/RDS/Redis/EFS**를 갱신(apply)

을 자동으로 수행하도록 `.github/workflows/deploy-main.yml`을 추가했습니다.

### 1) GitHub Actions 권한(권장: AWS OIDC)
GitHub Actions에서 장기 AWS Access Key를 쓰지 않기 위해 OIDC를 권장합니다.

- AWS IAM에 OIDC Provider(GitHub) + Role 생성
- Role trust policy에서 이 레포만 허용
- Role에 아래 권한 필요(최소):
  - ECR push/pull
  - ECS 서비스 업데이트
  - ALB/SG/RDS/Redis/EFS/CloudWatch Logs 생성/갱신
  - S3/DynamoDB (Terraform backend state)

### 2) Terraform backend (S3 + DynamoDB Lock)
Terraform state는 로컬이 아니라 S3에 저장해야 안전합니다.
워크플로우는 `terraform init -backend-config=...` 형태로 backend를 주입합니다.

필요 리소스:
- S3 bucket: `TFSTATE_BUCKET`
- DynamoDB table: `TFSTATE_DYNAMODB_TABLE` (Lock용)
- Key: `TFSTATE_KEY` (예: `dubbi-e2e/prod/terraform.tfstate`)

### 3) GitHub Secrets/Variables 설정
GitHub repo settings → Secrets and variables → Actions → Secrets에 아래를 추가하세요.

필수:
- `AWS_REGION`: `ap-northeast-3`
- `AWS_ROLE_TO_ASSUME`: OIDC role ARN
- `TFSTATE_BUCKET`
- `TFSTATE_DYNAMODB_TABLE`
- `TFSTATE_KEY`
- `TF_PROJECT`: 예) `dubbi-e2e`
- `TF_VPC_ID`
- `TF_PUBLIC_SUBNET_IDS`: JSON string 예) `["subnet-a","subnet-b"]`
- `TF_PRIVATE_SUBNET_IDS`: JSON string 예) `["subnet-c","subnet-d"]`
- `TF_JWT_SECRET_KEY`
- `TF_DB_PASSWORD`
- `ECR_REPO_API`: 예) `dubbi-e2e-api`
- `ECR_REPO_WORKER`: 예) `dubbi-e2e-worker`

선택:
- `TF_ENABLE_FRONTEND_S3`: 현재 워크플로우는 기본값(false)을 사용합니다. 필요하면 terraform 변수로 별도 적용하세요.

### 4) 최초 배포 흐름
1) 로컬에서 terraform을 한번 apply(혹은 main 머지로) → 인프라 생성
2) 이후 main 머지마다:
   - ECR에 `:<git sha>` 태그로 push
   - terraform apply가 그 태그를 ECS task definition에 주입해 롤링 배포

### 5) storageState(로그인 우회 세션) 운영
배포 환경에서는 `AUTH_STATE_ROOT`가 EFS로 마운트되어 영속 저장됩니다.
클라이언트는 FE/Extension에서 업로드한 세션을 공유/재사용할 수 있습니다.

## (CI/CD) Public Suite API에서 storageState를 “첨부”해서 실행하기
외부에서 `X-Api-Key`로 `/public/v1/suite-runs`를 호출할 때, 아래 필드를 추가로 보내면
각 케이스 디렉터리에 `storage_state.json`이 주입되고 `combined.json`에 `storage_state_path`가 자동 설정됩니다.

- `storage_state_b64`: `storageState.json` 파일 내용을 base64로 인코딩한 문자열
- `storage_state_filename`(선택): 기본 `storage_state.json`

예시(curl):

```bash
ST_B64=$(python3 - <<'PY'
import base64,sys
data=open('hogak.storage_state.json','rb').read()
print(base64.b64encode(data).decode('utf-8'))
PY
)

curl -X POST "$API_BASE/public/v1/suite-runs" \
  -H "X-Api-Key: $DUBBI_TEAM_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"team_id\": \"TEAM_ID\",
    \"combinations\": [[\"SCENARIO_ID_1\",\"SCENARIO_ID_2\"]],
    \"storage_state_b64\": \"${ST_B64}\"
  }"
```


