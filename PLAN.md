# MagicaVoxel Asset MCP — Codex 구현 계획

> 구현 상태 (2026-10-26): Phase 1~4의 엔진·파일 I/O·MCP·편의 기능을 구현하고 테스트했다.
> 사용자의 추가 요청으로 아래 원안의 PNG 제외 범위를 확장하여 `export_six_views` 도구를 구현했다.
> 다중 모델/장면/재질 확장은 검토 후 후속 범위로 유지하며, 해당 청크가 있는 입력은 거절한다.
> 실제 설치 환경은 MCP SDK 2.3.0이며 `MCPServer` API와 stdio 연결을 검증했다.
> 생성한 `workspace/assets/green_slime.vox`를 MagicaVoxel 0.99.7.2에서 열어 크기·색상·형상을 확인했다.
> 상세한 설치·연산·PNG 방향·지원 한계·검증 절차는 `README.md`를 참조한다.

> 목적: Codex에서 MCP 도구를 호출해 MagicaVoxel 호환 `.vox` 복셀 에셋을 생성·조회·수정·저장·불러온다.  
> 대상: Windows 로컬 환경, Codex CLI/IDE, Python 3.11+.

## 0. Codex에 전달할 첫 지시문

이 저장소에서 본 문서 `PLAN.md`를 읽고 **Phase 1부터 순서대로 구현**하라. `MagicaVoxel` 프로그램의 비공식 UI 자동화에 의존하지 말고, `.vox` 파일의 안정적인 읽기·쓰기와 복셀 편집 엔진을 구현하라. 구현 중 확실하지 않은 .vox 사양은 링크된 레퍼런스 및 실제 샘플 파일로 검증하라. 각 Phase의 테스트를 통과시킨 뒤 다음 단계로 넘어가고, 구현·설정·테스트 절차를 README에 기록하라. 먼저 동작하는 MVP를 완성하라.

## 1. 핵심 요구사항과 범위

### 필수

1. MCP 서버를 Codex에 **stdio**로 연결한다.
2. Codex가 복셀 모델을 `create`, `inspect`, `edit`, `save`, `load` 할 수 있게 한다.
3. MagicaVoxel에서 열 수 있는 `.vox` 파일을 생성·읽기·수정·저장한다.
4. Typed Voxel Operations 스키마와 원자적 배치 실행, revision 충돌 방지를 구현한다.
5. 파일 포맷, 좌표계, MCP 인터페이스, 경로 안전성을 자동화 테스트로 검증한다.
6. 로컬 저장 공간 이외로 임의 업로드하지 않으며, 허용된 작업 폴더 외부 경로에 쓰지 않는다.

### MVP에서 제외 (후속 개발)

- MagicaVoxel UI에 키/마우스 이벤트를 보내는 자동화
- 이미지 렌더링·미리보기·2D 파일 출력과 관련된 모든 기능
- 애니메이션, 장면 그래프, 다중 모델/레이어, 고급 재질의 완전한 보존 및 편집
- 별도의 LLM 호출: **모델링 계획과 도구 선택은 Codex가 수행**

### 반드시 명시할 한계

- `.vox` 파일 편집은 **파일 기반 연동**이며, MagicaVoxel 실행 프로세스를 실시간 제어하거나 동기화하지 않는다.
- `.vox`의 재질·장면 노드·레이어 등 복합 기능은 MVP에서 보존을 보장하지 않는다. 지원하지 않는 입력은 **명시적으로 거절**하거나 읽기 전용으로 처리하며, 묵시적으로 손실 저장하지 않는다.
- Codex가 자연어를 Operation JSON으로 변환할 수는 있으나 품질은 모델·도구 설명·검증 방식에 좌우된다.

## 2. 권장 아키텍처

```text
Codex (CLI / IDE)
  └── MCP stdio
       └── Python MCP server
            ├── asset_store           안전한 에셋 경로·버전·저장 관리
            ├── operation_executor    스키마 검증 + 복셀 연산(원자적 적용)
            ├── vox_io                MagicaVoxel .vox read/write
            ├── palette               팔레트 관리
            └── magicavoxel_launcher  선택적 프로그램 열기
                 └── MagicaVoxel.exe  파일 검토·수동 편집 (선택)
```

