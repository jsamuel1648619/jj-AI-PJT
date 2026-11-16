import os
import json
from fastapi import FastAPI
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain.tools import tool
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException

load_dotenv()


def _fetch_naver_news() -> str:
    """네이버 뉴스 메인 페이지에서 주요 뉴스를 수집합니다."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get("https://news.naver.com/")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        driver.implicitly_wait(3)

        # JavaScript로 뉴스 링크 추출
        raw_items = driver.execute_script("""
            const results = [];
            const seen = new Set();
            // 뉴스 섹션 내의 기사 링크 추출
            const newsSections = document.querySelectorAll('[role="region"], div[role="article"], div[data-section]');
            
            newsSections.forEach(section => {
                const sectionLinks = section.querySelectorAll('a');
                sectionLinks.forEach(link => {
                    const href = link.getAttribute('href') || '';
                    if (!href.includes('n.news.naver.com') && !href.includes('/article/')) return;
                    
                    // 링크의 실제 제목 텍스트 추출 (자식 요소의 텍스트만)
                    let title = '';
                    const heading = link.querySelector('h1, h2, h3, h4, h5, h6');
                    if (heading) {
                        title = heading.textContent.trim();
                    } else {
                        // h태그가 없으면 링크 텍스트에서 언론사명/날짜 제거
                        title = link.textContent.trim();
                    }
                    
                    // 불필요한 텍스트 제거
                    title = title.replace(/\\d{1,2}월\\s*\\d{1,2}일\\s*\\d{1,2}:\\d{2}/g, '').trim();
                    title = title.replace(/\\d{1,2}\\.\\d{1,2}\\(\\w+\\)/g, '').trim();
                    title = title.replace(/(?:YTN|한국경제TV|중앙일보|대전일보|한국경제|매일경제|경향신문|아시아경제|서울경제|JTBC|SBS|SBS Biz|헤럴드경제|MBC|TV조선|머니투데이|뉴스1|조선비즈|파이낸셜뉴스|비즈워치|국민일보|헬스조선|이코노미스트|매경이코노미|주간조선|한경비즈니스|JIBS|부산일보|데일리안|노컷뉴스|시사IN|KBS|국제신문|CJB청주방송|전자신문|매일신문|여성신문|뉴스타파|전주MBC|뉴시스|동아일보|조선일보|한국일보|경향신문|한겨레|연합뉴스|연합뉴스TV|중앙일보|머니투데이|)[\\s,，.。!?!]+$/g, '').trim();
                    title = title.replace(/^[(\[]?속보[)\]]?[\\s,，.。]+/g, '').trim();
                    
                    if (title.length > 5 && !seen.has(title) && !['구독', '속보 더보기', '더보기', '내용작성전'].includes(title)) {
                        seen.add(title);
                        results.push({ title, url: href });
                    }
                });
            });
            
            // 섹션 기반 추출이 실패하면 일반적인 방식으로
            if (results.length < 5) {
                document.querySelectorAll('a').forEach(link => {
                    if (results.length >= 20) return;
                    const href = link.getAttribute('href') || '';
                    if (!href.includes('n.news.naver.com') && !href.includes('/article/')) return;
                    
                    let title = '';
                    const heading = link.querySelector('h1, h2, h3, h4, h5, h6');
                    if (heading) {
                        title = heading.textContent.trim();
                    } else {
                        title = link.textContent.trim();
                    }
                    
                    title = title.replace(/\\d{1,2}월\\s*\\d{1,2}일\\s*\\d{1,2}:\\d{2}/g, '').trim();
                    title = title.replace(/\\d{1,2}\\.\\d{1,2}\\(\\w+\\)/g, '').trim();
                    
                    if (title.length > 5 && !seen.has(title) && !['구독', '속보 더보기', '더보기', '내용작성전'].includes(title)) {
                        seen.add(title);
                        results.push({ title, url: href });
                    }
                });
            }
            return JSON.stringify(results);
        """)
        
        items = json.loads(raw_items)
        
        # 언론사 매핑: 섹션 구조를 통해 언론사 연결
        # 간단히: 기사 제목에 언론사가 이미 포함되어 있는 경우 처리
        
        # 중복 제거 및 상위 15개
        seen = set()
        unique_items = []
        for item in items:
            if item["title"] not in seen:
                seen.add(item["title"])
                unique_items.append(item)
            if len(unique_items) >= 15:
                break

        result = "=== 오늘의 주요 뉴스 (네이버 뉴스) ===\n\n"
        for i, item in enumerate(unique_items, 1):
            result += f"{i}. {item['title']}\n"
        return result

    finally:
        driver.quit()


def _fetch_central_news() -> str:
    """중앙일보 메인 페이지에서 주요 뉴스를 수집합니다 (폴백용)."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get("https://www.joongang.co.kr/")
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        driver.implicitly_wait(3)

        # JavaScript로 뉴스 링크 추출 (h2 a 링크 중 article URL)
        raw_items = driver.execute_script("""
            const results = [];
            const seen = new Set();
            // h2 내의 a 태그 중 article URL만 추출
            document.querySelectorAll('h2 a').forEach(a => {
                const href = a.getAttribute('href') || '';
                if (href.includes('/article/')) {
                    // 텍스트가 여러 줄이면 첫 줄만 사용 (중복 제거)
                    let title = a.textContent.trim();
                    if (title.includes('\\n')) {
                        title = title.split('\\n')[0].trim();
                    }
                    if (title.length > 5 && !seen.has(title) && !['구독', '더보기'].includes(title)) {
                        seen.add(title);
                        results.push({ title, url: href });
                    }
                }
            });
            return JSON.stringify(results);
        """)
        
        items = json.loads(raw_items)
        
        # 중복 제거
        seen = set()
        unique_items = []
        for item in items:
            if item["title"] not in seen:
                seen.add(item["title"])
                unique_items.append(item)
            if len(unique_items) >= 15:
                break
        
        result = "=== 오늘의 주요 뉴스 (중앙일보) ===\n\n"
        for i, item in enumerate(unique_items, 1):
            result += f"{i}. {item['title']}\n"
        return result

    finally:
        driver.quit()


