# Client Integration Test Checklist (v0.3.1 ultraqa Phase 3)

이 문서는 binja-mcp v0.3 (23 도구)의 OMC(Claude Code) 및 OMX(Codex CLI) 클라이언트 통합 검증 체크리스트입니다. production 배포 전 1회 수동 실행을 권장합니다.

## 사전 조건

- Binary Ninja Commercial/Ultimate 라이센스가 설치된 환경
- venv editable install 완료 (`pip install -e ".[dev]"`)
- `binja-mcp.exe --version` 정상 (`binja-mcp 0.1.0`)
- 라이브 테스트 바이너리 준비 (예: `C:\Program Files\Vector35\BinaryNinja\update.exe`)

---

## OMC (Claude Code) 통합

### 1. 등록

```powershell
# 사용자 글로벌
claude mcp add --scope user binja-mcp -- "P:\binaryninja-headless-mcp\.venv\Scripts\binja-mcp.exe"

# 또는 프로젝트 단위
claude mcp add --scope project binja-mcp -- "P:\binaryninja-headless-mcp\.venv\Scripts\binja-mcp.exe"
```

확인:
- [ ] `claude mcp list` 결과에 `binja-mcp: ... ✓ Connected` 표기
- [ ] `/mcp` 슬래시 명령으로 reconnect 성공
- [ ] 도구 자동 노출: `mcp__binja-mcp__open_binary`, `mcp__binja-mcp__list_segments` 등

### 2. 23 도구 라운드트립 (1 사이클)

세션을 새로 열어 다음 순서로 호출하고 응답 확인:

| # | 도구 | 검증 포인트 |
|---|------|------------|
| 1 | `open_binary(path)` | `binary_id` 반환, `is_mock=false` |
| 2 | `list_binaries()` | `total=1`, items에 1번 binary_id |
| 3 | `binary_info(binary_id)` | `arch`, `platform`, `entry_point`, `function_count` 모두 정상 |
| 4 | `list_functions(binary_id, limit=5)` | 5개 함수 + `has_more=true` |
| 5 | `decompile(binary_id, "<entry_addr>")` | `il_level="HLIL"`, text가 실제 디컴파일 (repr 아님) |
| 6 | `get_il(binary_id, addr, level="LLIL")` | text가 LLIL 인스트럭션 |
| 7 | `get_il(binary_id, addr, level="MLIL")` | text가 MLIL |
| 8 | `get_disasm(binary_id, addr, length=64)` | text에 어셈블리 |
| 9 | `get_xrefs_to(binary_id, addr, limit=5)` | items 구조 + total |
| 10 | `search_strings(binary_id, pattern="error")` | 매치 결과 |
| 11 | `list_segments(binary_id)` | r/w/x 플래그가 bool |
| 12 | `list_sections(binary_id)` | `.text` 포함, `semantics`가 enum 이름 (`"CodeSectionSemantics"`) |
| 13 | `list_imports(binary_id, limit=5)` | total > 0 (PE의 경우) |
| 14 | `list_exports(binary_id, limit=5)` | total >= 0 |
| 15 | `list_symbols(binary_id, symbol_type="function", limit=3)` | 모두 type=FunctionSymbol |
| 16 | `list_symbols(binary_id, name_or_addr="<known_name>")` | 단일 결과 |
| 17 | `begin_undo(binary_id)` | `state_id` 반환 |
| 18 | `rename_symbol(binary_id, addr, "TEST_NAME")` | `kind="function"`, before/after 정확 |
| 19 | `commit_undo(binary_id, state_id)` | committed 응답 |
| 20 | `undo(binary_id)` | `undone=true` (mock) 또는 best-effort (real BN) |
| 21 | `redo(binary_id)` | 변경 재적용 |
| 22 | `define_type(binary_id, "TestType", "typedef int TestType;")` | name="TestType" |
| 23 | `get_type(binary_id, "TestType")` | definition 비어있지 않음 |
| 24 | `define_data_var(binary_id, addr, "uint64_t")` | type="uint64_t" |
| 25 | `close_binary(binary_id)` | `closed=binary_id` |

각 도구당 응답 형식 확인 + 에러 없음.

### 3. 에러 시나리오

- [ ] 잘못된 binary_id → `BinjaError(BINARY_NOT_FOUND)` (모든 도구 일관)
- [ ] 잘못된 addr `"abc"` → `BinjaError(INVALID_ADDRESS)`
- [ ] `search_strings(pattern="(a+)+", regex=true)` → ValueError "nested quantifier"
- [ ] `define_type(name="X", source="invalid C")` → `BinjaError(TYPE_PARSE_ERROR)`

---

## OMX (Codex CLI) 통합

### 1. 등록

`~/.codex/config.toml`에 추가:

```toml
[mcp_servers.binja]
command = "P:/binaryninja-headless-mcp/.venv/Scripts/binja-mcp.exe"
args = []
startup_timeout_sec = 30
tool_timeout_sec = 300
```

확인:
- [ ] `codex` CLI 시작 시 binja-mcp 도구가 노출됨
- [ ] 첫 호출 시 startup_timeout 내 응답

### 2. 라운드트립

OMC와 동일한 25 단계 라운드트립 실행. OMC와 응답이 일치하는지 비교:

- [ ] 응답 JSON 스키마 동일
- [ ] 도구 호출 latency 비슷 (OMC vs OMX ±20% 이내)
- [ ] 에러 변환 일관 (BinjaError → MCP `isError`)

---

## 종합 sign-off

- [ ] OMC 25 단계 모두 PASS
- [ ] OMX 25 단계 모두 PASS
- [ ] 에러 시나리오 4건 모두 PASS (양쪽)
- [ ] 응답 latency 사용자 체감 OK
- [ ] 발견된 결함 모두 v0.3.1 PR에 반영

검증자 서명: ______________ 날짜: __________

---

## 알려진 한계 (v0.3 시점)

- macOS/Mach-O 형식 검증 미수행 (v0.5 이연)
- Cross-arch (ARM64) 검증 미수행
- `update_analysis=False` 시 일부 도구의 응답이 sparse (e.g. function_count, basic_block_count)
- `undo`/`redo`의 `remaining` 필드는 mock 백엔드에서만 정확 — real BN은 None
