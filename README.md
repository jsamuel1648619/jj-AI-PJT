# 개발자 역량 성장 플랫폼

로컬 Qwen 기반 Django 서비스입니다. DebugDNA의 코드 분석과 SkillRadar → GrowthPlan 흐름을 제공합니다.

## 실행 (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py runserver
```

- DevDNA 대시보드: http://127.0.0.1:8000/
- DebugDNA: http://127.0.0.1:8000/debugdna/
- SkillRadar: http://127.0.0.1:8000/skillradar/
- GrowthPlan: http://127.0.0.1:8000/growthplan/

SQLite(`db.sqlite3`)에 진단과 세션을 저장하므로 처음 실행하거나 마이그레이션을 추가한 뒤 `manage.py migrate`를 실행합니다. DB 파일은 `.gitignore` 대상이며 커밋하지 않습니다. Selenium 수집에는 Chrome이 필요하며 Selenium Manager가 드라이버를 준비합니다. 처음 실행 시 드라이버 다운로드를 위한 인터넷 연결이 필요할 수 있습니다. Chart.js는 고정 버전 CDN을 사용하며 로딩 실패 시 표로 결과를 확인할 수 있습니다.

## DevDNA 대시보드

메인 페이지 `/`는 같은 브라우저 세션의 실제 DB 기록을 집계합니다. 목표 기업·사업부·직무와 공고 출처, 역량 진단 점수 레이더 차트, 반복 실수 빈도, 선택한 계획의 과제 달성률, 우선 학습 과제와 최근 코드 분석을 보여줍니다. 저장된 값이 없으면 빈 상태로 표시하며 점수·과제·진척도를 임의 생성하지 않습니다. 이전 공고에 기업·직무 필드가 없으면 공고 제목·원문 일부만 표시하고 기업이나 직무명을 추정하지 않습니다.

기본 선택은 가장 최근 학습 계획입니다. 다른 계획을 선택할 수 있으며, 진단 기반 계획은 해당 계획에 연결된 진단을 사용하므로 이후에 다른 진단을 받아도 점수가 뒤섞이지 않습니다. 직접 설정한 계획에는 연결 진단이 없으므로 별도로 최근 완료 진단을 표시합니다. 과제가 없으면 달성률은 0이며, 계획 자체가 없으면 달성률을 표시하지 않습니다. 미평가 점수는 `null` 그대로 표시합니다.

달성률은 `선택한 계획의 완료 과제 수 / 전체 과제 수 × 100`입니다. 과제는 저장된 계획의 주차별 실습 한 개에 대응합니다. 우선 과제에는 계획 생성 시 저장된 역량 우선순위에 따라 역량별 가장 이른 미완료 과제를 보여줍니다. 완료는 실제 역량 향상이나 시간을 인증하는 기능이 아니며 표시 시간은 계획에 배정된 시간입니다.

완료·취소는 Fetch API로 DB에 저장한 뒤 즉시 다시 조회합니다. 열린 다른 탭에는 BroadcastChannel과 storage 이벤트로 알리고, 페이지가 보일 때 5초마다 및 포커스 복귀 시 DB를 재확인합니다. WebSocket 서비스 없이 동작하며, 차트 로딩 실패 시 점수 표와 빈도 목록을 사용할 수 있습니다. 모든 조회·변경 API는 세션 소유자를 검사합니다.

## 로컬 Qwen

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama serve
```

이미 Ollama가 실행 중이면 추가 실행하지 않습니다. `OLLAMA_BASE_URL` 기본값은 `http://127.0.0.1:11434`, `QWEN_MODEL` 기본값은 `qwen3:4b-instruct-2507-q4_K_M`입니다. JSON Schema를 `/api/chat`의 `format`으로 전달하고 Pydantic으로 응답을 검증합니다. 추론 요청의 제한 시간은 90초입니다. 연결 실패는 503, 응답 형식·원문 근거·계획 주차 검증 실패는 502입니다. SkillRadar 화면은 직무 분석과 계획 생성을 모두 로컬 Qwen으로 고정하며 모델·서버 설정을 노출하지 않습니다. 기존 API의 키워드 모드와 GrowthPlan 단독 화면의 기본 계획 기능은 유지합니다.

## SkillRadar 흐름

