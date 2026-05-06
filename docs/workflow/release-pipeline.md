# Release Pipeline (v0.3 검증 워크플로우)

v0.3에서 검증된 그룹별 자동화 파이프라인. v0.4 이후 도구 그룹 추가 시 동일 절차 사용.

---

## 그룹 단위 자동화 — Heavy 모드

각 PR은 단일 `executor` 서브에이전트가 다음 self-chain을 끝까지 수행:

```
1. [구현]
   - 신규 src/binja_mcp/tools/<group>.py + @tool 등록
   - mock_backend.py 확장 (필요 시)
   - errors.py 신규 코드 추가 (있다면)
   - tools/__init__.py import 추가

2. [자체 deslop — ai-slop-cleaner 인라인]
   Pass 1: dead code 제거 (speculative 상수, 미사용 헬퍼)
   Pass 2: 중복 제거 (cross-import private, backcompat shim)
   Pass 3: 명명/에러 일관성 (BinjaError 패턴, ValueError → 적절한 코드)
   Pass 4: 테스트 보강 (mock-only path 커버리지)
   각 pass 후 pytest + ruff 통과 확인

3. [자체 ultraqa — green까지 게이트 cycle]
   Gate 1: pytest -q (mock + integration)
   Gate 2: ruff check src tests
   Gate 3: FastMCP build_server() + list_tools() smoke
   Gate 4: registry sanity (도구 수 증분 확인)
   실패 시: architect 진단 → 인라인 fix → 재실행 (max 5 cycles)

4. [보고]
   - 변경 파일 목록 + LOC delta
   - pytest/ruff 결과
   - deslop 제거 항목 요약
   - ultraqa cycle 횟수 + 최종 게이트 상태
   - 알려진 잔여 리스크
```

## 메인 Claude의 PR-level 오케스트레이션

```
for PR in [그룹별]:
  1. git checkout -b v0.X-<group> main          # ← 항상 main에서 분기 (NOT 이전 PR 브랜치)
  2. Agent(executor, self-chain)                 # 백그라운드/포그라운드 선택
  3. executor 보고 수신
  4. Agent(verifier 또는 code-reviewer, diff 검토) # writer/reviewer 분리 강제
  5. verifier OK → git push + gh pr create --base main
  6. 라이브 회귀:
     - BINJA_MCP_LIVE_TARGET=update.exe pytest -m live_quick (~30s)
     - 릴리스 직전: pytest -m live (full ~5min)
  7. 사용자에게 PR URL 보고 + 머지 신호 대기
  8. [머지 후] git checkout main && git pull --ff-only origin main
  9. 다음 PR 진입
```

## 다중 모델 리뷰 (v0.3.1 → v0.3.2 패턴)

OMC ULTRAQA만으론 누락 있음 — OMX(Codex) 독립 리뷰에서 14건 추가 발견. 패턴:

1. OMC ULTRAQA로 1차 결함 검출 + 수정 (PR n.1)
2. OMX Codex 독립 리뷰로 2차 결함 검출 + 수정 (PR n.2)
3. 두 모델 합산이 production-ready 기준

### OMX 호출 방법 (v0.3.2 실측)

`/codex:review` 슬래시 명령은 v0.3.2 시점에 권한/실행 흐름 이슈로 안정 동작 못 함.
실제로 사용한 경로 — **claudecode-pty MCP로 Codex CLI 세션 직접 spawn**:

```
1. mcp__claudecode-pty__pty_spawn  → codex CLI 세션 띄움
2. 권한 정책 차단 회피: --dangerously-bypass-approvals-and-sandbox (yolo) 플래그
   (config의 ask-for-approval=never 옵션은 MCP tool 승인까지 우회하지 못함)
3. pty_write로 리뷰 프롬프트 paste, pty_send_key Enter로 제출
4. pty_wait + pty_read로 응답 수집
5. pty_kill로 세션 정리
```

긴 리뷰 프롬프트는 `[Pasted Content N chars]` 표시 후 별도 Enter가 필요 (paste 자동 submit 안 됨).

### ⚠️ YOLO 모드 보안 제약 (반드시 준수)

`--dangerously-bypass-approvals-and-sandbox`는 **모든 승인/샌드박스 우회**:
- 파일 읽기/쓰기, 임의 셸 명령, 네트워크 호출 모두 허용됨
- 따라서 다음 환경에서만 사용:
  - **격리된 신뢰 워크스페이스** (전용 repo, 별도 user account/container)
  - 시크릿/자격증명/사내 키 **부재** (env, ~/.aws, ~/.ssh 등 마스킹 필수)
  - 신뢰할 수 있는 diff만 입력 (외부 PR 리뷰는 절대 yolo로 돌리지 말 것)
  - 세션 종료 후 `pty_kill cleanup=true`로 즉시 정리
- **금지**: production 환경, 공유 머신, 사용자 홈 디렉토리에서 실행
- 외부 입력 신뢰 모델: 리뷰 대상 코드는 prompt-injection 시도를 포함할 수 있음 → 별도 머신/VM 권장

### OMX가 잘 잡는 각도
- 직접 BN API 문서 조회 (Platform vs BinaryView 차이 등)
- 적대적 정규식 패턴 사고 (ReDoS 누락 케이스)
- TOCTOU race 분석
- MCP 스키마 생성 고려사항

## PR 시작 체크리스트

작업 시작 전 반드시 확인:

- [ ] `git status` clean, `git checkout main` 완료
- [ ] `git pull --ff-only origin main` 최신 동기화
- [ ] `git checkout -b v0.X-<group>` (base가 main인지 확인 — `git log main..HEAD` 비어있어야)
- [ ] 그룹 도구 명세 작성 (도구명/입력/출력/에러)
- [ ] mock_backend 확장 범위 명시
- [ ] 의존하는 인프라 확인 (e.g. v0.3 undo, types)

## PR 종료 체크리스트

머지 전 반드시 확인:

- [ ] `gh pr view <n> --json baseRefName` → `"main"` 인지 (stacked PR 방지)
- [ ] `pytest -q` mock 그린
- [ ] `pytest -m live_quick` 그린 (~30s)
- [ ] `ruff check src tests` 클린
- [ ] verifier/code-reviewer agent APPROVE
- [ ] PR description에 새 도구 수 + 테스트 수 명시
- [ ] `.omc/`, `.omx/`, `.openchrome/` 등 런타임 state 미포함 (`git diff --stat | grep -E "^\.om"` 비어야)

## 사용자 머지 신호 대기

자동 진행 차단 신호:
- 사용자 `/cancel` 또는 "stop"
- live 테스트 실패
- verifier critical 발견 → 사용자 개입 요청

각 PR 머지 후 `claude mcp` reconnect로 OMC 도구 등록 자동 갱신 확인 필요.
