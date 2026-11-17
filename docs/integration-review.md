# 앱 연동 점검 결과

검증일: 2026-11-17

## 데이터 흐름

1. SkillRadar는 기업·직무(필수), 사업부(선택)로 공고 후보를 검색한다. 선택한 공고를 Selenium으로 수집하고 Qwen으로 역량·요구 수준·중요도·원문 근거를 추출한다. 수집 실패 시 URL 또는 본문 입력으로 계속할 수 있다.
2. 질문·평가 기준을 생성하고 사용자 답변을 평가한다. Diagnosis와 DiagnosisAttempt에 공고, 목표 기업·직무, 답변, 점수, 평가 근거, 보완점을 저장한다. 빈 답변은 미평가이며 명시적인 모름 답변과 구분한다.
3. DebugDNA는 Python 코드 쌍을 AST·difflib과 Qwen으로 분석한다. CodeAnalysis의 근거 검증된 실수 기록을 코드 쌍·유형별로 중복 제거해 집계한다. 사용자 코드는 실행하지 않는다.
4. GrowthPlan은 저장된 진단의 점수·요구 수준·보완점과 현재 세션의 DebugDNA 기록을 사용한다. 역량 격차와 중요도에 실수 관찰 가산을 반영해 순서·주차별 과제를 만든다. 실수 기록으로 진단 점수를 변경하지 않는다.
5. Dashboard는 선택한 DiagnosisRoadmap의 진단·목표 직무와 LearningTask 완료 상태를 표시한다. GrowthPlan과 Dashboard의 완료·취소는 DB에 저장되고 다른 탭에 반영된다.

모든 앱은 동일한 세션 소유자를 사용한다. 계정·기기 간 동기화는 현재 범위에 포함되지 않는다.

## 발견 및 개선

- GrowthPlan에서 진단 기반 계획을 재생성하면 일반 생성 API를 호출해 진단 연결과 평가 보완점이 사라졌다. 저장된 계획의 실제 진단 FK와 역량 ID를 응답에 포함하고 재생성에도 진단 전용 API를 사용하도록 수정했다. 서버가 원래 점수·평가 근거를 다시 읽으므로 Dashboard의 목표 기업·직무도 유지된다.
- 진단 기반 계획에서 점수·역량 이름·필수 여부·중요도를 직접 변경하거나 역량을 추가·삭제하는 입력을 비활성화했다. 목표 수준·기간·시간·메모는 조정할 수 있고, 점수 변경은 연결된 SkillRadar 재진단으로 안내한다.
- DebugDNA 기록은 자동 반영된다는 안내를 추가해 취약점 메모에 분석 결과를 다시 옮겨 적을 필요를 줄였다.
- GrowthPlan 생성 중 중복 submit 이벤트를 차단했다. 일반 계획과 진단 기반 계획은 기존 공통 build_plan을 계속 사용한다.
- 모델 실패 후 재시도 시 입력과 진단 연결이 유지되는 브라우저 회귀 검증을 추가했다.

## 실행 결과

| 검사 | 결과 |
| --- | --- |
| manage.py check | 이상 없음 |
| RUN_SELENIUM_TESTS=1 manage.py test | 65개 전부 통과, 생략 없음 |
| 실제 Chrome 사용자 흐름 | 3개 시나리오 통과 |
| scripts/verify_diagnosis.py | 실제 Qwen 추출·질문·평가·DB 복원·계획 저장 통과 |
| scripts/verify_debugdna.py | 실제 Qwen 코드 분석 2회·근거·힌트·중복 없는 반복 집계·계획 가산 통과 |
| manage.py makemigrations --check --dry-run | 변경 없음 |
| git diff --check | 오류 없음 |

Chrome 검증 범위: 공고 검색·선택, 질문과 평가, DebugDNA 기록, 계획 생성과 복원, 실제 Chart.js 데이터, 완료·취소의 두 탭 동기화, 모바일 빈 상태·가로 넘침, 수집·추출·질문·평가·계획 실패 후 재시도, 답변 수정에 따른 결과 무효화, GrowthPlan 재생성 후 진단 연결·점수·기업·보완점 유지.

Chrome 테스트는 실제 Chrome과 Django·DB를 사용하되 공고 검색 결과·본문과 모델 응답을 로컬 테스트 서버로 통제한다. 실제 Qwen 검증은 별도 API 통합 스크립트와 임시 DB로 수행했다. 이번 검증에서 외부 채용 사이트의 실시간 검색·수집과 실제 Qwen을 하나의 브라우저 흐름으로 함께 실행한 것은 아니다. DebugDNA 실제 모델 검증의 진단 점수는 가산 효과 비교를 위한 고정 fixture이며, 실제 채점은 verify_diagnosis.py에서 별도로 확인했다.

기존 AGENTS.md와 references/crawling, references/local-model을 확인했다. 커밋은 수행하지 않았으며 .gitignore 대상 파일은 변경 목록에 포함하지 않았다.