MVP에서는 실행 중인 MagicaVoxel 프로세스에 실시간 연결할 필요가 없다. **디스크의 `.vox` 교환**이 계약이다. 나중에 실시간 동기화가 필요할 때만 별도 브리지/IPC를 설계한다.

## 3. 권장 프로젝트 구성

```text
magica-voxel-mcp/
├── PLAN.md
├── README.md
├── pyproject.toml
├── .gitignore
├── src/voxel_mcp/
│   ├── __init__.py
│   ├── server.py
│   ├── config.py
│   ├── models.py
│   ├── asset_store.py
│   ├── operations.py
│   ├── geometry.py
│   ├── vox_io.py
│   ├── palette.py
│   └── launcher.py
├── tests/
│   ├── test_operations.py
│   ├── test_vox_roundtrip.py
│   ├── test_security.py
│   └── test_mcp.py
└── workspace/
    └── assets/
```

추천 의존성: `mcp[cli]`, `numpy`, `pydantic`, `pytest`; 선택적으로 `pytest-cov`. 의존성 버전 범위를 명시하고 lockfile을 유지할 것. Python 3.11 이상.

## 4. 데이터 모델과 좌표계 — 필수 계약

- 단일 모델 크기 `(sx, sy, sz)`로 표현한다. 각 축은 양의 정수이며 MVP 권장 상한은 축당 126이다. 크기와 총 복셀 수 제한은 설정 가능하게 하며 실제 `.vox` writer의 범위에 맞춘다.
- 내부 배열 인덱싱: `grid[x, y, z]` (`numpy.uint8`). `0` = 빈 공간, `1..255` = 팔레트 색상 인덱스.
- `palette`는 최대 256개 RGBA 색상을 관리한다. **인덱스 0은 빈 공간으로 사용하며 .vox 파일 팔레트/색상 인덱스와의 매핑은 round-trip 테스트로 확인한다.**
- 좌표계: `+X = right`, `+Y = back`, `+Z = up`; 좌표 범위는 각각 `0..sx-1`, `0..sy-1`, `0..sz-1`.
- 모든 연산은 위 좌표계를 따르며, MagicaVoxel 파일 포맷의 축 방향과 일치하는지 비대칭 샘플을 통해 검증한다.
- 내부 에셋에는 `asset_name`, `size`, `palette`, `grid`, `revision`을 포함한다. 빈 공간과 팔레트 색상 인덱스를 혼동하지 않는다.

## 5. Voxel Operation Schema

ChatGPT/Codex에 표준 `voxel operations` 문법이 내장되어 있는 것은 아니다. MCP 도구 설명과 입력 JSON schema를 **프로젝트에서 직접 정의**한다. 먼저 typed `Pydantic` 모델로 판별 유니온(discriminated union)을 구성한다.

### 필수 연산

| op | 인수 | 의미 |
|---|---|---|
| `set_voxel` | `point:[x,y,z], color:int` | 한 셀 설정 |
| `remove_voxel` | `point:[x,y,z]` | 한 셀 비우기 |
| `fill_box` | `min:[x,y,z], max:[x,y,z], color:int` | 범위 양끝 포함 |
| `fill_ellipsoid` | `center:[x,y,z], radius:[rx,ry,rz], color:int` | 이산 타원체 |
| `fill_sphere` | `center, radius, color` | 이산 구 |
| `fill_cylinder` | `start, end, radius, color` | 세부 규약 문서화 후 구현 |
| `fill_line` | `start, end, color` | 결정적 정수 3D 선 |
| `clear_region` | `min, max` | 부분 삭제 |
| `replace_color` | `from_color, to_color` | 색상 변경 |
| `mirror` | `axis, region?, mode` | 대칭 복사/반사: overwrite 정책 필수 |
| `rotate_90` | `axis, turns, region?` | 회전 중심·충돌·범위 정의 필수 |
| `translate` | `delta:[dx,dy,dz], region?` | 이동시 경계/충돌 정책 필수 |