기본 화면은 현재 단계 한 개와 4단계 진행 표시만 보여줍니다. 처리 중·완료·재시도 상태를 표시하며 요청 중에는 입력·이동·중복 제출을 막습니다. 완료한 단계로 돌아갈 수 있고, 공고나 진단 답변을 수정하면 후속 평가·계획을 무효화하여 오래된 결과가 전달되지 않도록 합니다.

1. **직무 찾기**: 기업명·직무명(필수), 사업부(선택)만 입력합니다. 검색 결과에서 공고를 선택하면 Selenium 본문 수집과 Qwen 분석이 자동으로 이어집니다. 기업·직무·마감일은 원문에서 확인하세요. URL·본문 직접 입력은 기본적으로 접힌 보조 메뉴에 있으며, 자동 수집 실패 시 펼쳐집니다.
2. **직무 분석**: 추출 역량 수·필수 역량 수·요구 수준을 요약합니다. 공고 본문·출처와 역량별 분석 근거는 필요할 때 펼쳐 확인할 수 있습니다. 로컬 Qwen이 필수/우대 구분, 요구 수준·판단 구분·이유·원문 근거, 중요도(1~5)·이유를 JSON으로 추출하고 원문 근거와 스키마를 검증합니다. 분석 실패 시 같은 단계에서 재시도하거나 공고를 바꿀 수 있습니다.
3. **나의 역량 진단**: 추출 역량마다 Qwen이 실무 상황 질문 한 개와 0~5점의 관찰 가능한 평가 기준을 생성합니다. 사용자는 해결 과정·경험을 답하고, Qwen이 기준에 따라 점수·평가 이유·답변 원문 인용·보완점을 반환합니다. 답변에 없는 인용, 범위를 벗어난 점수, 역량 누락·중복은 거부합니다. 빈 답변은 미평가(`null`)이고, 명시적으로 모른다는 답변은 0점 기준입니다. 점수는 답변에서 확인된 이해 수준이며 실제 실무 능력이나 채용 합격을 보장하지 않습니다. 차트·부족 역량·학습 우선순위·평가 근거를 함께 표시합니다.
4. **성장 계획**: DB에 완료된 진단 결과의 점수·보완점·평가 이유로 같은 화면에서 Qwen 계획을 생성하고 저장합니다. 브라우저가 보낸 점수를 재사용하지 않습니다. 기본값은 4주·주 5시간이며 기간·시간·목표 수정·취약점 메모는 선택 메뉴입니다. 요구 수준이 없는 역량에만 목표 선택을 요청합니다. 생성한 계획은 DB ID로 GrowthPlan 관리 화면에서 다시 불러옵니다.

### 진단 저장과 재시도

- `Diagnosis`: 공고 원문·출처, 추출 역량 스냅샷, 질문·0~5 기준, 생성 모델명.
- `DiagnosisAttempt`: 제출 답변 스냅샷, 역량별 평가, 부족 역량·우선순위, 평가 모델명·완료 시각. 답변 변경 후 제출하면 별도 기록을 만듭니다.
- `DiagnosisRoadmap`: 세션 소유자, 선택적 연결 진단, 학습 계획과 설정.
- `LearningTask`: 계획·주차별 과제의 완료 여부, 완료 시각과 갱신 시각.

질문 생성과 채점은 호출당 최대 3개 역량씩 처리하고 완료분을 저장합니다. 실패 시 같은 화면에서 이어서 처리하며, 처리 중 중복 요청은 409를 반환하고 120초가 지난 처리 잠금은 재시도할 수 있습니다. 모델 요청 중 DB 트랜잭션을 열어 두지 않습니다. 동일 완료 평가 재조회는 모델을 호출하지 않습니다. 질문이 준비되지 않았거나 채점이 완료되지 않은 진단으로 계획을 생성할 수 없습니다.

계정 기능은 없으며 DB 세션 쿠키에 연결된 소유자만 자신의 기록을 조회할 수 있습니다. SkillRadar 첫 단계의 ‘이전 진단 결과 불러오기’에서 완료 기록을 열 수 있습니다. 쿠키 삭제·세션 만료 시 기존 기록에 접근할 수 없으며 다른 브라우저·기기와 자동 공유되지 않습니다. 별도 UUID만 알아도 다른 세션의 진단·계획을 열 수는 없습니다.

검색 결과 없음, 브라우저 오류, 시간 초과, 이미지·로그인·차단 페이지 등은 수집 실패로 안내합니다. 자동 로그인이나 차단 우회는 하지 않습니다. 모든 사이트를 지원하지 않으며, 원문 인용 검증이 AI 의미 해석의 정확성까지 보장하지는 않습니다.

