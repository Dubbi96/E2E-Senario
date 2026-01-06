# Hogak 로그인(Apple 2FA/팝업) 우회 가이드 (Headless E2E)

Hogak은 SNS 로그인(특히 Apple)이 팝업/2차인증으로 이어지는 경우가 많아,
서버/CI의 headless 환경에서 **로그인 과정을 재현하기가 사실상 불가능**합니다.

이 레포는 이를 타개하기 위해 Playwright의 **storageState(쿠키+로컬스토리지) 주입**을 지원합니다.

## 1) storageState 캡처(한 번만, headed)

로컬에서 브라우저를 띄워 수동 로그인 후 세션을 저장합니다.

```bash
python3 scripts/capture_storage_state.py --url https://hogak.live/login_t --out /abs/path/to/hogak.storage_state.json
```

- 브라우저에서 Apple/Kakao/Naver/Google 로그인을 완료
- 터미널에서 ENTER → storageState 저장

## 2) Headless 실행 시 storageState 주입

### 옵션 A: 파일 경로로 주입

```bash
export E2E_STORAGE_STATE_PATH=/abs/path/to/hogak.storage_state.json
pytest -q tests/e2e/test_scenario.py --scenario scenarios/hogak_generated/hogak_P0_auth_vod_play.json
```

### 옵션 B: CI Secret로 base64 주입

storageState JSON을 base64로 인코딩해서 Secret로 저장 후:

```bash
export E2E_STORAGE_STATE_B64='...'
pytest -q tests/e2e/test_scenario.py --scenario scenarios/hogak_generated/hogak_P0_auth_vod_play.json
```

## 3) 시나리오에서 로그인 필요 여부 표시

시나리오 최상단에 아래를 지정하면,
세션 주입이 없을 때 테스트가 바로 실패하면서 안내 메시지를 제공합니다.

```json
{
  "requires_auth": true
}
```

또는, 시나리오 파일에서 직접 경로를 줄 수도 있습니다:

```json
{
  "storage_state_path": "./hogak.storage_state.json"
}
```

## 4) 만료/로그아웃 대응

storageState는 Hogak/Apple 세션 정책에 따라 만료될 수 있습니다.
만료되면 `ensure_logged_in` step에서 빠르게 감지하도록 되어 있으므로,
다시 `scripts/capture_storage_state.py`로 갱신해서 주입하세요.


