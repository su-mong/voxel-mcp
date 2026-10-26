# 검증 기록

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

