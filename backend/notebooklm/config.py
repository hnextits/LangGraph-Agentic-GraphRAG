import os
import json
import logging
import torch
from pathlib import Path


# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 특정 모듈의 로그 레벨 조정
logging.getLogger('transformers').setLevel(logging.WARNING)
logging.getLogger('faiss').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('filelock').setLevel(logging.WARNING)
logging.getLogger('huggingface_hub').setLevel(logging.WARNING)

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
        current_file = Path(__file__).resolve()
        self.PROJECT_ROOT = current_file.parent.parent.parent
        self.DATA_PATH = self.DATA_PATH = self.PROJECT_ROOT / "data" / "nextits_data"
        self.INDEX_DIR = os.path.join(os.path.dirname(__file__), "faiss_test")
        self.CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"
        
        #############################################
        # 1-1. Weaviate 설정
        #############################################
        # Weaviate 호스트 설정 - 로컬호스트 사용
        self.WEAVIATE_HOST = "127.0.0.1"
        self.WEAVIATE_PORT = 8080
        self.WEAVIATE_URL = f"http://{self.WEAVIATE_HOST}:{self.WEAVIATE_PORT}"
        self.WEAVIATE_BATCH_SIZE = 100
        self.WEAVIATE_TEXT_CLASS = "TextDocument"
        self.WEAVIATE_IMAGE_CLASS = "ImageDocument"
        self.WEAVIATE_VECTORIZER = "text2vec-model2vec"  # 컨테이너에서 설정한 vectorizer
        
        #############################################
        # 2. 모델 설정 (모델 이름)
        #############################################
        # 임베딩 모델
        self.EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"
        
        # 리랭커 모델
        self.RERANKER_MODEL_NAME = "Qwen/Qwen3-Reranker-4B"
        
        # 쿼리 리라이터 모델
        self.QUERY_REWRITE_MODEL_NAME = "NEXTITS/Qwen3-0.6B-SFT-No.952"
        
        # 생성 모델
        self.LLM_MODEL = "Qwen/Qwen3-8B"
        
        # 정제 모델
        self.REFINER_MODEL = "Qwen/Qwen3-1.7B-FP8"
        
        # 마인드맵 생성 모델 (요약 모델과 동일)
        self.MINDMAP_MODEL = "Qwen/Qwen3-8B"
        
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
        self.GENERATOR_DO_SAMPLE = True  # 샘플링 활성화
        
        # SGLang 설정 - Engine API 직접 사용
        self.SGLANG_USE_DIRECT_ENGINE = True  # SGLang Engine API 직접 사용
        self.GENERATOR_NUM_BEAMS = 1     # 빔 서치 비활성화 (그리디 서치)
        self.GENERATOR_PAD_TOKEN_ID = None  # 토크나이저에서 설정
        self.GENERATOR_ENABLE_THINKING = False
        self.MODEL_TIMEOUT = 180

        # 리랭커 파라미터
        self.RERANKER_BATCH_SIZE = 4
        self.RERANKER_USE_FP16 = True
        
        # 정제 파라미터
        self.REFINER_MAX_TOKENS = 8192
        self.REFINER_TEMPERATURE = 0.3
        self.REFINER_TOP_P = 0.9
        self.REFINER_DO_SAMPLE = True    # 샘플링 활성화
        self.REFINER_NUM_BEAMS = 1       # 빔 서치 비활성화 (그리디 서치)
        self.REFINER_PAD_TOKEN_ID = None # 토크나이저에서 설정
        self.REFINER_MODEL_TIMEOUT = 180  # 5분 후 자동 언로드
        
        # 기본 모델 파라미터
        self.BATCH_SIZE = 4
        self.GENERATOR_TORCH_DTYPE = "auto"  # bfloat16에서 auto로 변경하여 한국어 텍스트 깨짐 방지
        
        # 마인드맵 생성 파라미터
        self.MINDMAP_DEVICE = "cuda:0"
        self.MINDMAP_MEM_FRACTION = 0.5  # GPU 메모리 50% 사용
        self.MINDMAP_MAX_TOKENS = 8192
        self.MINDMAP_TOKEN_BUFFER = 500

        #############################################
        # 5. 파이프라인 설정
        #############################################
        # 파이프라인 설정
        self.debug_mode = False
        self.use_feedback_loop = True
        self.use_refiner = False
        self.separate_image_text_results = True  # 이미지와 텍스트 결과 분리 여부
        
        # 메모리 관리 설정
        self.memory_management = {
            "auto_cleanup": True,
            "cleanup_threshold": 0.8  # GPU 메모리 사용률 80% 이상일 때 정리
        }
        
        #############################################
        # 6. API 엔드포인트 설정
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
        self.ENABLE_QUERY_REWRITE = False  # 쿼리 리라이팅 비활성화 (속도 향상)
        
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
        #############################################
        # 기본 디바이스 설정
        self.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        
        # ⚠️ 테스트 모드 설정 (GPU 배치 전환)
        # True: SGLang=GPU1, Transformers=GPU0 (테스트용)
        # False: SGLang=GPU0, Transformers=GPU1 (운영용, 기본값)
        TEST_MODE = False
        
        # GPU 분산 배치 설정 (2개 H100 GPU 활용)
        if TEST_MODE:
            # 🧪 테스트 모드: SGLang → GPU 1, Transformers → GPU 0
            logger.info("🧪 TEST MODE: SGLang=GPU1, Transformers=GPU0")
            self.TEXT_GENERATOR_DEVICE = "cuda:1"       # SGLang → GPU 1
            self.RERANKER_DEVICE = "cuda:0"             # 리랭커 → GPU 0
            self.REFINER_DEVICE = "cuda:0"              # 정제 모델 → GPU 0
            self.QUERY_REWRITER_DEVICE = "cuda:0"       # 쿼리 재작성 → GPU 0
            self.EMBEDDING_DEVICE = "cuda:0"            # 임베딩 → GPU 0
        else:
            # 🚀 운영 모드: SGLang → GPU 0, Transformers → GPU 1 (기본값)
            self.TEXT_GENERATOR_DEVICE = "auto"         # SGLang → GPU 0 (auto)
            self.RERANKER_DEVICE = "cuda:1"             # 리랭커 → GPU 1
            self.REFINER_DEVICE = "cuda:1"              # 정제 모델 → GPU 1
            self.QUERY_REWRITER_DEVICE = "cuda:1"       # 쿼리 재작성 → GPU 1
            self.EMBEDDING_DEVICE = "cuda:1"            # 임베딩 → GPU 1
        
        # 하위 호환성 및 명시적 설정
        self.TEXT_EMBEDDING_DEVICE = self.EMBEDDING_DEVICE
        self.IMAGE_EMBEDDING_DEVICE = self.EMBEDDING_DEVICE
        
        #############################################
        # 7-1. Search 시스템 설정
        #############################################
        # 경로 설정
        self.SEARCH_DATA_DIR = self.PROJECT_ROOT / "backend" / "search_data"
        self.CRAWLING_DATA_DIR = self.SEARCH_DATA_DIR / "crawling"
        self.SEARCH_RESULTS_DIR = self.SEARCH_DATA_DIR / "results"
        
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
        self.SUMMARIZER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        self.SEARCH_CHUNK_LENGTH = 3600  # 크롤링 데이터 나눠서 요약할 크기
        
        # 크롤링 설정
        self.MAX_CRAWL_DEPTH = 2
        self.CRAWL_DELAY = 1.0  # 크롤링 간 대기 시간 (초)
        
        # Search 디렉토리 생성
        self._ensure_search_directories()
        
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
    
    def _ensure_search_directories(self):
        """Search 시스템 디렉토리 생성"""
        directories = [
            self.SEARCH_DATA_DIR,
            self.CRAWLING_DATA_DIR,
            self.SEARCH_RESULTS_DIR
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.debug(f"Search 디렉토리 확인: {directory}")
    
    @classmethod
    def load_embedding_model(cls, model_name=None, device=None, use_fp16=True, cache_dir=None):
        """임베딩 모델 로드"""
        # 이미 로드된 모델이 있으면 그것을 반환
        if cls._is_embedding_loaded and cls._embedding_model is not None and cls._embedding_tokenizer is not None:
            logger.debug("이미 로드된 임베딩 모델 사용")
            return cls._embedding_model, cls._embedding_tokenizer
        
        # 설정에서 기본값 가져오기
        config = cls()
        if model_name is None:
            model_name = config.EMBEDDING_MODEL
        if device is None:
            device = config.DEVICE
            
        from transformers import AutoModel, AutoTokenizer
        
        try:
            logger.info(f"임베딩 모델 로드 중: {model_name}")
            
            # 토크나이저 로드
            tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
            
            # GPU 메모리 상태 확인
            if device == "cuda" and torch.cuda.is_available():
                num_gpus = torch.cuda.device_count()
                logger.info(f"사용 가능한 GPU 개수: {num_gpus}")
                
                # 메모리 정보 출력
                for i in range(num_gpus):
                    free_mem, total_mem = torch.cuda.mem_get_info(i)
                    free_gb = free_mem / (1024**3)
                    total_gb = total_mem / (1024**3)
                    logger.info(f"GPU {i}: 사용 가능 메모리 {free_gb:.2f}GB / 전체 {total_gb:.2f}GB")
                
                # 가장 메모리가 많은 GPU 선택
                max_free = 0
                selected_gpu = 0
                for i in range(num_gpus):
                    free_mem, _ = torch.cuda.mem_get_info(i)
                    if free_mem > max_free:
                        max_free = free_mem
                        selected_gpu = i
                
                logger.info(f"선택된 GPU: {selected_gpu} (사용 가능 메모리: {max_free / (1024**3):.2f}GB)")
                device = f"cuda:{selected_gpu}"
            
            # 모델 로드 설정 - float16으로 통일
            model_kwargs = {}
            if device.startswith("cuda") and torch.cuda.is_available():
                model_kwargs["torch_dtype"] = torch.float16  # 모든 GPU 모델을 float16으로 통일
                model_kwargs["device_map"] = "cuda"  # 명시적으로 CUDA 디바이스에 로드
                # device_map="auto" 대신 특정 GPU로 지정
                # model_kwargs["device_map"] = "auto" 
            else:
                model_kwargs["torch_dtype"] = torch.float32  # CPU는 float32 사용
            
            # 메모리 정리
            torch.cuda.empty_cache()
            
            # 모델 로드
            model = AutoModel.from_pretrained(
                model_name, cache_dir=cache_dir, **model_kwargs
            ).to(device)  # 특정 디바이스로 모델 이동
            
            # 로드된 모델을 클래스 변수에 저장
            cls._embedding_model = model
            cls._embedding_tokenizer = tokenizer
            cls._is_embedding_loaded = True
            logger.info("임베딩 모델 로드 완료")
            
            return model, tokenizer
        except Exception as e:
            logger.error(f"임베딩 모델 로드 실패: {str(e)}")
            raise
    
    @classmethod
    def unload_embedding_model(cls):
        """임베딩 모델 언로드"""
        if cls._embedding_model is not None:
            try:
                # 메모리 해제
                del cls._embedding_model
                del cls._embedding_tokenizer
                cls._embedding_model = None
                cls._embedding_tokenizer = None
                cls._is_embedding_loaded = False
                
                # 메모리 정리
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                     
                logger.info("임베딩 모델 언로드 완료")
                return True
            except Exception as e:
                logger.error(f"임베딩 모델 해제 실패: {str(e)}")
        return False
        
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
