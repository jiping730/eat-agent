import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

# 项目根目录：config.py 所在的目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class Settings(BaseSettings):
    zhipuai_api_key: str = os.getenv("ZHIPUAI_API_KEY")
    embedding_model: str = "embedding-2"
    llm_model: str = "glm-4-flash"
    vector_store_path: str = os.path.join(BASE_DIR, "faiss_index")
    documents_path: str = os.path.join(BASE_DIR, "data", "documents")

    class Config:
        env_file = ".env"

settings = Settings()