요구 수준 척도: 1 입문, 2 기초 실습, 3 프로젝트 활용, 4 독립 문제 해결, 5 설계·최적화·리딩. `explicit`은 해당 척도의 수치가 공고에 명시된 경우, `inferred`는 수행 표현을 AI가 해석한 경우, `unknown`은 판단 불가입니다. 경력 연수를 수준 숫자로 단순 변환하지 않도록 프롬프트에 지시합니다. 키워드 모드는 기술명·섹션 제목만 탐지하며 요구 수준은 `null`로 유지합니다.

격차 = `max(요구 수준 - 현재 수준, 0)`, 진단의 기본 우선순위 점수 = `격차 × 중요도`. 필수 → 구분 없음 → 우대 순으로, 같은 구분 내에서 점수 내림차순, 동점은 중요도 내림차순으로 정렬합니다. 수준 하나라도 없으면 격차·점수는 `null`이고 진단 대상으로 둡니다. GrowthPlan은 아래 DebugDNA 관찰 가산을 추가하며 진단 점수 자체를 변경하지 않습니다. 이 우선순위 점수는 채용 적합도나 합격 확률이 아닙니다.

수집은 공개 HTTP(S) 기본 포트 URL의 주소를 검사하며 로컬·사설 주소를 거부합니다. 브라우저 전체를 네트워크 격리하는 기능은 아니므로 외부 공개 배포 시 브라우저의 내부망 접근을 별도로 제한해야 합니다. 개발 서버는 기본적으로 로컬에서 실행합니다.

## GrowthPlan

SkillRadar에서 전달받거나 직접 입력한 현재·목표 수준, 구분, 중요도와 경험을 사용합니다. 학습 기간 1~12주, 주당 시간 1~40시간, 취약점 메모(최대 5,000자)를 설정합니다. 요구 수준은 초기 목표로 제공하되 AI 해석을 검토하고 수정할 수 있습니다. 목표를 조정한 경우 조정된 목표 기준으로 격차와 순위를 다시 계산합니다.

한 주에 한 역량을 배치하며 필수·일반·우대 구분을 유지합니다. 같은 구분 안에서는 기본 점수에 같은 세션의 DebugDNA 가산을 더해 정렬합니다. 가산은 `min(6, 역량별 실수 관찰 코드 쌍 수 + 유형별 반복 초과 횟수 합)`이며, 각 유형에서 두 번째 관찰부터 반복 초과 횟수에 포함합니다. 예를 들어 Python 경계값 오류가 서로 다른 코드 쌍에서 2회 관찰되면 가산은 `2 + 1 = 3`입니다. 기본 점수·가산·합산 점수와 근거 분석 ID를 계획에 기록하고, SkillRadar의 진단 점수는 그대로 둡니다. 계획 생성 시 서버가 현재 세션의 기록을 조회하므로 클라이언트가 보낸 가산은 사용하지 않습니다.

미평가는 진단, 초급은 기초 실습, 이후에는 프로젝트 적용과 설계 검토·개선 단계를 제시합니다. DebugDNA의 관련 실수 유형·연습 과제를 Qwen 계획 입력과 회고에 포함합니다. 목표 이상이어도 실수 관찰이 있는 역량은 보완 학습 대상으로 포함하며, 목표에 없는 역량을 임의로 추가하지는 않습니다. 과거 관찰이 현재도 동일한 오류가 남아 있다는 뜻은 아닙니다. 기간보다 역량이 많으면 미배정 목록을 표시합니다. 주당 시간에는 실습·회고를 포함하며 실제 목표 달성은 이후 재평가가 필요합니다.

단독 화면의 기본 계획은 모델 없이 생성할 수 있습니다. Qwen 계획은 역량·목표·경험·시간·취약점과 진단 평가 이유·보완점을 반영하되 역량 배정·시간·주차는 서버에서 유지하고 검증합니다. 진단 기반·직접 설정 계획 모두 DB에 저장되며 `/growthplan/?roadmap=<UUID>`로 같은 세션에서 불러옵니다. 기존 저장 계획은 마이그레이션으로 주차별 실습 과제를 만들고 소유자를 연결합니다. 기존 기기 보관 체크는 실제 DB 완료 기록이 아니므로 완료 상태로 자동 추정하지 않습니다.

