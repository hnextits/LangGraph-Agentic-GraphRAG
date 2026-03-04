import os
import json
import logging
import sys
try:
    import torch  # type: ignore
except Exception:
    torch = None
from pathlib import Path

# backend 디렉토리를 sys.path에 추가하여 utils.* 모듈을 notebooklm에서 직접 실행할 때도 불러올 수 있도록 함
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# 특정 모듈의 로그 레벨 조정은 main.py에서 configure_logging 호출 후 수행
# 여기서는 로깅 설정을 호출하지 않음
logging.getLogger('transformers').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('filelock').setLevel(logging.WARNING)
logging.getLogger('huggingface_hub').setLevel(logging.WARNING)
logging.getLogger('weaviate').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# 전역 변수로 기본 dtype 설정
GENERATOR_TORCH_DTYPE = "auto"

class RAGConfig:
    """텍스트 전용 RAG 시스템 설정"""
    
    # 싱글톤 패턴을 위한 클래스 변수
    _instance = None
    
    # 임베딩 모델 관련 변수
    _embedding_model = None
    _embedding_tokenizer = None
    _is_embedding_loaded = False
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(RAGConfig, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        # 이미 초기화된 경우 건너뛰
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        #############################################
        # 1. 경로 및 파일 설정
        #############################################
        from utils.path_helpers import get_project_root, get_data_pipeline_dir
        self.PROJECT_ROOT = get_project_root()
        self.DATA_ROOT = get_data_pipeline_dir()
        self.DATA_PATH = self.DATA_ROOT
        self.SESSIONS_ROOT = self.DATA_ROOT / "sessions"
        self.DEFAULT_DOC_DIR = self.DATA_ROOT / "doc"
        self.DEFAULT_METADATA_DIR = self.DEFAULT_DOC_DIR / "metadata"
        self.DEFAULT_METADATA_FILE = self.DEFAULT_METADATA_DIR / "file_metadata.json"
        
        # 기본 디렉토리 생성
        self.DATA_ROOT.mkdir(parents=True, exist_ok=True)
        self.SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)
        self.DEFAULT_DOC_DIR.mkdir(parents=True, exist_ok=True)
        self.DEFAULT_METADATA_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"
        
        #############################################
        # 1-1. Weaviate 설정
        #############################################
        # 환경 변수 기반 Weaviate 설정 분리
        env = os.getenv('ENVIRONMENT', 'production')  # 기본값: production
        
        if env == 'test':
            # 테스트 환경 설정
            self.WEAVIATE_HOST = os.getenv('TEST_WEAVIATE_HOST', "localhost")
            self.WEAVIATE_PORT = int(os.getenv('TEST_WEAVIATE_PORT', "8080"))
            self.WEAVIATE_TEXT_CLASS = "TestTextDocument"
            self.WEAVIATE_IMAGE_CLASS = "TestImageDocument"
        else:
            # 운영 환경 설정
            self.WEAVIATE_HOST = os.getenv('WEAVIATE_HOST', "127.0.0.1")
            self.WEAVIATE_PORT = int(os.getenv('WEAVIATE_PORT', "8080"))
            self.WEAVIATE_TEXT_CLASS = "TextDocument"
            self.WEAVIATE_IMAGE_CLASS = "ImageDocument"
            
        self.WEAVIATE_URL = f"http://{self.WEAVIATE_HOST}:{self.WEAVIATE_PORT}"
        self.WEAVIATE_BATCH_SIZE = 100
        self.WEAVIATE_VECTORIZER = "text2vec-model2vec"  # 컨테이너에서 설정한 vectorizer

        #############################################
        # 1-2. Neo4j 설정 (Deep Graph Traversal용)
        #############################################
        self.NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
        self.NEO4J_USER = os.getenv("NEO4J_USER", "")
        self.NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
        self.GRAPH_MAX_HOPS = int(os.getenv("GRAPH_MAX_HOPS", "6"))

        #############################################
        # 2. SGLang 서버 모델 설정
        #    - 모든 SGLang 서버의 모델명, 엔드포인트, GPU, 포트, mem_fraction을 한곳에서 관리
        #    - LazyLoading: 필요 시 자동 기동, 유휴 5분(300s) 후 자동 종료
        #    - GPU 배치: generator → cuda:0 / 나머지 → cuda:1
        #############################################
        self.SGLANG_IDLE_TIMEOUT = 60  # 유휴 자동 종료 시간 (초)
        self.SGLANG_KEEPALIVE_INTERVAL = int(os.getenv("SGLANG_KEEPALIVE_INTERVAL", "20"))

        # ── 2-1. 생성기 (Generator) ─────────────────
        self.LLM_MODEL = "Qwen/Qwen3-8B"                          # ~16GB
        self.SGLANG_GENERATOR_ENDPOINT = os.getenv("SGLANG_GENERATOR_ENDPOINT", "http://localhost:30000")
        self.SGLANG_GENERATOR_PORT = 30000
        self.SGLANG_GENERATOR_DEVICE = "cuda:0"
        self.SGLANG_GENERATOR_MEM_FRACTION = 0.3                 # cuda:0 단독 사용

        # ── 2-2. 임베딩 (Embedding) ─────────────────
        self.EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"          # ~8GB
        self.SGLANG_EMBEDDING_ENDPOINT = os.getenv("SGLANG_EMBEDDING_ENDPOINT", "http://localhost:30001")
        self.SGLANG_EMBEDDING_MODEL = self.EMBEDDING_MODEL
        self.SGLANG_EMBEDDING_PORT = 30001
        self.SGLANG_EMBEDDING_DEVICE = "cuda:1"
        self.SGLANG_EMBEDDING_MEM_FRACTION = 0.15                  # cuda:1 공유

        # ── 2-3. 리랭커 (Reranker) ──────────────────
        self.RERANKER_MODEL_NAME = "Qwen/Qwen3-Reranker-4B"       # ~8GB
        self.SGLANG_RERANKER_ENDPOINT = os.getenv("SGLANG_RERANKER_ENDPOINT", "http://localhost:30002")
        self.SGLANG_RERANKER_MODEL = self.RERANKER_MODEL_NAME
        self.SGLANG_RERANKER_PORT = 30002
        self.SGLANG_RERANKER_DEVICE = "cuda:1"
        self.SGLANG_RERANKER_MEM_FRACTION = 0.15                   # cuda:1 공유

        # ── 2-4. 리파이너 (Refiner) ─────────────────
        self.REFINER_MODEL = "Qwen/Qwen3-1.7B-FP8"                # ~2GB
        self.SGLANG_REFINER_ENDPOINT = os.getenv("SGLANG_REFINER_ENDPOINT", "http://localhost:30003")
        self.SGLANG_REFINER_MODEL = self.REFINER_MODEL
        self.SGLANG_REFINER_PORT = 30003
        self.SGLANG_REFINER_DEVICE = "cuda:1"
        self.SGLANG_REFINER_MEM_FRACTION = 0.1                    # cuda:1 공유

        # ── 2-5. 쿼리 리라이터 (Query Rewriter) ─────
        self.QUERY_REWRITE_MODEL_NAME = "NEXTITS/Qwen3-0.6B-SFT-No.952"  # ~1.2GB
        self.SGLANG_QUERY_REWRITER_ENDPOINT = os.getenv("SGLANG_QUERY_REWRITER_ENDPOINT", "http://localhost:30004")
        self.SGLANG_QUERY_REWRITER_MODEL = self.QUERY_REWRITE_MODEL_NAME
        self.SGLANG_QUERY_REWRITER_PORT = 30004
        self.SGLANG_QUERY_REWRITER_DEVICE = "cuda:1"
        self.SGLANG_QUERY_REWRITER_MEM_FRACTION = 0.1             # cuda:1 공유

        # ── 2-6. HopClassifier (생성기 서버 공유) ───
        self.HOP_CLASSIFIER_MODEL = self.LLM_MODEL
        self.HOP_CLASSIFIER_SGLANG_ENDPOINT = self.SGLANG_GENERATOR_ENDPOINT
        self.HOP_CLASSIFIER_API_KEY = "EMPTY"
        self.HOP_CLASSIFIER_MAX_TOKENS = 64
        self.HOP_CLASSIFIER_TIMEOUT = 15

        # ── 2-7. 그래프 추출기 (Graph Extractor, 생성기 서버 공유) ──
        self.GRAPH_EXTRACTOR_MODEL = self.LLM_MODEL
        self.GRAPH_EXTRACTOR_ENDPOINT = self.SGLANG_GENERATOR_ENDPOINT
        self.GRAPH_EXTRACTOR_API_TIMEOUT = int(os.getenv("GRAPH_EXTRACTOR_API_TIMEOUT", "60"))
        self.GRAPH_EXTRACTOR_CHUNK_SIZE = int(os.getenv("GRAPH_EXTRACTOR_CHUNK_SIZE", "800"))

        # ── 2-8. 마인드맵 / 요약 (sgl.Engine in-process, LazyModelManager 관리) ──
        self.MINDMAP_MODEL = "Qwen/Qwen3-8B"
        self.MINDMAP_DEVICE = "cuda:0"
        self.MINDMAP_MEM_FRACTION = 0.5
        self.MINDMAP_MAX_TOKENS = 8192
        self.MINDMAP_TOKEN_BUFFER = 500

        #############################################
        # 3. 모델 파라미터 설정
        #############################################
        # 임베딩 파라미터
        self.VECTOR_DIMENSION = 2560  # Qwen3-Embedding-4B 모델의 임베딩 차원
        self.MAX_LENGTH = 512  # 최대 텍스트 길이
        
        # 생성기(GENERATOR) 파라미터
        self.GENERATOR_MAX_TOKENS = 4096
        self.GENERATOR_TEMPERATURE = 0.6  
        self.GENERATOR_TOP_P = 0.9
        self.GENERATOR_TOP_K = 3
        self.GENERATOR_DO_SAMPLE = True
        self.GENERATOR_NUM_BEAMS = 1
        self.GENERATOR_PAD_TOKEN_ID = None
        self.GENERATOR_ENABLE_THINKING = False
        self.MODEL_TIMEOUT = 180

        # 리랭커 파라미터
        self.RERANKER_BATCH_SIZE = 4
        self.RERANKER_USE_FP16 = True
        
        # 정제 파라미터
        self.REFINER_MAX_TOKENS = 8192
        self.REFINER_TEMPERATURE = 0.3
        self.REFINER_TOP_P = 0.9
        self.REFINER_DO_SAMPLE = True
        self.REFINER_NUM_BEAMS = 1
        self.REFINER_PAD_TOKEN_ID = None
        self.REFINER_MODEL_TIMEOUT = 180
        
        # 기본 모델 파라미터
        self.BATCH_SIZE = 4
        self.GENERATOR_TORCH_DTYPE = "auto"

        #############################################
        # 5. 파이프라인 설정
        #############################################
        # 파이프라인 설정
        self.debug_mode = False
        self.use_feedback_loop = False  # Disabled feedback loop to save resources
        self.use_refiner = False        # Explicitly disabled
        self.use_query_rewriter = False  # 쿼리 리라이터 비활성화
        self.separate_image_text_results = True  # 이미지와 텍스트 결과 분리 여부

        # 메모리 관리 설정
        self.memory_management = {
            "auto_cleanup": True,
            "cleanup_threshold": 0.8  # GPU 메모리 사용률 80% 이상일 때 정리
        }

        #############################################
        # 6. 그래프 RAG / LangGraph 설정
        #############################################
        self.GRAPH_RAG_ENABLED = os.getenv("GRAPH_RAG_ENABLED", "true").lower() == "true"
        self.LANGGRAPH_ENABLED = os.getenv("LANGGRAPH_ENABLED", "true").lower() == "true"
        self.GOT_MODE_ENABLED = os.getenv("GOT_MODE_ENABLED", "true").lower() == "true"
        self.GRAPH_MAX_HOPS = int(os.getenv("GRAPH_MAX_HOPS", "6"))

        # GoT (Graph of Thought) 세부 설정
        self.GOT_MAX_STEPS = int(os.getenv("GOT_MAX_STEPS", "5"))
        self.GOT_BRANCH_FACTOR = int(os.getenv("GOT_BRANCH_FACTOR", "3"))       # 각 단계에서 동시 탐색할 thought 분기 수
        self.GOT_MERGE_STRATEGY = os.getenv("GOT_MERGE_STRATEGY", "top_k")      # "top_k" | "weighted_union" | "vote"
        self.GOT_MERGE_TOP_K = int(os.getenv("GOT_MERGE_TOP_K", "1"))           # top_k 병합 시 선택할 상위 thought 수
        self.GOT_THOUGHT_SCORE_THRESHOLD = float(os.getenv("GOT_THOUGHT_SCORE_THRESHOLD", "0.3"))  # thought 최소 품질 임계값
        self.GOT_EDGE_PRUNE_THRESHOLD = float(os.getenv("GOT_EDGE_PRUNE_THRESHOLD", "0.2"))        # 엣지 가지치기 임계값
        self.GOT_MAX_CONSECUTIVE_FAILURES = int(os.getenv("GOT_MAX_CONSECUTIVE_FAILURES", "2"))     # 연속 실패 시 백트래킹
        self.GOT_OBSERVER_ENDPOINT = os.getenv("GOT_OBSERVER_ENDPOINT", "")      # GoT 전용 관찰자 LLM 엔드포인트 (빈 문자열이면 HOP_CLASSIFIER 공유)
        self.GOT_OBSERVER_MODEL = os.getenv("GOT_OBSERVER_MODEL", "")            # GoT 전용 관찰자 모델명
        
        # Quality Gate & Backtracking 설정
        self.QUALITY_GATE_THRESHOLD = float(os.getenv("QUALITY_GATE_THRESHOLD", "0.3"))  # 품질 게이트 통과 임계값
        self.MAX_BACKTRACK_COUNT = int(os.getenv("MAX_BACKTRACK_COUNT", "2"))            # 최대 백트래킹 횟수
        
        #############################################
        # 6-1. Tool Calling & MCP 서버 설정
        #############################################
        self.TOOL_CALLING_ENABLED = os.getenv("TOOL_CALLING_ENABLED", "true").lower() == "true"
        self.MCP_SERVER_ENABLED = os.getenv("MCP_SERVER_ENABLED", "false").lower() == "true"
        self.MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
        self.MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "30"))
        
        # Tool Router 의도 분류 설정
        self.TOOL_INTENT_CLASSIFIER_ENDPOINT = self.SGLANG_GENERATOR_ENDPOINT  # hop classifier와 동일한 LLM 사용
        self.TOOL_INTENT_CLASSIFIER_MODEL = self.LLM_MODEL
        self.TOOL_INTENT_CLASSIFIER_TIMEOUT = 10
        
        #############################################
        # 7. API 엔드포인트 설정
        #############################################
        self.API_BASE_URL = "/api"
        
        #############################################
        # 4. 검색 및 리랭킹 설정
        #############################################
        # 벡터 검색 설정
        self.TEXT_TOP_K = 5  # 텍스트 검색 결과 수 (7 -> 5)
        self.TEXT_FINAL_K = 3  # 텍스트 리랭킹 후 최종 결과 수
        self.IMAGE_TOP_K = 3  # 이미지 검색 초기 결과 수 (5 -> 3, 속도 향상)
        self.IMAGE_FINAL_K = 3  # 이미지 리랭킹 후 최종 결과 수
        self.TOP_K = 3  # 기존 호환성을 위한 기본값
        self.RELEVANCE_THRESHOLD = 0.3  # 텍스트 검색 임계값 (0.5 -> 0.3)
        self.TEXT_RERANKER_TOKEN_FALSE_ID = 2152  # no
        
        # 이미지 리랭커 토큰 ID
        self.IMAGE_RERANKER_TOKEN_TRUE_ID = 9693   # yes
        self.IMAGE_RERANKER_TOKEN_FALSE_ID = 2152  # no
        
        # 가중치 설정
        self.SEMANTIC_WEIGHT = 0.5
        self.KEYWORD_WEIGHT = 0.5
        
        # 이미지 관련 설정
        self.IMAGE_THRESHOLD = 0.5  # 이미지 검색 임계값 (벡터 유사도 기준)
        self.IMAGE_RERANK_SCORE_THRESHOLD = 0.7  # 이미지 리랭크 점수 임계값 (소프트맥스 확률 기준, 70% 이상 확신)
        self.IMAGE_RELEVANCE_THRESHOLD = 0.7   # 이미지 관련성 임계값
        self.IMAGE_RERANK_AMPLIFICATION = 1.5  # 시그모이드 증폭 계수
        self.CAPTION_WEIGHT = 8.0      # 이미지 캡션 가중치
        self.TAG_WEIGHT = 2.0         # 이미지 태그 가중치
        
        #############################################
        # 5. 쿼리 리라이팅 설정
        #############################################
        self.ENABLE_QUERY_REWRITE = False  # Explicitly disabled
        
        #############################################
        # 5-1. 프롬프트 템플릿 설정
        #############################################
        self.PROMPT_TEMPLATES = {
            "system": (
                "You are an AI assistant that answers user questions using ONLY the provided documents. The documents include both text and images.\n"
                "You MUST strictly follow the rules below when generating your response.\n"
                "\n"
                "**🎯 Core Rules**\n"
                "- **ONLY use information explicitly present** in the provided documents. Do not use any external knowledge or make assumptions.\n"
                "- If the answer cannot be found in the documents, respond with **'제공된 자료에서 해당 정보를 찾을 수 없습니다.'** and nothing else.\n"
                "- Do NOT describe the contents of images. (e.g., 'In the image...', 'The photo shows...')\n"
                "- Do NOT include metadata like similarity scores, filenames, or page numbers in your answer.\n"
                "- Your response **MUST be in Korean ONLY.** Do not use any English.\n"
                "\n"
                "**✍️ Response Format Guidelines**\n"
                "- Write your output in **Markdown format** and do not use code blocks.\n"
                "- Use `#` and `##` for headings to improve readability, and separate paragraphs with a blank line.\n"
                "- **Bold** key terms and use `-` or numbered lists to organize information clearly.\n"
                "- If the user asks for a comparison, pros and cons, or a table, you **MUST** use a **Markdown table**.\n"
                "- Structure your answer with a 'Summary' and 'Detailed Explanation'. Keep it concise and to the point, avoiding unnecessary introductions or conclusions.\n"
                "\n"
                "**📚 Source Citation Rules**\n"
                "- If the retrieved documents contain source URLs or links (e.g., 'source_url', 'link', 'url' fields), you **MUST** include a '### 📎 출처' section at the END of your response.\n"
                "- Format each source as a Markdown hyperlink: `- [Source Title or URL](URL)`\n"
                "- If NO source URLs are available in the documents, do NOT include the '### 📎 출처' section at all.\n"
                "- Only include sources that were actually used to answer the question.\n"
                "\n"
                "**✅ Example Response Structure**\n"
                "### 💡 핵심 요약\n"
                "A 3-5 sentence summary of the answer to the question.\n"
                "\n"
                "### 📝 상세 설명\n"
                "A detailed, step-by-step or itemized explanation of the core content. Use bullet points and bolding where necessary.\n"
                "\n"
                "### 📎 출처 (Only if source URLs are available)\n"
                "- [Source 1 Title](https://example.com/source1)\n"
                "- [Source 2 Title](https://example.com/source2)\n"
            ),
            "user": "Question: \n{query} \n\nRetrieved documents:\n{context}\n\nresponse: "
        }
        
        # 2025. 08. 18 프롬프트
        #"system": "You are an AI assistant. Your goal is to answer the user's question using the documents below.\n"
                    # "- Each document has a field called con_type which is either 'text' or 'image'.\n"
                    # "- Each document, including images, is provided with a similarity field, indicating its relevance to the user's question.\n"
                    # "- For text documents, prioritize using data blocks where the similarity is close to 1 to build the answer, ensuring the most relevant information is utilized. Aim to provide a comprehensive answer from these text documents.\n"
                    # "- **The provided documents may contain tables in Markdown format. Interpret the rows and columns of the table to accurately answer the question.**\n"
                    # "- Do NOT describe the contents of the image.\n"
                    # "- Do not display metadata such as similarity score, document name, or page number in the response.\n"
                    # "- **STRICT RULE: You MUST ONLY use information that is explicitly present in the provided documents. Do NOT use your general knowledge, make assumptions, or provide information from outside sources.**\n"
                    # "- **If ANY part of the answer cannot be found in the provided documents, you MUST respond with ONLY: '제공된 자료에서 해당 정보를 찾을 수 없습니다.' Do NOT attempt to answer partially or provide general explanations.**\n"
                    # "- **NEVER combine document information with your general knowledge. If the documents are incomplete or unclear, still respond with '제공된 자료에서 해당 정보를 찾을 수 없습니다.'**\n"
                    # "- You MUST respond in Korean ONLY. Do not use English or any other language. All explanations, terms, and sentences must be in Korean. This is an absolute rule that must be followed.\n"
                    # "When writing the answer, strictly follow the structure below to ensure a clear and logical GPT-style response:\n"
                    # "1. Briefly summarize the intent of the question (1 sentence)\n"
                    # "2. Key answer (3–5 concise lines)\n"
                    # "3. Detailed explanation\n"
                    # "- Use numbered lists and bullet points for step-by-step clarity\n"
                    # "- Highlight important terms in **bold**\n"
                    # "4. Final conclusion (one-sentence key takeaway)\n"
                    # "**IMPORTANT: Only follow this structure if you can answer the question completely using the provided documents. If not, respond only with '제공된 자료에서 해당 정보를 찾을 수 없습니다.'**\n"
                    # "Write the answer in a professional, structured, and concise manner, similar to an expert Q&A report, with no unnecessary content."
        # "You are an AI assistant. Your goal is to answer the user's question using the documents below.\n - Each document has a field called con_type which is either 'text' or 'image'.\n - Each document, including images, is provided with a similarity field, indicating its relevance to the user's question.\n - For text documents, **prioritize using data blocks where the similarity is close to 1** to build the answer, ensuring the most relevant information is utilized. Aim to provide a comprehensive answer from these text documents.\n - Do NOT describe the contents of the image.\n - Do not display metadata such as similarity score, document name, or page number in the response.\n - Exclude images that are only tangentially related, redundant, or do not add significant value to the answer beyond the specified similarity and relevance criteria.\n - If the answer is not found in the documents, respond: '제공된 자료에서 해당 정보를 찾을 수 없습니다.'\n - You MUST respond in Korean ONLY. Do not use English or any other language. All explanations, terms, and sentences must be in Korean. This is an absolute rule that must be followed. ",
        
        #############################################
        # 6. API 및 토큰 설정
        #############################################
        self.HF_TOKEN = "REMOVED_SECRET"
        self.OLLAMA_API_URL = "http://localhost:11434"
        self.GENERATE_ENDPOINT = "/api/generate"
        
        #############################################
        # 7. 디바이스 설정
        #    - SGLang 서버 디바이스는 섹션 2에서 관리
        #    - 아래는 하위 호환성을 위한 참조 설정
        #############################################
        cuda_available = bool(torch and hasattr(torch, "cuda") and torch.cuda.is_available())
        self.DEVICE = "cuda" if cuda_available else "cpu"

        # 하위 호환성: 섹션 2의 SGLang 디바이스 설정을 참조
        self.TEXT_GENERATOR_DEVICE = self.SGLANG_GENERATOR_DEVICE
        self.RERANKER_DEVICE = self.SGLANG_RERANKER_DEVICE
        self.REFINER_DEVICE = self.SGLANG_REFINER_DEVICE
        self.QUERY_REWRITER_DEVICE = self.SGLANG_QUERY_REWRITER_DEVICE
        self.EMBEDDING_DEVICE = self.SGLANG_EMBEDDING_DEVICE
        self.TEXT_EMBEDDING_DEVICE = self.EMBEDDING_DEVICE
        self.IMAGE_EMBEDDING_DEVICE = self.EMBEDDING_DEVICE
        
        #############################################
        # 7-1. Search 시스템 설정
        #############################################      
        # Google Search API 설정
        self.ENABLE_GOOGLE_SEARCH = True
        self.GOOGLE_API_KEY = "REMOVED_SECRET"
        self.GOOGLE_CX_ID = "f00b2a2eaff4b4fbf"
        
        # 연결 관리 설정
        self.SEARCH_CONNECTION_TIMEOUT = 10  # 연결 타임아웃 (초)
        self.SEARCH_READ_TIMEOUT = 30  # 읽기 타임아웃 (초)
        self.SEARCH_CLOSE_CONNECTION = True  # 요청 후 연결 즉시 종료
        
        # 요약 모델 설정 (md_summarizer 사용)
        self.SUMMARIZER_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
        self.SUMMARIZER_DEVICE = "cuda" if cuda_available else "cpu"
        self.SEARCH_CHUNK_LENGTH = 3600  # 크롤링 데이터 나눠서 요약할 크기
        
        # 크롤링 설정
        self.MAX_CRAWL_DEPTH = 2
        self.CRAWL_DELAY = 1.0  # 크롤링 간 대기 시간 (초)
        
        # Search 디렉토리 생성
        
        #############################################
        # 8. 프롬프트 설정
        #############################################
        self.REFINER_SYSTEM_PROMPT = """
            Transform RAG answers into beautifully formatted Markdown for user display.
            CRITICAL: Output ONLY pure Markdown text. Do NOT use markdown or code blocks.
            ***You MUST respond in Korean ONLY. Do not use English or any other language. All explanations, terms, and sentences must be in Korean.***

            📋 Your Task
                Convert the original answer into visually appealing, well-structured Markdown while preserving all key information.

            ✅ Requirements
            1. Pure Markdown Output
                Use only Markdown syntax (no code blocks).

            2. Beautiful Structure with Proper Line Breaks
                Use #, ##, ### headings to organize content clearly.
                Add relevant emojis to headings and key points.
                ALWAYS add blank lines between different sections.
                ALWAYS add blank lines between headings and content.
                Tables → must be Markdown tables, with proper line breaks inside cells.
                Lists → use bullet points (-) or numbered lists.
                Each list item must be on a separate line.
                Add blank lines between different groups of content (text, lists, tables).

            3. Strict Line Break Rules
                Insert a blank line after every heading.
                Insert a blank line between sections.
                Each bullet point must be on its own line.
                Add blank lines between different content types (paragraphs, lists, tables).
                Use double blank lines to separate major sections.

            4. Table Formatting (CRITICAL)
                If table content contains multiple items, each item must appear on a new line within the same cell.
                Never collapse multiple list items into a single line.
                Example of correct formatting:
                Category	Details
                🎵 Major Albums	- Heartbreaker (2009)
                One Of A Kind (2012)
                Coup D'etat (2013)
                POWER (2025) |
                | 📺 Music Show Wins | - Heartbreaker → 11 wins
                Coup D'etat → 4 wins
                HOME SWEET HOME → 4 wins |
                | 🌍 Billboard Rankings | - One Of A Kind → #161
                Coup D'etat → #182
                POWER → #29
                HOME SWEET HOME → #27 |

            5. Visual Enhancement
                Add emojis that match the context.
                Use bold and italic for emphasis.
                Ensure consistent spacing.

            6. Remove Redundancy
                Delete repetitive or unnecessary phrases.

            7. Keep Content
                Preserve all important information.
                ✨ Example Structure
                🎯 Main Topic
                📋 Key Information
                📌 Important point
                ✅ Another key point
                💡 Details
                Bold key concepts and use emojis appropriately.
                👉 This ensures perfect Markdown rendering with strict line-break handling, especially for tables with multiple items per cell. 
            """
                        
        
        # REFINER_SYSTEM_PROMPT 이전 버전전
        # self.REFINER_SYSTEM_PROMPT = """
        #     Transform RAG answers into beautifully formatted Markdown for user display.

        #     CRITICAL: Output ONLY pure Markdown text. Do NOT use ```markdown or ``` code blocks.

        #     ### Your Task
        #     Convert the original answer into visually appealing, well-structured Markdown while preserving all key information.

        #     ### Requirements
        #     1. **Pure Markdown Output**: Write direct Markdown text, not code blocks

        #     2. **Beautiful Structure with Proper Line Breaks**: 
        #     - Use # ## ### headings to organize content clearly
        #     - Add relevant emojis to headings and key points
        #     - ALWAYS add blank lines between different sections
        #     - ALWAYS add blank lines between headings and content
        #     - Tables → Markdown tables with proper formatting
        #     - Lists → bullet points or numbered lists with emojis where appropriate
        #     - Each list item should be on a separate line
        #     - Add blank lines between different list groups

        #     3. **Strict Line Break Rules**:
        #     - Insert blank line after each heading
        #     - Insert blank line between different sections
        #     - Each bullet point must be on its own line
        #     - Add blank line between different types of content (text, lists, tables)
        #     - Use double line breaks (blank lines) to separate major sections

        #     4. **Visual Enhancement**:
        #     - Add emojis that match the content context
        #     - Use **bold** and *italic* for emphasis
        #     - Create clear section breaks with headings
        #     - Ensure consistent spacing throughout

        #     5. **Remove Redundancy**: Delete repetitive sentences and unnecessary phrases

        #     6. **Keep Content**: Preserve all important information

        #     ### Example Structure:
        #     # 🎯 Main Topic
        #     ## 📋 Key Information
        #     - 📌 Important point
        #     - ✅ Another point
        #     ## 💡 Details
        #     **Bold key concepts** and use emojis appropriately.
        #     """

        self.REFINER_USER_PROMPT_TEMPLATE = """
            ### Original Answer:
            {answer}

            ### Refined Answer:
        """
        
        #############################################
        # 9. 시스템 초기화
        #############################################
        # PyTorch 메모리 최적화 설정
        self._setup_memory_optimization()
        
        # 초기화 완료 표시
        self._initialized = True
    
    def get_session_dir(self, session_id: str) -> Path:
        """세션별 전용 디렉토리 경로 반환 및 생성"""
        session_dir = self.SESSIONS_ROOT / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def get_session_doc_dir(self, session_id: str) -> Path:
        """세션별 문서 디렉토리 경로 반환 및 생성"""
        doc_dir = self.get_session_dir(session_id) / "doc"
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir

    def get_session_metadata_file(self, session_id: str) -> Path:
        """세션별 메타데이터 파일 경로 반환"""
        metadata_dir = self.get_session_doc_dir(session_id) / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        return metadata_dir / "file_metadata.json"

    def get_session_results_dir(self, session_id: str, result_type: str) -> Path:
        """세션별 결과물(OCR, 요약 등) 디렉토리 경로 반환 및 생성"""
        results_dir = self.get_session_dir(session_id) / "Results" / result_type
        results_dir.mkdir(parents=True, exist_ok=True)
        return results_dir
    def _setup_memory_optimization(self):
        """메모리 최적화 설정"""
        import os
        
        # PyTorch CUDA 메모리 할당 최적화
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True,max_split_size_mb:512'
        
        # Hugging Face 모델 캐시 설정
        # os.environ['TRANSFORMERS_CACHE'] = '/tmp/transformers_cache'
        
        # CUDA 커널 시작 시간 감소
        os.environ['CUDA_LAUNCH_BLOCKING'] = '0'
        
        logger.info("메모리 최적화 설정 완료")

    
    @classmethod
    def load_embedding_model(cls, model_name=None, device=None, use_fp16=True, cache_dir=None):
        """임베딩 모델 로드 - SharedEmbeddingModel 사용으로 변경"""
        logger.warning("RAGConfig.load_embedding_model()은 deprecated되었습니다. SharedEmbeddingModel을 사용하세요.")
        
        # SharedEmbeddingModel 인스턴스 반환
        from shared_embedding import SharedEmbeddingModel
        shared_model = SharedEmbeddingModel()
        shared_model.load_model()
        
        # 하위 호환성을 위해 더미 토크나이저 반환
        return shared_model._model, None
    
    @classmethod
    def unload_embedding_model(cls):
        """임베딩 모델 언로드 - SharedEmbeddingModel 사용으로 변경"""
        logger.warning("RAGConfig.unload_embedding_model()은 deprecated되었습니다. SharedEmbeddingModel.cleanup()을 사용하세요.")
        
        # SharedEmbeddingModel 정리
        from shared_embedding import SharedEmbeddingModel
        shared_model = SharedEmbeddingModel()
        shared_model.cleanup()
        
        return True
        
    @classmethod
    def get_weaviate_client(cls):
        """Weaviate 클라이언트 초기화 및 반환"""
        config = cls()
        try:
            # Weaviate 클라이언트 초기화
            import weaviate
            from weaviate.classes.init import Auth
            # 버전 확인
            weaviate_version = weaviate.__version__
            logger.info(f"Weaviate 버전: {weaviate_version}")
            
            try:
                # v4 API 사용
                client = weaviate.connect_to_custom(
                    http_host=config.WEAVIATE_HOST,
                    http_port=config.WEAVIATE_PORT,
                    http_secure=False,
                    grpc_host=config.WEAVIATE_HOST,
                    grpc_port=50051,
                    grpc_secure=False
                )
            except Exception as e:
                logger.error(f"Weaviate 클라이언트 초기화 오류: {e}")
                return None
            logger.info(f"Weaviate 클라이언트 연결 성공: {config.WEAVIATE_URL} (버전: {weaviate_version})")
            return client
        except Exception as e:
            logger.error(f"Weaviate 클라이언트 연결 실패: {str(e)}")
            return None
