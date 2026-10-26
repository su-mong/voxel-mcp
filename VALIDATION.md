# 검증 기록

## v0.1.1 — 모델만 보이는 6면 캡처 (2026-10-27)

- 사용자 확인: MagicaVoxel 창 캡처 대신 앱 UI 없이 모델만 보이는 이미지 저장 기능을 확장했다.
- `capture_six_views`: 점유 bounds 자동 framing, 공통 배율·정사각형 중앙 정렬, RGBA 배경, 6면 PNG·3×2 모아보기·manifest 원자적 저장.
- `scripts/test.ps1`: **128 passed**, 전체 커버리지 **95.71%**, 새 `capture.py` **100%**. Ruff lint·format 및 `pip check` 통과.
- 새 테스트는 비대칭 모델의 여섯 방향을 독립적인 광선 계산으로 확인하고, 공통 배율·crop·중앙 정렬, alpha 배경 합성, 빈 모델, 축소, 엄격한 인수, 7장 픽셀 예산, revision, 결정적 출력, 외부 파일 충돌, 중간 실패 복구를 검증한다.
- Windows가 새 이미지 디렉터리를 잠시 잠그는 경우에만 최대 5회로 제한해 공개(rename)를 재시도한다. 일시 실패 후 성공과 지속 실패 후 정리·기존 출력 보존을 검사했다.
- 기존 PNG 투영 회귀 테스트와 실제 MCP stdio legacy/auto 호출에 새 캡처 도구를 포함했다.
- `examples/capture_asset.py mario_64`를 실제 stdio로 실행했다. 마리오 revision 3을 유지한 채 512×512 PNG 여섯 장과 1536×1072 모아보기를 저장했다.
- 출력: `workspace/assets/mario_64/captures/r000003_512px_p24_a66f23269870391e/`. 정면과 모아보기를 직접 확인했으며, 일곱 PNG SHA256과 여섯 이미지 크기를 재검증했다.
- 패키지를 0.1.1로 업데이트했다. 이미 실행 중인 Codex MCP 서버는 연결 재시작 후 새 도구를 읽는다.

## 최초 구현 검증

검증일: 2026-10-26 (Asia/Seoul). Windows, Python 3.12.14, MCP SDK 2.3.0.

- Phase 1 최초 검증: 엔진·스키마·경로 보안 테스트 **39 passed**.
- Phase 2 최초 검증: 단일 모델 VOX·팔레트·손상/미지원 파일·저장 복구 테스트 **30 passed**.
- Phase 3 최초 검증: 메모리 연결, legacy/auto 실제 stdio E2E **3 passed**.
- Phase 4 최초 검증: 도형·변환·undo **13 passed**, 6면 PNG **9 passed**.
- 최종 확장 검증: `scripts/test.ps1` 실행 결과 **109 passed**, 커버리지 **95.16%**. Ruff lint·format 검사 통과.
- `python -m pip check`: **No broken requirements found**.
- Python 3.11의 NumPy 2.3.5 Windows wheel 해석은 pip dry-run으로 확인했다. 전체 테스트의 실제 실행 인터프리터는 Python 3.12이며, 3.11 전체 테스트를 실행했다고 주장하지 않는다.

실제 MCP stdio 예제 `examples/create_slime.py`를 실행했다.

- 에셋: `green_slime`, 크기 32×32×32, 복셀 수 6,373, revision 3.
- 생성 → 첫 저장 → 같은 이름 재불러오기 → 눈 위치 수정 → 재저장 → 6면 PNG 출력.
- 출력: `workspace/assets/green_slime.vox`.
- 6면 출력: `workspace/assets/green_slime/views/r000003_s8_p8_f68bd6ec5d4147f0/`.
- 각 PNG 272×272 RGBA. 면 방향과 SHA256은 해당 폴더의 `manifest.json`에 기록했다.
- `codex mcp get magicavoxel --json`에서 `enabled=true`, stdio, 프로젝트 `.venv` Python 및 절대 workspace 경로를 확인했다.

실제 MagicaVoxel 0.99.7.2를 선택적 launcher로 실행하고 Computer Use로 확인했다. 창에 `green_slime`, `32 32 32`가 표시되며 초록 몸체·검은 눈 두 개·흰 하이라이트가 정상적으로 나타났다. 검토 중 원본 파일을 수정하거나 다시 저장하지 않았다.

지원 단일 모델 import는 writer와 독립적인 비대칭 바이너리 fixture 및 전체 팔레트 인덱스 1..255로 검증했다. 로컬 MagicaVoxel 배포본의 샘플 11개는 모두 현대 장면 확장 청크가 있으므로 `unsupported_vox`로 거절됨을 검사했다. 현대 장면 파일의 완전한 읽기·편집·재저장은 구현 범위가 아니다.

이 환경의 제한된 샌드박스에서는 Windows asyncio 내부 socketpair 생성이 차단되어 초기 MCP 테스트가 멈췄다. 승인된 로컬 실행 환경에서 동일 테스트를 실행해 통과했고, 초기 디버그 프로세스는 정리했다. 서버는 stdio 전용으로 실행한다.

