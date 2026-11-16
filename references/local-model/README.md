# 도서 검색 RAG 챗봇

Qwen3 로컬 모델을 사용해, 2026년 10월 기준 총 100개의 도서 정보를 사용해 답변을 리턴합니다.  

## 세팅

- Ollama 를 사용해 다음 두 개의 모델을 받습니다.
  - qwen3-embedding:4b
  - qwen3:4b-instruct-2507-q4_K_M

```bash
ollama pull 모델명
```

- 이후, 해당 프로젝트에 가상환경을 만들고, 패키지를 설치한다.  

```bash
python -m venv venv
source ./venv/Scripts/activate
pip install -r ./requirements.txt
```

- 환경변수를 복사한다.  

```bash
cp -r ./.env.example ./.env
```

## 실행

FastAPI 기반이므로, uvicorn 으로 실행한다.  

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

- 요청 정보
  - POST : `http://127.0.0.1:8000/api/v1/chat`

- Request Body 예시

```json
{
    "prompt": "현재 보유중인 책 중에, 2022년 이후에 출간된 소설은?"
}
```

- Response Body 예시

```json
{
    "answer": "2022년 이후에 출간된 소설은 다음과 같습니다:\n\n1. **채식주의자** - 한강, 출간 연도: 2022년  \n2. **초역 부처의 말** - 코이케 류노스케, 출간 연도: 2024년  \n3. **지구 끝의 온실** - 김초엽, 출간 연도: 2021년 (2022년 이후가 아님, 제외)  \n4. **달러구트 꿈 백화점** - 이미예, 출간 연도: 2020년 (2022년 이후가 아님, 제외)  \n5. **물고기는 존재하지 않는다** - 룰루 밀러, 출간 연도: 2021년 (2022년 이후가 아님, 제외)\n\n따라서 2022년 이후에 출간된 소설은 다음과 같습니다:\n\n- **채식주의자** (한강)\n- **초역 부처의 말** (코이케 류노스케)  \n\n이 두 소설이 2022년 이후에 출간되었습니다."
}
```