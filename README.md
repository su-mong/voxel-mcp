# MagicaVoxel Asset MCP

Codex에서 로컬 복셀 에셋을 생성·조회·편집하고 **MagicaVoxel 호환 `.vox`와 6면 PNG**를 출력하는 Python MCP 서버입니다. 모델링 계획은 Codex가 세우고, 서버는 typed operation을 검증·실행합니다. 별도 LLM/API 키, 업로드, MagicaVoxel UI 자동화가 필요하지 않습니다.

`PLAN.md`의 Phase 1 → 2 → 3 → 4 순서로 구현했습니다. 사용자 요청에 따라 계획의 PNG 제외 범위를 확장했습니다. 다중 모델·장면 그래프·레이어·고급 재질 편집은 후속 범위이며, 해당 데이터가 들어 있는 파일은 import에서 거절합니다.

## 설치와 실행

Windows, Python **3.11+**가 필요합니다. 검증 환경은 Windows / Python 3.12.14 / MCP SDK **2.3.0**입니다. v2의 `mcp.server.MCPServer`만 사용합니다.

프로젝트 폴더에서 실행합니다.

```powershell
.\scripts\setup.ps1 -Python C:\path\to\python.exe
.\.venv\Scripts\python.exe -m voxel_mcp.server
```

Codex 내장 Python을 사용하는 이 컴퓨터에서는 다음 경로도 사용할 수 있습니다.

```powershell
.\scripts\setup.ps1 -Python "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
```

스크립트는 `.venv`를 만들고 `requirements.lock`의 고정 의존성을 설치한 뒤 editable 패키지를 등록합니다. 내장 Python에 `ensurepip`가 없는 경우 호스트 pip의 `--python` 기능으로 설치합니다. 의존성을 설치할 때만 패키지 다운로드가 필요하며, 서버는 로컬 파일만 사용합니다.

수동 설치:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

잠금 파일은 Windows의 검증된 전체 의존성 목록입니다. NumPy는 Python 3.11에서 2.3.5, 3.12 이상에서 2.5.4를 선택합니다. 의존성 범위는 `pyproject.toml`에도 선언했습니다. 잠금을 갱신할 때에는 깨끗한 가상환경에서 `pip list --format=freeze --exclude magica-voxel-mcp`를 사용하고 플랫폼·Python 조건을 유지한 뒤 테스트를 재실행하십시오.

## Codex 연결

```powershell
.\scripts\register-codex.ps1
codex mcp get magicavoxel --json
codex mcp list
```

이 스크립트는 Codex 사용자 설정에 `magicavoxel` stdio 서버를 등록합니다. 프로젝트 `.venv`의 절대 Python 경로와 `VOXEL_WORKSPACE` 절대 경로를 저장하므로 Codex의 현재 폴더에 의존하지 않습니다. **등록 후 Codex의 MCP 연결을 재시작하거나 새 채팅을 열어 도구를 불러오십시오.** 현재 대화에 도구가 자동으로 추가되는 것은 아닙니다.

선택적으로 로컬 MagicaVoxel 열기를 활성화하려면:

```powershell
.\scripts\register-codex.ps1 -EnableLauncher
```

이 옵션은 `MagicaVoxel\MagicaVoxel.exe`를 명시적으로 설정합니다. 기본 등록에서는 실행 기능이 비활성화됩니다. 기존 서버 이름을 따로 쓰려면 `-ServerName voxel-local`을 지정합니다.

동등한 TOML 설정 예시(경로를 실제 설치 위치로 바꿉니다):

```toml
[mcp_servers.magicavoxel]
command = 'C:\path\to\voxel-mcp\.venv\Scripts\python.exe'
args = ["-m", "voxel_mcp.server"]
startup_timeout_sec = 10
tool_timeout_sec = 60

[mcp_servers.magicavoxel.env]
VOXEL_WORKSPACE = 'C:\path\to\voxel-mcp\workspace'
# 외부 import가 필요한 경우에만 읽기 허용 폴더를 명시합니다.
# VOXEL_READ_ROOTS = 'C:\voxel-imports;D:\reference-vox'
# MAGICAVOXEL_EXE = 'C:\path\to\MagicaVoxel\MagicaVoxel.exe'
```

