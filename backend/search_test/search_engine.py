"""
Google Search API 불러오는 클래스
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class GoogleSearchClient:
    """
    Google Custom Search JSON API 클라이언트
    """

    def __init__(self, api_key: str, cx_id: str):
        """
        생성자
        Args:
            api_key (str): Google 검색 API 키
            cx_id (str): 검색 엔진 ID (CX)
        """
        self.api_key = api_key
        self.cx_id = cx_id
        self.base_url = "https://www.googleapis.com/customsearch/v1"

    def search(self, query: str, extra_params: dict = None, timeout_config: dict = None) -> dict:
        """
        검색 수행 (연결 관리 개선)

        Args:
            query (str): 검색할 쿼리
            extra_params (dict, optional): 추가 파라미터
            timeout_config (dict, optional): 타임아웃 설정

        Returns:
            dict: 검색 결과 JSON (실패 시 None)
        """
        params = {
            "key": self.api_key,
            "cx": self.cx_id,
            "q": query
        }
        if extra_params:
            params.update(extra_params)

        # 타임아웃 설정 (기본값)
        connect_timeout = 10
        read_timeout = 30
        
        if timeout_config:
            connect_timeout = timeout_config.get('connection_timeout', 10)
            read_timeout = timeout_config.get('read_timeout', 30)

        # 세션 생성 및 연결 관리 설정
        session = requests.Session()
        
        # 연결 풀링 비활성화 및 연결 즉시 종료 설정
        adapter = HTTPAdapter(
            pool_connections=1,  # 연결 풀 최소화
            pool_maxsize=1,      # 최대 연결 수 제한
            max_retries=Retry(total=1, backoff_factor=0.1)
        )
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        
        # Connection: close 헤더 추가 (연결 즉시 종료)
        headers = {
            'Connection': 'close',
            'User-Agent': 'Mozilla/5.0 (compatible; SearchBot/1.0)'
        }

        try:
            response = session.get(
                self.base_url, 
                params=params, 
                timeout=(connect_timeout, read_timeout),
                headers=headers
            )
            response.raise_for_status()
            result = response.json()
            
            # 세션 명시적 종료
            session.close()
            
            return result
            
        except requests.exceptions.RequestException as e:
            print(f"API 요청 중 오류 발생: {e}")
            # 오류 발생 시도 세션 종료
            session.close()
            return None

# --- 사용 예시 ---
if __name__ == "__main__":
    YOUR_API_KEY = "YOUR_API_KEY"
    YOUR_CX_ID = "YOUR_CX_ID"
    client = GoogleSearchClient(YOUR_API_KEY, YOUR_CX_ID)
    result = client.search("한화 이글스", extra_params={"hl": "ko", "lr": "lang_ko", "gl": "kr"})
    if result:
        print(result)