첫 MVP에서는 **set/remove/fill_box/fill_ellipsoid/clear_region/replace_color**를 먼저 구현하고 나머지는 순차 추가한다.

### 예시 요청

```json
{
  "asset_name": "green_slime",
  "operations": [
    {"op":"fill_ellipsoid", "center":[16,12,16], "radius":[12,10,11], "color":4},
    {"op":"fill_box", "min":[10,13,5], "max":[12,16,5], "color":1}
  ],
  "expected_revision": 0
}
```

### 실행 규약

- 실행 순서는 배열 순서대로; 실패한 요청은 **전부 롤백**(복사본에서 적용한 뒤 원자적 교체).
- 모든 범위/크기/색상값/좌표 검증. 경계 밖 쓰기는 기본적으로 오류(조용한 clip 금지).
- 연산 최대 개수 및 총 처리 셀 수 상한 제공(무한/과도 루프 방지).
- `expected_revision` 일치 여부로 stale overwrite 방지, 성공 시 revision 증가.
- 명령 실행 결과는 `{ok, asset_name, revision, affected_voxels, warnings}` 형식.
- 스키마·세부 경계 규칙·편집 결과는 테스트로 고정.

## 6. MCP 도구 인터페이스 (MVP)

정확한 함수·스키마를 선언하되, 백엔드와 MCP 함수는 분리할 것.

| MCP Tool | 입력 | 반환 |
|---|---|---|
| `create_voxel_asset` | `asset_name, size:[x,y,z], palette?` | asset id, revision, size |
| `get_asset_info` | `asset_name` | size, revision, palette, voxel_count, bounds |
| `execute_voxel_operations` | `asset_name, operations[], expected_revision?` | result + new revision |
| `save_vox` | `asset_name` | `.vox` 절대 경로, revision |
| `load_vox` | `asset_name, source_path` | asset id, revision + 지원 범위 정보 |
| `list_assets` | (선택적 prefix) | 에셋 목록 |
| `open_in_magicavoxel` | `asset_name` | 시작 여부 또는 실행 결과; 옵션 기능 |

MCP 내부에서 모든 파일 경로는 미리 설정한 `workspace` 아래에만 생성. 외부 입력 `asset_name`에 구분자, `..`, 제어문자, 절대 경로 금지. `load_vox(source_path)`는 **읽기 허용 경로 정책**을 명시적으로 검증.

도구 설명에 "복셀 0=비어 있음", 좌표계, Batch atomicity, revision 및 저장·불러오기 워크플로를 충분히 적을 것. MCP 서버 차원의 `instructions`를 지원하는 SDK 버전이라면 공통 지침도 넣을 것.

## 7. `.vox` 읽기/쓰기

### MVP: 단일 복셀 모델

- VOX 헤더 및 `MAIN`, `SIZE`, `XYZI`, `RGBA` 청크 지원.
- 청크 길이와 콘텐츠 경계 검증, 손상된 파일에서 안전하게 오류 처리.
- RGB와 팔레트 인덱스는 .vox 사양에 맞게 변환, `RGBA` 기본/사용자 정의 팔레트 테스트.
- MagicaVoxel에서 생성한 단일 모델을 load → save → 재로드했을 때 복셀/색상 동일성 검증.
- 당장 지원하지 않는 `PACK`, `nTRN`, `nGRP`, `nSHP`, `LAYR`, `MATL` 등은 데이터 손실 위험을 문서화하고 **손실 없이 저장할 수 없는 파일은 import 단계에서 명시적으로 거절**할 것(향후 scene graph 지원 설계).
- 기존 파일에 쓰기 전 충돌 방지, 원자적 파일 저장(임시파일+replace).
- 샘플 `.vox` fixture 생성 또는 허가된 파일 사용; 실제 MagicaVoxel에서 여는 수동 점검 체크리스트 포함.

레퍼런스:
- 원 저자 기본 포맷 명세: https://github.com/ephtracy/voxel-model/blob/master/MagicaVoxel-file-format-vox.txt
- 확장 청크 조사 참고: https://github.com/huhlig/voxfile/blob/master/vox.md