설정 위치와 등록 방식은 [공식 Codex MCP 문서](https://learn.chatgpt.com/docs/extend/mcp)를 따릅니다. stdio의 stdout은 프로토콜 전용이고 로그는 stderr에 기록합니다.

## 도구와 작업 흐름

| 도구 | 핵심 입력 | 결과 |
|---|---|---|
| `create_voxel_asset` | `asset_name`, `size`, `palette?` | 빈 에셋, revision 0 |
| `get_asset_info` | `asset_name` | 크기·팔레트·revision·복셀 수·bounds |
| `execute_voxel_operations` | `asset_name`, `operations`, `expected_revision?` | 원자적 배치 결과 |
| `save_vox` | `asset_name`, `expected_revision?` | `.vox` 절대 경로·SHA256 |
| `load_vox` | `asset_name`, `source_path`, `expected_revision?` | 단일 모델 import·지원 범위 |
| `list_assets` | `prefix?` | 저장된 에셋 메타데이터 |
| `undo_voxel_operations` | `asset_name`, `expected_revision?` | 최근 배치 취소·새 revision |
| `export_six_views` | `asset_name`, `scale?`, `padding?`, `expected_revision?` | PNG 6개·manifest 절대 경로 |
| `open_in_magicavoxel` | `asset_name`, `expected_revision?` | 파일 저장 후 선택적 프로그램 실행 |

Codex에 요청할 예:

> magicavoxel 도구로 32×32×32 초록색 슬라임을 만들어줘. 검은 눈과 흰 하이라이트를 넣고 `.vox`와 정면·후면·좌측·우측·상면·하면 PNG를 출력해줘. 최신 revision을 사용하고 저장 경로를 알려줘.

실행 순서:

1. `create_voxel_asset` 또는 `load_vox`로 에셋을 준비합니다.
2. `get_asset_info`의 최신 revision으로 배치를 실행합니다.
3. 결과 revision으로 `save_vox`, `export_six_views`를 호출합니다.
4. 충돌 시 메타데이터를 다시 조회하고 계획을 갱신합니다.

예시 배치:

```json
{
  "asset_name": "green_slime",
  "expected_revision": 0,
  "operations": [
    {"op":"fill_ellipsoid", "center":[16,16,12], "radius":[12,10,11], "color":2},
    {"op":"fill_box", "min":[11,6,13], "max":[12,8,15], "color":1},
    {"op":"fill_box", "min":[20,6,13], "max":[21,8,15], "color":1}
  ]
}
```

팔레트 입력은 **인덱스 순서의 RGBA 배열**입니다. 예: `[[0,0,0,0],[16,24,22,255],[61,189,82,255]]`. 첫 원소는 반드시 투명한 빈 공간이며, 생략한 나머지 인덱스는 MagicaVoxel 기본 팔레트로 채웁니다. 팔레트를 생략하면 전체 기본 팔레트를 사용하므로 색상 인덱스를 추측하지 말고 `get_asset_info`로 확인합니다.

실제 stdio E2E 예제는 생성 → 저장 → 같은 파일 재불러오기 → 눈 위치 수정 → 재저장 → PNG 출력을 수행합니다.

```powershell
.\.venv\Scripts\python.exe examples\create_slime.py
# 이미 같은 이름이 있다면 새 이름을 사용합니다. 기존 에셋을 묵시적으로 지우지 않습니다.
.\.venv\Scripts\python.exe examples\create_slime.py --name slime_02
```

출력 구조:

```text
workspace/
  .state/<asset_name>.json                # 원본 작업 상태, revision, undo, 파일 지문
  .state/store.lock                       # 서버 프로세스 간 공용 잠금
  assets/<asset_name>.vox
  assets/<asset_name>/views/
    r000003_s8_p8_<content-hash>/
      front.png  back.png  left.png  right.png  top.png  bottom.png
      manifest.json
```

작업 상태는 디스크에 남으므로 서버 재시작·다른 Codex 세션에서도 재조회할 수 있습니다. `.vox`만 가져오려면 `load_vox`를 사용합니다. `.vox` 자체에는 이 프로젝트의 revision/undo가 들어 있지 않습니다.

## 좌표·연산 계약

내부 배열은 `numpy.uint8 grid[x,y,z]`, `+X=오른쪽`, `+Y=뒤쪽`, `+Z=위쪽`입니다. 0은 빈 공간, 1..255는 팔레트 색상입니다. 정수 인수는 bool·실수·문자열을 허용하지 않습니다. 미등록 연산과 여분 필드는 거절합니다.

| 연산 | 규칙 |
|---|---|
| `set_voxel` / `remove_voxel` | `point:[x,y,z]` 한 셀 설정/삭제 |
| `fill_box` / `clear_region` | `min`, `max` 양끝 포함, 역방향 범위 거절 |
| `fill_ellipsoid` | 유한 실수 center/radius, 모든 radius > 0; 정수 셀 중심에서 `Σ((p-c)/r)² ≤ 1` |
| `replace_color` | 1..255의 `from_color`를 `to_color` 0..255로 변경; 0으로 바꾸면 삭제 |
| `fill_sphere` | ellipsoid의 세 반지름이 동일한 경우 |
| `fill_cylinder` | 정수 `start/end`, 양수 radius; 축에 수직인 평평한 양끝 면을 포함. 같은 시작/끝 거절 |
| `fill_line` | 양끝 포함 dominant-axis integer DDA. 최근접 정수, 정확히 절반이면 시작점에서 멀어지는 쪽 선택 |
| `mirror` | `axis`, 필수 `mode`; `reflect`는 region 전체 반전. `copy`는 해당 축의 낮은 절반을 높은 절반에 복사. 빈 셀도 덮어쓰며 홀수 중앙면 유지 |
| `rotate_90` | `axis`, `turns` -3..3(기본 1); region 중심 오른손 법칙 회전. 홀수 회전은 회전 평면의 두 길이가 같아야 함. region 안의 빈 셀도 회전 |
| `translate` | region 안의 점유 셀을 `delta`만큼 이동. 선택 내부 겹침은 동시 이동으로 처리. 외부 셀 충돌은 기본 `collision:error`, 명시적 `overwrite`로 변경 가능 |

변환의 선택적 `region`은 `{"min":[x,y,z],"max":[x,y,z]}`이며 생략하면 전체 모델입니다. **경계 밖 쓰기와 도형의 연속적 외곽이 경계 밖으로 나가는 요청은 clip 없이 실패**합니다. cylinder는 축 방향에 따른 실제 반경 외곽으로 검사합니다. 타원체/원통의 경계 비교에는 부동소수점 오차 허용치 `1e-12`를 사용합니다.

배치는 입력 순서대로 복사본에 적용하고 모두 성공한 경우에만 원자적으로 교체합니다. revision은 성공 배치당 1 증가합니다. `affected_voxels`는 배치 전후 최종 색상 인덱스가 달라진 **고유 셀 수**입니다. 최종 결과가 같아도 성공 배치는 revision을 증가시킵니다. undo는 기본 최근 8개 배치를 지원하며 revision은 계속 증가합니다. redo는 제공하지 않습니다.

`expected_revision` 생략 시에도 잠금 안에서 최신 상태를 편집하지만, 이전 계획으로 덮어쓰는 것을 막으려면 항상 전달하십시오. 기존 이름을 `load_vox`로 교체할 때는 필수입니다. 새 이름 import는 revision 0, 기존 이름 교체는 현재 값+1이고 undo 이력이 초기화됩니다. save/export는 revision을 바꾸지 않습니다.

## 6면 PNG 규격

무조명 정투영으로 각 광선의 가장 가까운 **점유 셀** RGBA를 사용합니다. 배경은 투명하고 원본 팔레트 alpha를 보존합니다. 반투명 셀 뒤의 색 합성, 그림자, 조명, 투시, 안티앨리어싱은 제공하지 않습니다. 확대는 nearest-neighbor이며 `scale=1..16`(기본 8), `padding=0..64`(기본 0, 최종 출력 픽셀 단위)입니다. 프레임은 모델 전체 크기를 유지하며 자동 crop하지 않습니다.

| 면 | 카메라 위치 | 화면 오른쪽 | 화면 위 | scale 1, padding 0 크기 |
|---|---|---|---|---|
| front | -Y | +X | +Z | sx × sz |
| back | +Y | -X | +Z | sx × sz |
| left | -X | -Y | +Z | sy × sz |
| right | +X | +Y | +Z | sy × sz |
| top | +Z | +X | +Y | sx × sy |
| bottom | -Z | +X | -Y | sx × sy |

여섯 장과 manifest를 임시 디렉터리에 준비한 후 디렉터리 rename으로 공개합니다. 중간 실패 시 이전 묶음은 유지됩니다. revision·scale·padding·내용 해시별 폴더를 사용하며 반복 요청은 같은 경로/바이트를 반환합니다. 기존 PNG 묶음을 외부에서 수정했으면 충돌로 거절합니다. manifest에는 카메라 방향, 크기, 절대 경로, SHA256, revision이 있습니다. 전체 여섯 장의 합산 픽셀 수 제한을 적용합니다.

## VOX 호환성과 손실 방지

[원 저자 명세](https://github.com/ephtracy/voxel-model/blob/master/MagicaVoxel-file-format-vox.txt)의 little-endian `VOX `/`MAIN`/`SIZE`/`XYZI`/`RGBA`를 구현했습니다. writer는 버전 150, reader는 기본 청크만으로 구성된 버전 150/200을 지원합니다. 축 교환 없이 x/y/z를 기록합니다. `RGBA` 파일 레코드 0..254는 내부 인덱스 1..255에 대응하고, 마지막 파일 레코드는 미사용입니다. `RGBA`가 없으면 원 저자 기본 팔레트를 사용합니다.

중복 좌표, 인덱스 0의 XYZI, 크기 초과, 잘린 헤더·청크·콘텐츠, 부정확한 길이, 잘못된 청크 순서, 중복/중첩 청크, trailing bytes를 거절합니다. 지원하지 않는 청크는 이름을 오류에 표시합니다. `PACK`, `nTRN`, `nGRP`, `nSHP`, `LAYR`, `MATL`, `MATT`, `IMAP` 및 미지 청크를 무시하지 않습니다.

**최신 MagicaVoxel에서 저장한 파일은 모델 하나라도 장면·레이어·재질 청크를 포함할 수 있어 거절될 수 있습니다.** 저장소에 이미 있던 0.99.7.2 샘플 11개도 이 경우에 해당하며, 테스트에서 전부 손실 없이 거절되는지 확인합니다. 이 앱 배포본과 샘플은 재배포하지 않습니다. 기본 단일 모델의 독립적인 비대칭 바이너리 fixture와 왕복 테스트는 항상 실행됩니다. 완전한 현대 MagicaVoxel 파일 편집을 지원한다고 보장하지 않습니다.

파일 기반 연동입니다. MagicaVoxel 실행 프로세스와 실시간 제어·동기화하지 않습니다. 저장 시 현재 파일 SHA256이 마지막 저장 지문 또는 동일 출력 내용과 다르면 거절합니다. 외부 변경을 받아들이려면 `load_vox`로 명시적으로 다시 불러와야 합니다. 현대 장면 파일로 바뀌어 읽을 수 없다면 기존 파일을 보존하고 새 에셋 이름을 사용합니다.

파일은 같은 폴더의 임시 파일에 쓰고 flush/fsync 후 `os.replace`합니다. VOX 파일 교체 전에 오류가 나면 기존 파일이 유지됩니다. 교체 완료 후 별도 상태 지문 기록에 실패하면 저장 성공과 경고를 반환합니다. 이때 추가 편집 전에 동일 revision으로 save를 재시도하면 지문을 복구합니다. 상태와 외부 파일 간 하드웨어 장애까지 포괄하는 다중 파일 트랜잭션은 아닙니다.

MagicaVoxel 수동 점검:

- 예제 `.vox`를 열고 32×32×32 크기, 초록 몸체, 검은 눈과 흰 하이라이트를 확인합니다.
- 비대칭 크기/모서리 색상 fixture를 열어 Z-up, x/y 방향과 팔레트 색상을 확인합니다.
- 지원 범위의 기본 단일 모델을 import → save → 재import하여 좌표·색상이 같은지 확인합니다.
- MagicaVoxel에서 다시 저장한 파일에 장면·재질 청크가 생겼다면 import가 명시적으로 거절되고 원본이 유지되는지 확인합니다.

## 경로·동시성·제한

이름은 1..64자의 ASCII 영문·숫자·`_`·`-`로 제한하며 첫 글자는 영문/숫자입니다. 소문자로 정규화하고 Windows 장치 이름을 차단합니다. `/`, `\`, `..`, 드라이브·UNC 경로, 제어문자, 공백·콜론을 이름에 사용할 수 없습니다. 출력 경로를 사용자 입력으로 직접 받지 않습니다. workspace 아래의 심볼릭 링크/정션을 거절합니다.

import는 기본 workspace 안에서만 읽으며 상대 경로는 workspace 기준입니다. 외부 파일이 필요하면 운영자가 `VOXEL_READ_ROOTS`에 읽기 허용 폴더를 명시합니다(Windows `;` 구분). 읽기 허용은 쓰기 허용을 늘리지 않습니다. workspace를 이 서버가 관리하는 신뢰된 로컬 디렉터리로 사용하십시오. 경로 검사와 파일 열기 사이의 적대적 OS 사용자에 의한 경로 교체까지 방어하는 격리 환경은 아닙니다.

모든 서버는 `.state/store.lock`의 OS 파일 잠금과 프로세스 내 잠금을 사용합니다. 상태는 요청마다 디스크에서 다시 읽습니다. 잠금 대기 시간은 10초이며 revision 검사를 잠금 안에서 수행합니다. 서버를 통하지 않는 외부 프로그램은 이 잠금을 따르지 않으므로 파일 지문 검사와 함께 사용합니다. 네트워크 파일 시스템의 잠금 보장은 대상 범위가 아닙니다.

| 환경 변수 | 기본값 | 의미 |
|---|---|---|
| `VOXEL_WORKSPACE` | `workspace` | 작업·출력 루트 |
| `VOXEL_READ_ROOTS` | 없음 | 추가 읽기 허용 폴더 |
| `VOXEL_MAX_AXIS` | 126 | 축 최대, 설정 상한 256 |
| `VOXEL_MAX_VOXELS` | 2,000,376 | 전체 그리드 셀 수 최대 |
| `VOXEL_MAX_OPERATIONS` | 1,000 | 배치당 연산 수 |
| `VOXEL_MAX_PROCESSED_CELLS` | 20,000,000 | 배치 계산 범위의 누적 셀 수 |
| `VOXEL_MAX_FILE_BYTES` | 67,108,864 | VOX 입출력 파일 크기 |
| `VOXEL_MAX_ASSETS` | 128 | 작업 공간 에셋 수 |
| `VOXEL_HISTORY_LIMIT` | 8 | undo 배치 수, 0이면 비활성화 |
| `VOXEL_MAX_PNG_PIXELS` | 16,000,000 | 6면 PNG의 합산 픽셀 수 |
| `MAGICAVOXEL_EXE` | 없음 | 선택적 실행 파일 |

모델 크기를 늘릴 때 축과 총 셀 제한을 함께 설정해야 합니다. limits를 낮춘 후 기존 큰 에셋을 읽으면 오류가 날 수 있습니다. 이력은 원본 배열의 base64 snapshot이므로 큰 모델·긴 이력은 디스크를 더 사용합니다. 모든 에셋/출력의 누적 디스크 용량 자동 정리는 제공하지 않습니다.

## 테스트

```powershell
.\scripts\test.ps1
```

Ruff 검사, 포맷 검사, pytest, 커버리지(최소 85%)를 실행합니다. 임시 테스트 파일은 `workspace/test-tmp/<unique-id>` 안에서 생성합니다. Windows 샌드박스가 asyncio 내부 로컬 소켓을 막는 환경에서는 MCP 테스트에 허용된 로컬 프로세스 실행 환경이 필요합니다. 서버 자체는 stdio를 사용하며 네트워크 리스너를 열지 않습니다.

단계별 실행:

```powershell
New-Item -ItemType Directory -Path workspace\test-tmp -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest tests/test_operations.py tests/test_security.py -q --basetemp=workspace/test-tmp/phase1
.\.venv\Scripts\python.exe -m pytest tests/test_vox_roundtrip.py -q --basetemp=workspace/test-tmp/phase2
.\.venv\Scripts\python.exe -m pytest tests/test_mcp.py -q --basetemp=workspace/test-tmp/phase3
.\.venv\Scripts\python.exe -m pytest tests/test_geometry.py tests/test_render.py tests/test_concurrency.py -q --basetemp=workspace/test-tmp/phase4
```

테스트는 경계·스키마·원자적 롤백·revision, 비대칭 좌표·팔레트·빈/최대 모델, 독립 VOX fixture, 손상/미지원 파일, 파일 실패·외부 변경 충돌, 경로 탈출·링크, 프로세스 간 충돌, 6면 픽셀 방향·가림·투명도, PNG 묶음 실패 복구, SDK 메모리 연결 및 실제 stdio `tools/list`/도구 호출을 다룹니다. stdio는 legacy handshake와 현재 auto 협상을 모두 검사합니다.

## 코드 구조

`models`/`palette`는 데이터 계약, `operations`/`geometry`는 순수 복셀 연산, `asset_store`는 안전 경로·잠금·상태·undo, `vox_io`는 파일 포맷, `render`는 6면 투영, `service`는 저장·불러오기·내보내기, `launcher`는 선택적 프로그램 열기, `server`는 얇은 MCP 어댑터입니다.

기술 참고: [MCP SDK v2](https://py.sdk.modelcontextprotocol.io/), [기본 VOX 명세](https://github.com/ephtracy/voxel-model/blob/master/MagicaVoxel-file-format-vox.txt), [확장 청크 참고](https://github.com/huhlig/voxfile/blob/master/vox.md).