주차별 체크를 선택하면 완료, 해제하면 취소입니다. 반복 요청은 중복 완료를 만들지 않으며 완료 시각도 유지합니다. 완료·취소는 자동 저장되고 대시보드 및 열린 GrowthPlan 화면에 반영됩니다. 새 계획을 생성하면 이전 계획의 체크를 복사하지 않고 새 과제로 시작합니다. 과제 체크가 진단 점수를 변경하지는 않습니다. 최근 계획 선택·Markdown 다운로드·기기 백업도 지원하되, 백업을 불러와도 완료 상태는 DB 기록을 우선합니다. DB ID가 없는 과거 기기 초안은 읽기 전용이며 다시 계획을 생성해야 완료를 관리할 수 있습니다.

## API

모든 POST API는 `Content-Type: application/json`과 CSRF 토큰이 필요합니다.

| 경로 | 입력 / 결과 |
| --- | --- |
| `/api/skillradar/collect/` | `url` 또는 `company`, `division`, `role` → 공고 본문·출처 또는 선택할 후보. 수집 실패는 422와 `manual_input_required: true` |
| `/api/skillradar/analyze/` | `job_posting`, `source_url`, `use_llm` → 추출 역량 JSON. 기존 `current_skills` 동시 입력도 지원 |
| `/api/skillradar/evaluate/` | 기존 자기평가 비교 API: `job_posting`, `requirements`, `current_skills`, `use_llm` → 격차·순위. 답변 기반 진단은 아래 별도 API 사용 |
| `/api/growthplan/generate/` | `skills`, `weeks`, `hours_per_week`, `weaknesses`, `use_llm` → 학습 로드맵 |
| `/api/skillradar/diagnoses/` | POST: `job_posting`, `source_url`, `requirements` → 진단 생성 |
| `/api/skillradar/diagnoses/<id>/questions/` | POST `{}`: 다음 최대 3개 질문 생성, `ready`가 true일 때 완료 |
| `/api/skillradar/diagnoses/<id>/attempts/` | POST `responses: [{skill_id, answer}]` → 답변 스냅샷 생성 |
| `/api/skillradar/attempts/<id>/evaluate/` | POST `{}`: 다음 최대 3개 채점, `completed`가 true일 때 `result` 반환 |
| `/api/skillradar/diagnoses/history/` | GET: 같은 세션의 최근 완료 진단 30건 |
| `/api/skillradar/attempts/<id>/` | GET: 질문·응답·점수·근거·연결 계획 조회 |
| `/api/growthplan/from-diagnosis/` | POST: `attempt_id`, 선택적 `targets: [{skill_id, level}]`, 기간·시간·메모 → DB 점수 기반 계획 생성·저장 |
| `/api/growthplan/roadmaps/<id>/` | GET: 저장된 진단 기반 계획 조회 |
| `/api/dashboard/` | GET: 현재 세션의 대시보드. 선택적 `?roadmap=<id>`로 계획 지정 |
| `/api/growthplan/roadmaps/` | GET: 같은 세션의 최근 학습 계획 20개 |
| `/api/growthplan/tasks/<id>/completion/` | POST: `{"completed":true}`로 완료, `false`로 취소. 소유자·CSRF·엄격한 boolean 검증 |
| `/api/analyze/` | POST: `original`, `corrected`, 선택적 `related_skills`, `notes`, `use_llm`(기본 true) → DebugDNA 분석·힌트·DB 저장·세션 집계 |
| `/api/debugdna/history/` | GET: 같은 세션의 최근 분석 30개와 전체 반복 실수 집계 |
| `/api/debugdna/analyses/<id>/` | GET: 소유한 코드 원문·분석·현재 반복 빈도 조회 |
| `/api/debugdna/insights/` | GET: 오류 유형 빈도·관련 취약 역량·가산·분석 근거 ID |
| `/api/debugdna/skills/` | GET: Python과 같은 세션의 최근 완료 SkillRadar 진단 역량 후보 |

학습 계획 요청 예:

```json
{"skills":[{"name":"Python","current_level":1,"target_level":4,"required_level":4,"level_basis":"inferred","importance":"required","weight":5,"experience":"기초 실습"}],"weeks":4,"hours_per_week":5,"weaknesses":"경계값 처리 연습","use_llm":false}
```

## DebugDNA

입력은 Python 오답 코드·수정 코드와 선택적 학습 역량·메모입니다. 코드의 들여쓰기와 앞뒤 줄바꿈을 보존합니다. AST로 문법과 함수·반복·조건·클래스·예외 처리 구조를 검사하고 difflib으로 변경 구간과 추가·삭제 줄을 추출합니다. 사용자 코드는 실행하지 않으며 수정 코드의 정답을 보장하지 않습니다.

