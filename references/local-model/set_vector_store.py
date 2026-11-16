import os
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document

load_dotenv()

def load_text(file_path: str) -> list[Document]:
    with open(file_path, "r", encoding="utf-8") as f:
        return [Document(page_content=f.read(), metadata={"source": file_path})]

file_path = './books.txt'

docs = load_text(file_path=file_path)

text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, add_start_index=True)
all_splits = text_splitter.split_documents(docs)

embeddings = OllamaEmbeddings(
    model="qwen3-embedding:4b",
)

vector_store = Chroma(
    collection_name="books",
    embedding_function=embeddings,
    persist_directory="./chroma_store",
)

vector_store.add_documents(all_splits)

retriever = vector_store.as_retriever()

print("=" * 50)

query = "베스트셀러 1등부터 10등까지 말해봐."

retrieved_docs = retriever.invoke(query)

print(f"[질문]: {query}")
print(f"\n[검색 결과]:\n{retrieved_docs[0].page_content}")
