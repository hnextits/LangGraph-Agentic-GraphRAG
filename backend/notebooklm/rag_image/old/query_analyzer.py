import re
import logging
import json
import os
import requests
import time
import tempfile
import subprocess
from typing import Dict, List, Any, Optional, Tuple

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class QueryAnalyzer:
    def __init__(self, config_path: str = None):
        """
        쿼리 분석기 초기화
        
        Args:
            config_path: 설정 파일 경로
        """
        self.config = self._load_config(config_path)
        self.ollama_url = self.config.get("ollama_url", "http://localhost:11434")
        self.model_name = self.config.get("model_name", "qwen3:4b")
        
        # Ollama 모델 가용성 확인
        self._check_model_availability()
        
        logger.info(f"쿼리 분석기 초기화 완료: {self.model_name}")
    
    def _load_config(self, config_path: str = None) -> Dict[str, Any]:
        """
        설정 파일 로드
        
        Args:
            config_path: 설정 파일 경로
            
        Returns:
            설정 딕셔너리
        """
        default_config = {
            "data_types": ["text", "image"],
            "ollama_url": "http://localhost:11434",
            "model_name": "qwen3:4b",
            "timeout": 10,
            "max_retries": 2,
            "temperature": 0.1,
            "top_p": 0.95,
            "system_prompt": "당신은 사용자 질문에 대한 최적의 설명 방식을 판단하여 필요한 어떤 데이터 타입(text, image)이 필요한지 판단하는 전문가입니다."
        }
        
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info(f"설정 파일 로드 완료: {config_path}")
                return config
            except Exception as e:
                logger.error(f"설정 파일 로드 실패: {str(e)}")
        
        logger.info("기본 설정 사용")
        return default_config
    
    def _check_model_availability(self) -> bool:
        """
        Ollama 모델 가용성 확인
        
        Returns:
            모델 사용 가능 여부
        """
        try:
            url = f"{self.ollama_url}/api/tags"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                models = response.json().get("models", [])
                available_models = [model.get("name") for model in models]
                if self.model_name in available_models:
                    logger.info(f"모델 확인 완료: {self.model_name}")
                    return True
                else:
                    logger.warning(f"모델 {self.model_name}이(가) Ollama에 없습니다. 사용 가능한 모델: {available_models}")
            else:
                logger.warning(f"Ollama API 응답 오류: {response.status_code}")
        except Exception as e:
            logger.error(f"Ollama 연결 오류: {str(e)}")
        
        return False
    
    def analyze(self, query: str) -> Dict[str, Any]:
        """
        질문 분석
        
        Args:
            query: 사용자 질문
            
        Returns:
            분석 결과 딕셔너리 (데이터 타입 점수, 의도, 키워드 등)
        """
        # Ollama 모델을 사용하여 분석
        return self._analyze_with_ollama(query)

    def _analyze_with_ollama(self, query: str) -> Dict[str, Any]:
        """
        Ollama 모델을 사용한 질문 분석 (최적화된 버전)
        
        Args:
            query: 사용자 질문
            
        Returns:
            분석 결과 딕셔너리
        """
        
        # 도메인 전문성을 고려한 최적화된 프롬프트
        prompt_template = """
            다음은 사용자의 질문입니다: %s
            당신은 질문에 가장 적절한 데이터 타입을 판단하고, 질문 속 핵심 전문 키워드를 추출하는 전문가입니다.

            아래 기준에 따라 각 데이터 타입(text, image)을 0.0~1.0 사이 점수로 평가하고,  
            도메인을 추정한 뒤 그 도메인 분류에 가장 결정적인 영향을 준 키워드들만 추출하여 명사형으로 keyword에 넣어주세요.
            ---

            [출력 형식]
            정확히 하나의 JSON 객체만 출력하세요.
            **만약 도메인을 알 수 없다면 domain 항목과 keyword항목은 빈 문자열("") 또는 빈 리스트([])로 비워두세요.**

            [데이터 타입 평가 기준]

            1. TEXT: 설명, 정의, 개념이 필요한 질문 (예: "무엇인가요", "정의", "원리")
            2. IMAGE: 시각 자료가 필요한 질문 (예: "그림", "그래프", "사진", "구조도", "시각화")

            **중요: 전문 도메인 용어 보너스 적용**

            회계/금융 전문용어 감지시 → IMAGE +0.4, TEXT +0.3 보너스
            - 용어: BEP, 손익분기점, ROI, NPV, IRR, 재무제표, 손익계산서, 대차대조표, 현금흐름표, 매출총이익, 순이익, 자기자본비율, 부채비율, 유동비율, 당좌비율, 회전율, CVP, cvp

            의료 전문용어 감지시 → IMAGE +0.5, TEXT +0.2 보너스  
            - 용어: MRI, CT, X-ray, 혈압, 당뇨, 고혈압, 콜레스테롤, 심전도, 뇌파, 혈액검사, 소변검사, 내시경, 초음파, 생검, 수술

            법률 전문용어 감지시 → TEXT +0.4 보너스
            - 용어: 계약서, 소송, 판례, 민법, 형법, 상법, 헌법, 계약위반, 손해배상, 이행청구, 법정대리인, 위임장

            제조/공정 전문용어 감지시 → IMAGE +0.5, TEXT +0.3 보너스
            - 용어: 6시그마, 린생산, TPM, 공정개선, 품질관리, 불량률, 수율, QC, QA, FMEA, SPC, 공정능력, 관리도

            IT 전문용어 감지시 → IMAGE +0.4, TEXT +0.2 보너스  
            - 용어: 알고리즘, 데이터베이스, API, 클라우드, 마이크로서비스, 아키텍처, 네트워크, 서버, 백엔드, 프론트엔드, DevOps, CI/CD

            질문에 해당 용어가 포함되면 도메인을 추정하고 보너스를 적용하세요.
            ---

  

            예시:
            json
            {"text": 0.8, "image": 0.3, "domain": "IT", "keywords": ["키워드1", "키워드2"]}
        """
        
        # 쿼리를 프롬프트에 삽입
        prompt = prompt_template % query
        
        # 여러 URL을 시도하는 리스트
        urls_to_try = [
            f"{self.ollama_url}/api/generate",
            "http://localhost:11434/api/generate",
            "http://ollama:11434/api/generate",
            "http://172.19.0.6:11434/api/generate"
        ]
        
        # 기본 페이로드 설정
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "temperature": 0.1,
            "stream": False,
            "options": {
                "num_predict": 500,
                "num_ctx": 2048
            }
        }
        
        # curl 명령어로 시도
        response_text = self._call_ollama_api_with_curl(prompt, payload)
        if response_text:
            # JSON 추출 시도
            json_str = self._extract_json_fast(response_text)
            if json_str:
                try:
                    parsed = json.loads(json_str)
                    logger.debug(f"curl 호출로 JSON 파싱 성공: {parsed}")
                    return self._validate_and_correct_result(parsed, query)
                except json.JSONDecodeError as e:
                    logger.warning(f"curl 응답 JSON 파싱 실패: {e}")
        
        # 분석 실패 시 기본값 반환
        logger.debug("모든 API 호출 방법 실패, 기본값 반환")
        return self._quick_fallback_analysis(query)

    def _extract_json_fast(self, text: str) -> str:
        """빠른 JSON 추출 (개선된 버전 - <think> 태그 처리 추가)"""
        import re
        
        # <think> 태그 처리
        if "<think>" in text:
            logger.debug("<think> 태그 발견, 처리 시도")
            # </think> 태그 이후의 텍스트 추출 시도
            think_end = text.find("</think>")
            if think_end > -1:
                text = text[think_end + 8:].strip()
                logger.debug(f"</think> 이후 텍스트: {text[:50]}...")
        
        # 1. 정규식을 사용하여 중괄호로 둘러싸인 JSON 객체 찾기 시도
        json_pattern = re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}')
        match = json_pattern.search(text)
        if match:
            potential_json = match.group(0)
            try:
                # 유효성 검사
                parsed = json.loads(potential_json)
                logger.debug(f"정규식으로 JSON 추출 성공: {parsed}")
                return potential_json
            except json.JSONDecodeError:
                # 정규식으로 찾은 JSON이 유효하지 않은 경우 다음 방법 시도
                logger.debug("정규식으로 추출한 JSON 파싱 실패, 다음 방법 시도")
                pass
        
        # 2. 중괄호 균형을 맞추는 방식으로 시도
        start = text.find('{')
        if start == -1:
            logger.debug("중괄호 '{'가 없음, 다음 방법 시도")
        else:
            count = 0
            for i, char in enumerate(text[start:], start):
                if char == '{':
                    count += 1
                elif char == '}':
                    count -= 1
                    if count == 0:
                        potential_json = text[start:i+1]
                        try:
                            # 유효성 검사
                            parsed = json.loads(potential_json)
                            logger.debug(f"중괄호 균형으로 JSON 추출 성공: {parsed}")
                            return potential_json
                        except json.JSONDecodeError:
                            # 계속 진행하여 다른 JSON 객체 찾기
                            logger.debug("중괄호 균형으로 추출한 JSON 파싱 실패, 계속 검색")
                            continue
        
        # 3. 마지막 시도: 텍스트에서 값 추출하여 JSON 생성
        logger.debug("정규표현식을 사용하여 값 추출 시도")
        try:
            # 점수 추출 시도
            scores = {}
            for data_type in ["text", "image"]:
                pattern = rf"{data_type}[:\s=]+(\d+\.\d+|\d+)"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    scores[data_type] = float(match.group(1))
                    logger.debug(f"{data_type} 점수 추출: {scores[data_type]}")
                else:
                    scores[data_type] = 0.0
            
            # 키워드 추출 시도
            keywords = []
            keyword_patterns = [
                r"keywords?[:\s=]+\[([^\]]+)\]",  # keywords: [키워드1, 키워드2]
                r"keywords?[:\s=]+(.+?)(?:\.|\n|$)",  # keywords: 키워드1, 키워드2
                r"\[([^\]]+)\]",  # [키워드1, 키워드2]
                r"\"([^\"]+)\""  # "키워드1"
            ]
            
            for pattern in keyword_patterns:
                keyword_match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
                if keyword_match:
                    kw_text = keyword_match.group(1)
                    keywords = [k.strip().strip('"\',') for k in kw_text.split(',')]
                    if keywords:
                        logger.debug(f"키워드 추출: {keywords}")
                        break
            
            # 도메인 추출 시도
            domain = "general"
            domain_patterns = [
                r"domain[:\s=]+(\w+)",  # domain: finance
                r"\b(finance|accounting|medical|legal|manufacturing|it|general)\b"  # 도메인 키워드 직접 찾기
            ]
            
            for pattern in domain_patterns:
                domain_match = re.search(pattern, text.lower(), re.IGNORECASE)
                if domain_match:
                    domain = domain_match.group(1).lower()
                    logger.debug(f"도메인 추출: {domain}")
                    break
            
            # 결과가 충분히 의미 있는지 확인
            if any(scores.values()) or keywords:
                result = {**scores, "domain": domain, "keywords": keywords}
                logger.debug(f"추출된 값으로 JSON 생성: {result}")
                return json.dumps(result)
            else:
                logger.debug("추출된 값이 충분하지 않음")
        except Exception as e:
            logger.debug(f"값 추출 중 오류: {e}")

        
        logger.debug("JSON 추출 실패, None 반환")
        return None

    def _validate_and_correct_result(self, parsed: Dict, query: str) -> Dict[str, Any]:
        """결과 검증 및 자동 보정 (도메인 보너스 점수 적용)"""
        
        # 기본 구조 보장
        result = {
            "query": query,
            "type_scores": {"text": 0.3, "image": 0.0},
            "primary_type": "text",
            "intent": "information",
            "keywords": [],
            "domain": "general",
            "is_professional": False
        }
        
        # 점수 추출 및 검증 (기본 점수)
        if "text" in parsed and isinstance(parsed["text"], (int, float)):
            result["type_scores"]["text"] = max(0.0, min(1.0, float(parsed["text"])))
        if "image" in parsed and isinstance(parsed["image"], (int, float)):
            result["type_scores"]["image"] = max(0.0, min(1.0, float(parsed["image"])))
        
        # 도메인 정보 추출
        if "domain" in parsed:
            result["domain"] = str(parsed["domain"])
        if "keywords" in parsed and isinstance(parsed["keywords"], list):
            # 키워드 리스트에서 쌍따옴표 안에 있는 단어만 추출
            processed_keywords = []
            for k in parsed["keywords"][:5]:
                k_str = str(k)
                # 쌍따옴표 안에 있는 단어 추출 (예: ['here would be "UML" and "다이어그램"])
                if '"' in k_str:
                    # 정규표현식을 사용하여 쌍따옴표 안에 있는 모든 단어 추출
                    import re
                    quoted_words = re.findall(r'"([^"]+)"', k_str)
                    if quoted_words:
                        # 쌍따옴표 안에 있는 단어들을 개별 키워드로 추가
                        processed_keywords.extend(quoted_words)
                        
                        print(f"[DEBUG]원래 키워드 : {k_str}")
                        print(f"[DEBUG]쌍따옴표 안에서 추출된 키워드: {quoted_words}")
                        # logger.debug(f"쌍따옴표 안에서 추출된 키워드: {quoted_words}")
                    else:
                        # 쌍따옴표가 있지만 추출에 실패한 경우 원본 추가
                        processed_keywords.append(k_str)
                else:
                    # 쌍따옴표가 없는 일반 키워드는 그대로 추가
                    processed_keywords.append(k_str)
        
            result["keywords"] = processed_keywords
        
        # 전문 용어 감지 및 보너스 점수 적용
        professional_info = self._detect_professional_terms(query)
        if professional_info:
            result["is_professional"] = True
            result["domain"] = professional_info["domain"]
            
            # 보너스 점수 적용 (모델이 이미 계산했을 수도 있지만 안전장치)
            original_image = result["type_scores"]["image"]
            
            # 보너스 적용하되 1.0을 초과하지 않도록
            result["type_scores"]["image"] = min(1.0, original_image + professional_info["image_bonus"])
            
            # 전문 용어는 기본적으로 텍스트 설명도 필요
            if result["type_scores"]["text"] < 0.6:
                result["type_scores"]["text"] = 0.7
        
        # 최고 점수 타입 결정
        result["primary_type"] = max(result["type_scores"].items(), key=lambda x: x[1])[0]
        
        # 점수가 모두 낮으면 텍스트 기본값 설정
        if max(result["type_scores"].values()) < 0.1:
            result["type_scores"]["text"] = 0.7
            result["primary_type"] = "text"
        
        return result

    def _detect_professional_terms(self, query: str) -> Dict[str, Any]:
        """전문 용어 감지 및 보너스 점수 정보 생성"""
        
        query_lower = query.lower()
        
        # 도메인별 전문 용어 사전 (보너스 점수 포함)
        professional_domains = {
            "finance": {
                "terms": ["bep", "손익분기점", "roi", "npv", "irr", "재무제표", "손익계산서", "대차대조표", 
                        "현금흐름표", "매출총이익", "순이익", "자기자본비율", "부채비율", "유동비율", "당좌비율", "cvp", "CVP"],
                "image_bonus": 0.4,
                "table_bonus": 0.3,
                "related_terms": ["재무분석", "투자지표", "수익성분석", "재무제표", "경영지표"]
            },
            "medical": {
                "terms": ["mri", "ct", "x-ray", "혈압", "당뇨", "고혈압", "콜레스테롤", "심전도", "뇌파", 
                        "혈액검사", "소변검사", "내시경", "초음파", "생검", "수술"],
                "image_bonus": 0.5,
                "table_bonus": 0.2,
                "related_terms": ["의료진단", "치료방법", "의료영상", "임상결과", "의료기술"]
            },
            "legal": {
                "terms": ["계약서", "소송", "판례", "민법", "형법", "상법", "헌법", "계약위반", "손해배상", 
                        "이행청구", "법정대리인", "위임장"],
                "image_bonus": 0.1,
                "table_bonus": 0.4,
                "related_terms": ["법적근거", "판례분석", "법률해석", "규정조항", "법적절차"]
            },
            "manufacturing": {
                "terms": ["6시그마", "린생산", "tpm", "공정개선", "품질관리", "불량률", "수율", "qc", "qa", 
                        "fmea", "spc", "공정능력", "관리도"],
                "image_bonus": 0.5,
                "table_bonus": 0.3,
                "related_terms": ["공정개선", "품질시스템", "생산관리", "공정도", "제조기술"]
            },
            "it": {
                "terms": ["알고리즘", "데이터베이스", "api", "클라우드", "마이크로서비스", "아키텍처", 
                        "네트워크", "서버", "백엔드", "프론트엔드", "devops", "ci/cd"],
                "image_bonus": 0.4,
                "table_bonus": 0.2,
                "related_terms": ["시스템구조", "기술스택", "아키텍처", "개발방법론", "IT인프라"]
            }
        }
        
        # 쿼리에서 전문 용어 탐지
        for domain, info in professional_domains.items():
            for term in info["terms"]:
                if term in query_lower:
                    return {
                        "domain": domain,
                        "image_bonus": info["image_bonus"],
                        "table_bonus": info["table_bonus"],
                        "related_terms": info["related_terms"],
                        "detected_term": term
                    }
        
        return None

    def _quick_fallback_analysis(self, query: str) -> Dict[str, Any]:
        """빠른 폴백 분석 (도메인 인식 강화)"""
        
        query_lower = query.lower()
        scores = {"text": 0.5, "image": 0.0}  # 기본적으로 텍스트 필요
        
        # 전문 용어 감지
        professional_info = self._detect_professional_terms(query)
        
        # 기본 키워드 매칭
        image_keywords = ["다이어그램", "차트", "그래프", "그림", "이미지", "구조", "도식"]
        
        # 이미지 관련 키워드 체크  
        if any(keyword in query_lower for keyword in image_keywords):
            scores["image"] = 0.8
        
        # 전문 용어 감지시 점수 조정
        if professional_info:
            scores["text"] = 0.8  # 전문 용어는 설명 필수
            # visual_important 대신 image_bonus를 사용
            if professional_info["image_bonus"] > 0.3:  # 이미지 보너스가 큰 도메인
                scores["image"] = max(scores["image"], 0.6)
        
        # 간단한 키워드 추출
        keywords = []
        for word in query.split():
            if len(word) > 1 and word not in ["는", "은", "이", "가", "을", "를"]:
                keywords.append(word)
        
        result = {
            "query": query,
            "type_scores": scores,
            "primary_type": max(scores.items(), key=lambda x: x[1])[0],
            "intent": "information",
            "keywords": keywords[:5],
            "domain": professional_info["domain"] if professional_info else "general",
            "is_professional": bool(professional_info),
            "suggested_searches": professional_info["related_terms"] if professional_info else []
        }
        
        return result

    def generate_search_queries(self, analysis_result: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        분석 결과를 바탕으로 검색 쿼리 생성
        
        Args:
            analysis_result: 쿼리 분석 결과
            
        Returns:
            데이터 타입별 검색 쿼리 딕셔너리
        """
        
        base_query = analysis_result["query"]
        keywords = analysis_result["keywords"]
        domain = analysis_result.get("domain", "general")
        is_professional = analysis_result.get("is_professional", False)
        
        search_queries = {
            "text": [],
            "image": []
        }
        
        # 기본 검색 쿼리
        search_queries["text"].append(base_query)
        
        # 전문 용어인 경우 확장 검색
        if is_professional and domain != "general":
            
            # 텍스트 검색 확장
            search_queries["text"].extend([
                f"{' '.join(keywords)} 정의 설명",
                f"{' '.join(keywords)} 개념 원리",
                f"{domain} {' '.join(keywords)} 전문용어"
            ])
            
            # 도메인별 특화 검색
            if domain == "finance":
                search_queries["text"].extend([
                    f"{' '.join(keywords)} 계산방법 공식",
                    f"{' '.join(keywords)} 재무분석 지표"
                ])
                search_queries["image"].extend([
                    f"{' '.join(keywords)} 그래프 차트",
                    f"{' '.join(keywords)} 분석차트 시각화"
                ])
                
            elif domain == "medical":
                search_queries["text"].extend([
                    f"{' '.join(keywords)} 의학정보 설명",
                    f"{' '.join(keywords)} 진단 치료방법"
                ])
                search_queries["image"].extend([
                    f"{' '.join(keywords)} 의료영상 이미지",
                    f"{' '.join(keywords)} 해부도 구조"
                ])
                
            elif domain == "manufacturing":
                search_queries["text"].extend([
                    f"{' '.join(keywords)} 공정절차 방법",
                    f"{' '.join(keywords)} 품질관리 기준"
                ])
                search_queries["image"].extend([
                    f"{' '.join(keywords)} 공정도 플로우차트",
                    f"{' '.join(keywords)} 설비 구조도"
                ])
                
            elif domain == "it":
                search_queries["text"].extend([
                    f"{' '.join(keywords)} 기술설명 원리",
                    f"{' '.join(keywords)} 구현방법 코드"
                ])
                search_queries["image"].extend([
                    f"{' '.join(keywords)} 아키텍처 다이어그램",
                    f"{' '.join(keywords)} 시스템 구조도"
                ])
        
        # 빈 리스트 제거 및 중복 제거
        for data_type in search_queries:
            search_queries[data_type] = list(set([q for q in search_queries[data_type] if q.strip()]))
        
        return search_queries

    # 추가: 배치 처리를 위한 최적화 (여러 쿼리 동시 처리)
    def analyze_batch(self, queries: List[str]) -> List[Dict[str, Any]]:
        """
        여러 쿼리를 배치로 처리 (성능 최적화)
        
        Args:
            queries: 쿼리 리스트
            
        Returns:
            분석 결과 리스트
        """
        
        if len(queries) == 1:
            return [self.analyze(queries[0])]
        
        # 배치 프롬프트 생성
        batch_prompt = "다음 질문들을 각각 분석하여 JSON 배열로 응답:\n\n"
        
        for i, query in enumerate(queries[:5]):  # 최대 5개까지만 배치 처리
            batch_prompt += f"{i+1}. {query}\n"
        
        batch_prompt += """
        각 질문별로 {"text": float, "image": float, "keywords": []} 형식으로 분석.
        JSON 배열만 출력: [{\"text\": 0.8, \"image\": 0.2, \"keywords\": [\"키워드1\"]}, ...]
        """
        
        try:
            # 배치 API 호출
            response = self._call_ollama_api(batch_prompt, max_tokens=500)
            
            if response:
                # 배열 파싱 시도
                results = []
                try:
                    parsed_array = json.loads(response)
                    if isinstance(parsed_array, list):
                        for i, parsed in enumerate(parsed_array):
                            if i < len(queries):
                                result = self._validate_and_correct_result(parsed, queries[i])
                                results.append(result)
                        return results
                except:
                    pass
        
        except Exception as e:
            logger.warning(f"배치 처리 실패: {e}")
        
        # 배치 실패시 개별 처리로 폴백
        return [self.analyze(query) for query in queries]

    def _call_ollama_api(self, prompt: str, max_tokens: int = 100) -> str:
        """Ollama API 호출 공통 함수 (개선된 버전)"""
        # 여러 URL을 시도하는 리스트
        urls_to_try = [
            f"{self.ollama_url}/api/generate",
            "http://localhost:11434/api/generate",
            "http://172.19.0.6:11434/api/generate"
        ]
        
        # 기본 페이로드 설정
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "temperature": 0.0,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "num_ctx": 1024,
                "stop": ["\n\n"]
            }
        }
        
        # 1. requests 라이브러리로 시도
        urls = ["http://localhost:11434/api/generate"]
        for url in urls:
            try:
                logger.debug(f"URL 시도: {url}")
                response = requests.post(url, json=payload, timeout=30)
                
                if response.status_code == 200:
                    response_text = response.json().get("response", "").strip()
                    
                    # <think> 태그 처리
                    if response_text.startswith("<think>"):
                        # <think> 태그 제거 시도
                        think_end = response_text.find("</think>")
                        if think_end > -1:
                            # </think> 이후의 텍스트 사용
                            response_text = response_text[think_end + 8:].strip()
                        else:
                            # <think> 태그만 제거
                            response_text = response_text[7:].strip()
                    
                    logger.debug(f"API 응답 성공: {url}")
                    return response_text
                    
            except Exception as e:
                logger.warning(f"{url} 호출 실패: {e}")
        
        # 2. curl 명령어로 시도 (Docker 환경에서의 리다이렉션 문제 해결)
        response_text = self._call_ollama_api_with_curl(prompt, max_tokens)
        if response_text:
            return response_text
        
        logger.error("모든 API 호출 방법 실패")
        return None
        
    def _call_ollama_api_with_curl(self, prompt: str, max_tokens: int = 100) -> str:
        """curl을 사용하여 Ollama API 호출 (리다이렉션 문제 해결)"""
        import subprocess
        import tempfile
        import json
        import os
        
        # 여러 URL을 시도하는 리스트
        urls_to_try = [
            f"{self.ollama_url}/api/generate",
            "http://localhost:11434/api/generate",
            "http://172.19.0.6:11434/api/generate"
        ]
        
        # 기본 페이로드 설정
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "temperature": 0.0,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "num_ctx": 1024,
                "stop": ["\n\n"]
            }
        }
        
        for url in urls_to_try:
            try:
                # 임시 파일에 JSON 데이터 저장
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp:
                    json.dump(payload, temp)
                    temp_path = temp.name
                
                # curl 명령어 실행
                logger.debug(f"curl로 API 호출 시도: {url}")
                cmd = [
                    "curl", "-s", "-X", "POST",
                    "-H", "Content-Type: application/json",
                    "-H", "Connection: close",
                    "-d", f"@{temp_path}",
                    url
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                os.unlink(temp_path)  # 임시 파일 삭제
                
                if result.returncode == 0 and result.stdout:
                    try:
                        response_data = json.loads(result.stdout)
                        response_text = response_data.get("response", "").strip()
                        
                        # <think> 태그 처리
                        if response_text.startswith("<think>"):
                            # <think> 태그 제거 시도
                            think_end = response_text.find("</think>")
                            if think_end > -1:
                                # </think> 이후의 텍스트 사용
                                response_text = response_text[think_end + 8:].strip()
                            else:
                                # <think> 태그만 제거
                                response_text = response_text[7:].strip()
                        
                        logger.debug(f"curl API 응답 성공: {url}")
                        return response_text
                    except json.JSONDecodeError:
                        logger.warning(f"curl 응답 JSON 파싱 실패: {result.stdout[:100]}...")
                else:
                    logger.warning(f"curl 명령 실패: {result.stderr}")
            
            except Exception as e:
                logger.error(f"curl 시도 중 오류: {e}")
        
        return None

def main():
    import time
    start = time.time()
    query_analyzer = QueryAnalyzer()
    query = input("사용자 질문 : ")
    result = query_analyzer.analyze(query)

    # primary_type = result.get('primary_type', 'text')
    # intent = result.get('intent', 'unknown')

    elapsed_time = time.time() - start
    # 시간을 분:초.밀리초 형식으로 변환
    if elapsed_time >= 60:
        minutes = int(elapsed_time // 60)
        seconds = elapsed_time % 60
        time_str = f"{minutes}분 {seconds:.2f}초"
    else:
        time_str = f"{elapsed_time:.2f}초"

    print("[INFO] 쿼리 분석 결과 : ", result)
    print(f"[INFO] 쿼리 분석 시간 : {time_str}") # 개선된 시간 표시

if __name__ == "__main__":
    main()