@tool
def search_news() -> str:
    """
    뉴스 정보를 검색합니다.

    Returns:
        str: 오늘의 주요 뉴스를 정리한 문자열
    """
    try:
        return _fetch_naver_news()
    except WebDriverException as e:
        print(f"네이버 뉴스 접속 실패: {e}")
        try:
            return _fetch_central_news()
        except WebDriverException as e2:
            print(f"중앙일보 접속 실패: {e2}")
            return "뉴스를 가져오는데 실패했습니다. 나중에 다시 시도해주세요."
    except Exception as e:
        print(f"네이버 뉴스 수집 실패: {e}")
        try:
            return _fetch_central_news()
        except Exception as e2:
            print(f"중앙일보 수집 실패: {e2}")
            return "뉴스를 가져오는데 실패했습니다. 나중에 다시 시도해주세요."

SYSTEM_PROMPT = """
너는 챗봇이다.
항상 한국어로 답변한다.
다음 툴을 사용할 수 있다.
  - search_news : 오늘 뉴스를 selenium 을 사용해 web scraping 할 때 사용함
일반적인 질문은 툴을 사용하지 않고 답변한다.
"""

llm = ChatOpenAI(
    model=os.getenv("API_MODEL"),
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("GMS_KEY"),
    use_responses_api=True,
)

# 에이전트 생성
agent = create_agent(
    model=llm,
    tools=[search_news],
    system_prompt=SYSTEM_PROMPT,
)

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    prompt: str


class ChatResponse(BaseModel):
    answer: str


@app.post("/api/v1/chat", response_model=ChatResponse)
def create_user(chat_request: ChatRequest) -> ChatResponse:
    response = agent.invoke({"messages": [("user", chat_request.prompt)]})
    # 마지막 메시지 내용 추출
    last_msg = response["messages"][-1]
    if hasattr(last_msg, 'text') and last_msg.text:
        final_answer = last_msg.text
    elif hasattr(last_msg, 'content'):
        content = last_msg.content
        if isinstance(content, list):
            # content가 블록 리스트인 경우 텍스트만 추출
            final_answer = "".join(
                block.get('text', '') if isinstance(block, dict) else str(block)
                for block in content
                if isinstance(block, dict) and block.get('type') == 'text'
            )
        else:
            final_answer = str(content)
    else:
        # dict인 경우
        if isinstance(last_msg, dict):
            if 'text' in last_msg:
                final_answer = last_msg['text']
            elif 'content' in last_msg:
                content = last_msg['content']
                if isinstance(content, list):
                    final_answer = "".join(
                        block.get('text', '') if isinstance(block, dict) else str(block)
                        for block in content
                        if isinstance(block, dict) and block.get('type') == 'text'
                    )
                else:
                    final_answer = str(content)
            else:
                final_answer = str(last_msg)
        else:
            final_answer = str(last_msg)
    return {"answer": final_answer}
