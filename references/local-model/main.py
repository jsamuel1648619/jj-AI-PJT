import os
from fastapi import FastAPI
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain.tools import tool
from langchain_core.documents import Document

load_dotenv()

embeddings = OllamaEmbeddings(
    model="qwen3-embedding:4b",
)

vector_store = Chroma(
    collection_name="books",
    embedding_function=embeddings,
    persist_directory="./chroma_store",
)

@tool
def search_books_info(query: str) -> tuple[str, list[Document]]:
    """
    도서 정보를 검색합니다.

    Args:
        query (str): 검색할 핵심 질의.

    Returns:
        tuple[str, list[Document]]: 검색된 문서의 직렬화된 문자열과 원본 문서 객체 리스트(artifact)로 구성된 튜플(tuple)

    Examples:
        - "한강 작가가 쓴 도서는 뭐가 있지?"
        - "현재 보유중인 도서 중 소설을 추천해줘"
    """

    retrieved_docs = vector_store.similarity_search(query, k=2)
    serialized = "\n\n".join(
        (f"Source: {doc.metadata}\nContent: {doc.page_content}")
        for doc in retrieved_docs
    )
    return serialized, retrieved_docs

SYSTEM_PROMPT = """
너는 도서 추천 챗봇이다.
항상 한국어로 답변한다.
다음 툴을 사용할 수 있다.
  - search_books_info : 도서 100권 정보에 접근할 때 사용
일반적인 질문은 툴을 사용하지 않고 답변한다.
"""

llm = ChatOpenAI(
    base_url=os.getenv("BASE_URL"),
    model="qwen3:4b-instruct-2507-q4_K_M",
    api_key="no_need",
)

# 에이전트 생성
agent = create_agent(
    model=llm,
    tools=[search_books_info],
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
    final_answer = response["messages"][-1].content
    return {"answer": final_answer}