## 9. MCP 서버 실행 및 Codex 등록

SDK의 현재 API와 버전을 **실제 설치 환경에서 확인**하고 그 버전에 맞게 구현한다. 현재 Python SDK v2 문서는 `mcp.server.MCPServer`와 `.run(transport="stdio")` 접근을 안내한다. v1 `FastMCP` 예제를 무작정 혼용하지 말 것.

```python
# 구조 예제 — 백엔드 함수 구현 후 연결
from mcp.server import MCPServer

mcp = MCPServer("magica-voxel-mcp")

@mcp.tool()
def get_asset_info(asset_name: str) -> dict:
    """Return metadata for an existing voxel asset."""
    return asset_service.get_info(asset_name)

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

위 코드는 **구조 예시**이며 `asset_service`는 실제 구현 대상이다.

로컬 등록 예시 (프로젝트 경로를 실제 값으로 교체):

```powershell
codex mcp add magicavoxel -- C:\path\to\magica-voxel-mcp\.venv\Scripts\python.exe -m voxel_mcp.server
codex mcp list
```

또는 사용자 설정 `~/.codex/config.toml`:

```toml
[mcp_servers.magicavoxel]
command = "C:\\path\\to\\magica-voxel-mcp\\.venv\\Scripts\\python.exe"
args = ["-m", "voxel_mcp.server"]
cwd = "C:\\path\\to\\magica-voxel-mcp"
startup_timeout_sec = 10
tool_timeout_sec = 60
```

설정은 Python 패키지 설치 또는 `PYTHONPATH` 설정을 전제로 한다. **프로젝트 내 가상환경 Python을 명시**하고, stdout에 로그/print 출력 금지(프로토콜 전용), 로그는 stderr.

참고:
- Codex MCP: https://learn.chatgpt.com/docs/extend/mcp
- Codex 설정: https://learn.chatgpt.com/docs/config-file/config-reference
- Python MCP SDK: https://py.sdk.modelcontextprotocol.io/

## 10. 단계별 작업 계획

### Phase 1 — 순수 복셀 엔진 / 스키마

- [x] `pyproject.toml`, 패키지 구조, pytest 준비
- [x] `VoxelAsset`, palette, revision 모델 및 직렬화
- [x] 안전한 workspace 경로 저장소
- [x] 기본 6개 Operation 구현 + typed validation + atomic batch
- [x] 단위 테스트 및 비대칭 테스트 fixture

**완료 조건:** 복셀 생성/수정/재조회, invalid operation 전체 롤백, revision 체크 통과.

### Phase 2 — MagicaVoxel .vox 호환

- [x] 단일 모델 .vox writer (SIZE/XYZI/RGBA)
- [x] reader + 엄격한 청크 검증
- [x] round-trip / 팔레트 검증
- [x] MagicaVoxel에서 파일 열기 수동 검증 절차

**완료 조건:** 생성한 `.vox`를 MagicaVoxel에서 열고, MagicaVoxel에서 저장한 지원 범위의 `.vox`를 다시 읽었을 때 동일한 모델/팔레트 확인.

### Phase 3 — MCP 통합

- [x] MCP 도구 등록 및 스키마 테스트
- [x] stdio 실행 및 Codex 등록 문서화
- [x] 자산 생성 → 연산 batch → .vox 저장 → 재불러오기 → 수정·재저장 E2E
- [x] 오류 메시지/로그 개선

**완료 조건:** Codex CLI에서 자연어 요청을 바탕으로 도구를 호출하여 `.vox` 파일을 실제 생성하고, 불러온 파일을 수정·재저장한다.

### Phase 4 — 편의 기능 (후순위)

- [x] sphere/cylinder/line/mirror/rotate/translate
- [x] 편집 이력·undo 및 충돌 보호 강화
- [x] MagicaVoxel 실행·열기 (`MAGICAVOXEL_EXE` 설정된 경우에만)
- [x] 다중 모델/장면 그래프 및 재질 확장 검토

## 11. 필수 자동화 테스트

1. `grid[x,y,z]` 축 방향 및 크기 검증
2. `set_voxel`/`fill_box` 음수·경계 초과·잘못된 색상 오류
3. batch 중간 실패 시 내용 및 revision 불변
4. `fill_ellipsoid`, `clear_region`, `replace_color` 결과 정확성
5. 빈 모델 및 최대 허용 크기의 `.vox` 저장·재로드
6. `.vox` round-trip에서 복셀 좌표·색상·팔레트 동일
7. MagicaVoxel에서 작성한 단일 모델 `.vox` import 호환성
8. 미지원 scene/multi-model `.vox`에 대해 손실 저장 차단
9. 손상된 청크 크기·불완전 파일·이상한 색상 인덱스 차단
10. 경로 탈출(`../`, 절대 경로, Windows 드라이브·UNC 경로) 차단
11. 미등록 operation 및 과도한 연산 규모 차단
12. MCP `tools/list` 및 도구 호출 통합 테스트
13. 파일 저장 중 오류 시 이전 `.vox` 원본 보존
14. 반복 저장·복원 시 결정적 결과 및 revision 충돌 검증

## 12. Codex E2E 작업 시나리오

**사용자 요청:**

> 32×32×32 크기의 초록색 슬라임을 만들어. 검은 눈 두 개를 추가해서 `.vox` 파일로 저장해줘. 그리고 해당 파일을 다시 불러와 눈의 위치를 조금 수정한 다음 덮어써줘.

**Codex 기대 행동:**

1. `create_voxel_asset("green_slime", [32,32,32], ...)`
2. `execute_voxel_operations(...)` — 타원체 몸체와 눈 추가
3. `get_asset_info("green_slime")` — 크기·팔레트·복셀 수 확인
4. `save_vox("green_slime")`
5. `load_vox(...)` — 저장된 파일 재불러오기
6. `execute_voxel_operations(...)` — 눈 위치 변경
7. `save_vox("green_slime")` — 변경된 `.vox` 저장
8. 최종 `.vox` 경로 및 revision 보고

**예상 결과:**

```text
workspace/assets/green_slime.vox
```

## 13. 구현 시 우선 해결할 기술적 쟁점

- MagicaVoxel 실제 파일을 기준으로 팔레트 인덱스·기본 팔레트·좌표 축 및 축 교환 여부 검증.
- MagicaVoxel에서 직접 수정한 파일을 재불러올 때 지원하지 않는 scene graph/재질/레이어를 손실시키지 않는 정책.
- 파일 저장 중 오류가 발생해도 기존 `.vox`가 망가지지 않도록 원자적 쓰기.
- 반복 요청에서 이전 revision을 통한 덮어쓰기 방지.
- 동시에 여러 Codex 세션이 같은 에셋을 편집할 경우 잠금 또는 낙관적 동시성 제어.

## 14. 성공 정의

**다음이 모두 성공하면 MVP 완료:**

- Codex가 MCP 서버를 인식한다.
- Codex 자연어 요청으로 복셀 모델을 생성·조회·수정한다.
- 생성된 `.vox` 파일을 MagicaVoxel에서 열 수 있다.
- 지원되는 `.vox` 파일을 불러온 후 편집하고 다시 저장할 수 있다.
- 복셀 좌표·색상·팔레트가 저장·불러오기 과정에서 유지된다.
- 미지원/손상 입력과 경로 탈출 시 안전하게 실패하며, 기존 파일을 보존한다.
- 프로젝트의 모든 자동화 테스트가 통과한다.
- 새 개발 환경에서 README만으로 실행 가능하다.

## 15. 공식/기술 문서

- MCP Python SDK (v2): https://py.sdk.modelcontextprotocol.io/
- Codex MCP 설정: https://learn.chatgpt.com/docs/extend/mcp
- Codex 설정 레퍼런스: https://learn.chatgpt.com/docs/config-file/config-reference
- MagicaVoxel .vox 기본 포맷: https://github.com/ephtracy/voxel-model/blob/master/MagicaVoxel-file-format-vox.txt
- 확장 .vox 청크 참고: https://github.com/huhlig/voxfile/blob/master/vox.md

