import os
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from rag.embeddings import get_embeddings
from config import settings

def create_vector_store(documents_path: str, vector_store_path: str):
    # 加载所有.txt文档
    loader = DirectoryLoader(
        documents_path,
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={'encoding': 'utf-8'}  # 指定 UTF-8 编码
    )
    documents = loader.load()
    # 文本分块
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = text_splitter.split_documents(documents)
    # 构建向量库
    embeddings = get_embeddings()
    vectorstore = FAISS.from_documents(docs, embeddings)
    # 保存到本地
    vectorstore.save_local(vector_store_path)
    return vectorstore

def load_vector_store(vector_store_path: str):
    embeddings = get_embeddings()
    # allow_dangerous_deserialization=True 是FAISS安全要求
    vectorstore = FAISS.load_local(vector_store_path, embeddings, allow_dangerous_deserialization=True)
    return vectorstore

def get_or_create_vector_store():
    if os.path.exists(settings.vector_store_path) and os.path.isdir(settings.vector_store_path):
        return load_vector_store(settings.vector_store_path)
    else:
        return create_vector_store(settings.documents_path, settings.vector_store_path)