기본적으로 로컬 Qwen이 오류 원인, 9개 고정 실수 유형 중 분류, 개선 여부, 원본·수정 코드의 변경 근거, 관련 학습 역량, 연습 과제를 생성합니다. 인용이 실제 코드와 변경 구간에 있는지, 관련 역량이 후보에 있는지 Pydantic과 서버 검증을 적용합니다. 힌트는 개념 단서 → 확인 위치 → 수정 접근·검증 과제의 세 필드로 생성하고 서버가 1~3단계로 변환합니다. 화면에서는 한 단계씩 펼칩니다. AI를 끄면 AST·diff와 기본 힌트만 제공합니다.

`CodeAnalysis`에 세션 소유자, 코드 원문, 메모, 관련 역량, 연결 진단, 구조·변경점·분석·힌트, 모델명과 시각을 저장합니다. 실패한 AI 응답은 저장하지 않습니다. 같은 입력은 기존 분석을 재사용하고, 메모나 설정을 바꿔 다시 분석해도 반복 빈도는 동일 코드 쌍별·실수 유형별 한 번만 셉니다. 동일 분석에 같은 유형이 여러 번 있어도 중복 집계하지 않습니다. 과거 localStorage 기록은 근거 코드가 없어 DB 집계로 자동 이전하지 않습니다.

관련 역량을 비우면 Python과 같은 세션의 최근 완료 SkillRadar 진단 역량을 후보로 사용합니다. SkillRadar 질문 생성 시 실수 관찰을 참고할 수 있지만 답변 점수는 질문의 기준과 현재 답변만으로 평가합니다. DebugDNA에서 최근 진단으로 이동하거나 SkillRadar의 결과·계획 화면에서 실수 기록 반영 여부를 확인할 수 있습니다. 세 기능은 동일한 DB 세션 소유자를 사용하며 다른 세션은 코드와 기록을 조회할 수 없습니다.

## 검증

```powershell
.\venv\Scripts\python.exe manage.py check
.\venv\Scripts\python.exe manage.py test

# 실제 Chrome에서 수집·평가·계획·저장 흐름 검증 (공고와 모델 응답은 로컬 테스트 서버)
$env:RUN_SELENIUM_TESTS='1'
.\venv\Scripts\python.exe manage.py test skillradar.test_browser
Remove-Item Env:RUN_SELENIUM_TESTS

# 설치된 로컬 Qwen으로 실제 추출·계획 생성 검증
.\venv\Scripts\python.exe scripts/verify_qwen.py

# 실제 공고 수집 → Qwen 추출 → 진단·채점 → DB 저장 → 계획 검증
# 원래 DB와 분리된 임시 테스트 DB를 사용합니다.
.\venv\Scripts\python.exe scripts/verify_diagnosis.py --url https://www.python.org/jobs/8213/

# 실제 Qwen 코드 분석 2회 → 반복 빈도·DB → Qwen 성장 계획 검증
# 임시 DB와 고정 진단 점수로 우선순위 가산을 확인합니다.
.\venv\Scripts\python.exe scripts/verify_debugdna.py
```

기본 테스트는 스키마·근거 검증, 별칭·중복, 미평가·0·초과 수준, 가중 우선순위, 수집 성공·실패·종료 처리, CSRF, 진단 저장·재개·소유권·점수 위조 방지, 대시보드 집계, 기존 계획 과제 이관, 과제 완료·취소·중복 요청·계획별 진행 분리를 검증합니다. 브라우저 테스트는 전체 진단 흐름, DB 이력 복원, 실제 차트 데이터, 모바일 빈 상태와 두 탭 사이의 완료·취소 양방향 갱신을 페이지 재로드 없이 확인하며 기본 실행 시 생략합니다. 외부 사이트 수집과 실제 모델 응답은 환경에 따라 결과가 달라질 수 있습니다.

설정은 개발 서버용입니다. 배포 시 비밀 키, DEBUG, 호스트, 정적 파일과 브라우저 격리 구성을 별도로 설정해야 합니다. 구현 참고: `references/crawling/main.py`, `references/local-model/main.py`, [Selenium 대기](https://www.selenium.dev/documentation/webdriver/waits/), [Ollama 구조화 출력](https://docs.ollama.com/capabilities/structured-outputs).
