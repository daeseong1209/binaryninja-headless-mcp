# Release Workflow Reference

이 디렉토리는 v0.3 릴리스 사이클에서 검증된 워크플로우를 v0.4+에서 재사용하기 위한 참조 문서입니다.

| 문서 | 내용 |
|---|---|
| [release-pipeline.md](release-pipeline.md) | PR 그룹별 자동화 파이프라인 (executor self-chain, writer/reviewer 분리) |
| [test-tiers.md](test-tiers.md) | 테스트 계층 (mock / live_quick / live_full / perf) + 픽스처 전략 |
| [lessons-learned.md](lessons-learned.md) | v0.3에서 만난 함정과 해결책 (stacked PR, mock-vs-real-BN 격차, ID 설정 등) |

## 빠른 진입 — 새 그룹 시작 시

1. [release-pipeline.md](release-pipeline.md) §"PR 시작 체크리스트"부터 읽기
2. [lessons-learned.md](lessons-learned.md) §"PR base는 항상 main"부터 읽기
3. 그룹 작업 후 [test-tiers.md](test-tiers.md) §"새 도구 추가 시 테스트 의무"확인
