# Test Tiers

v0.3.2에서 확립된 4-tier 테스트 전략. `pyproject.toml`의 `[tool.pytest.ini_options]`에 마커 등록됨.

| Tier | 마커 | 실행 시간 | 픽스처 | 목적 |
|---|---|---|---|---|
| Unit | (없음, 기본) | < 5초 | mock backend | 도구 로직 단위 검증 |
| Live quick | `live_quick` | ~30초 | hostname.exe / where.exe (시스템 PE) | 실 BN smoke + finding 회귀 |
| Live full | `live` | ~5분 | update.exe (3.4MB, 8555 funcs) | 릴리스 회귀 |
| Performance | `perf` | 가변 | update.exe | 회귀 추세 추적 |

`pyproject.toml`의 `addopts = "-m 'not perf'"`로 perf는 기본 제외.

---

## 1. Unit (mock)

```bash
pytest -q
```

- 모든 도구는 `BINJA_MCP_FORCE_MOCK=1`에서 mock backend로 동작
- 312+ 케이스 (v0.3.2 기준) — 새 도구 추가 시 그룹당 10-20 케이스 의무
- 위치: `tests/test_tools_mock.py`, `tests/test_edge_cases.py`, `tests/test_workflow.py`

mock backend 확장 시 주의:
- enum 값(MockSymbolType 등)은 **실 BN 정수값과 정확히 일치**해야 함
- 응답 shape는 실 BN 응답과 동일하게 (key 이름/타입)
- 새 API는 `mock_backend.py`에 `MockX` 클래스로 추가, 실 BN의 protocol 매칭

## 2. Live quick

```bash
pytest -m live_quick
```

- v0.3.2에서 도입된 빠른 실 BN tier
- 시스템 PE 픽스처(`C:\Windows\System32\where.exe`, `C:\Windows\SysWOW64\hostname.exe`)
- 35 케이스 (Group A 25 smoke + B 7 finding-verify + C 3 32-bit)
- 라이센스 잠금 없는 시스템 바이너리 사용 → 어디서나 재현 가능
- 위치: `tests/test_live_quick.py`

새 도구 추가 시 live_quick 의무:
- 그룹당 최소 2-3 케이스
- read 도구: 정상 호출 + 에러 케이스 1개
- write 도구: 적용 → 검증 → undo → 복귀 (4단계)

## 3. Live full

```bash
BINJA_MCP_LIVE_TARGET=update.exe pytest -m live
```

- 18+ 케이스 (v0.3.1 기준)
- update.exe 8555 함수 풀에서 페이지네이션 정확성, 거대 함수 디컴파일, 대형 import table 등
- 릴리스 사인오프 직전에만 실행 (per-PR은 live_quick으로 충분)
- 위치: `tests/test_tools_live.py`

## 4. Performance

```bash
pytest -m perf
```

- 11 케이스 (v0.3.1 기준)
- 회귀 ±20% 마진 (CI 부재로 로컬 측정만)
- 위치: `tests/test_perf.py`

---

## 픽스처 위치

```
tests/fixtures/binaries/      # .gitignore — 실제 바이너리는 미커밋
├── update.exe                # 사용자가 환경에 위치 (BINJA_MCP_LIVE_TARGET)
└── (live_quick은 시스템 PE 사용 — 픽스처 디렉토리 불요)
```

`BINJA_MCP_LIVE_FIXTURES_DIR` 환경변수로 위치 오버라이드 가능.

---

## 새 도구 추가 시 테스트 의무

| 도구 종류 | mock 케이스 | live_quick 케이스 | live full 케이스 |
|---|---|---|---|
| Read-only (e.g. list_X) | 정상 + 빈 결과 + offset/limit + 잘못된 binary_id | 1-2 smoke | 1 페이지네이션 회귀 |
| Read with lookup | 정상 + NOT_FOUND + 잘못된 입력 | 1 smoke + 1 NOT_FOUND | 1 라이브 회귀 |
| Write | 적용 + undo 복귀 + redo + 동시성 | 적용→undo→복귀 4단계 | 1 라이브 회귀 |
| Mixed (e.g. undo) | 빈 stack + 적용 후 + race | 1 smoke | 1 라이브 회귀 |

전수 매트릭스는 v0.3.1 ULTRAQA에서 130+ 케이스 도달. v0.4+ 그룹 추가 시 동일 강도 유지.

---

## 결함 발견 우선순위

1. live_quick PASS, live full FAIL → 픽스처 차이 또는 분석 시간 차이 → live_quick에 비슷한 패턴 추가
2. mock PASS, live_quick FAIL → mock-vs-real-BN API 격차 → mock_backend 보강 + 회귀 케이스
3. live PASS, perf FAIL → 회귀 — git bisect로 원인 commit 추적
4. perf PASS, live FAIL → 결정적 결함 — 즉시 fix
