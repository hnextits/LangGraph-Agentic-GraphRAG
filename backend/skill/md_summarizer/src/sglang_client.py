"""
SGLang Client for Qwen Model
기존 AnswerGenerator와 동일한 인터페이스 제공
"""

import httpx
import json
from typing import List, Optional, Dict, Any
from loguru import logger
import asyncio
from itertools import cycle


class SGLangClient:
    """SGLang 서버와 통신하는 클라이언트"""
    
    def __init__(self, endpoints: List[str] = None):
        """
        Args:
            endpoints: SGLang 서버 엔드포인트 리스트
                      예: ["http://localhost:30000", "http://localhost:30001"]
        """
        self.endpoints = endpoints or ["http://localhost:30000"]
        self.endpoint_cycle = cycle(self.endpoints)  # 라운드 로빈
        self.timeout = 120.0  # 큰 문서 처리를 위해 타임아웃 증가
        
        logger.info(f"SGLang Client initialized with endpoints: {self.endpoints}")
    
    def _get_next_endpoint(self) -> str:
        """라운드 로빈 방식으로 다음 엔드포인트 반환"""
        return next(self.endpoint_cycle)
    
    def generate_answer(self, content: str, max_tokens: int = 8192, auto_chunk: bool = True, max_input_tokens: int = 80000) -> str:
        """
        기존 AnswerGenerator.generate_answer()와 동일한 인터페이스
        
        Args:
            content: 요약할 MD 파일 내용 (문자열)
            max_tokens: 최대 생성 토큰 수
            auto_chunk: 자동 청킹 활성화 (기본값: True)
            max_input_tokens: 최대 입력 토큰 수 (기본값: 100000)
            
        Returns:
            str: 생성된 요약 텍스트
        """
        if not content or content.isspace():
            return "(관련된 구글 검색 결과를 찾을 수 없습니다)"
        
        # 입력 토큰 수 추정
        # 한글: 1문자 ≈ 1.5 토큰, 영어: 1문자 ≈ 0.25 토큰
        # 보수적으로 1문자 = 1.5 토큰으로 계산
        estimated_input_tokens = int(len(content) * 1.5)
        estimated_total_tokens = estimated_input_tokens + 2000 + max_tokens  # 입력 + 프롬프트 + 출력
        
        # 자동 청킹이 활성화되고 전체 토큰이 너무 크면 청킹 처리
        # 안전 마진: 40,000 토큰 (컨텍스트 오버플로우 방지)
        if auto_chunk and estimated_total_tokens > 40000:
            logger.info(f"입력이 너무 큽니다 (예상 총 토큰: {estimated_total_tokens:,}). 청킹 처리를 시작합니다...")
            return self._generate_with_chunking(content, max_tokens, max_input_tokens)
        
        try:
            # 요약 생성을 위한 프롬프트 (단원별 요약)
            prompt = f"""You are an expert summarizer. Read the following document carefully and provide a clear, accurate, and well-structured summary.
Focus on the key ideas, main arguments, important data points, and overall conclusions.
Avoid unnecessary details or examples.
Use concise and professional language suitable for an executive or technical audience.

The summary must be written entirely in Korean.

Please organize the output as follows:

Overview: A brief description of the document’s purpose and scope.

Key Points: The most important findings, arguments, or insights (in bullet points).

Conclusion/Implications: What the document ultimately conveys or recommends.

(Optional) Notable Quotes or Data: If there are any key phrases or statistics worth highlighting.

Input document:
{content}

**output:** """
            
            # SGLang API 호출
            endpoint = self._get_next_endpoint()
            response = self._call_sglang(endpoint, prompt, max_tokens)
            
            return response
            
        except Exception as e:
            logger.error(f"요약 생성 중 오류: {e}")
            return f"답변 생성에 실패했습니다: {str(e)}"
    
    def _call_sglang(self, endpoint: str, prompt: str, max_tokens: int) -> str:
        """SGLang 서버 호출"""
        url = f"{endpoint}/generate"
        
        payload = {
            "text": prompt,
            "sampling_params": {
                "max_new_tokens": max_tokens,
                "temperature": 0.5,  # 낮춰서 더 집중된 출력
                "top_p": 0.9,
                "repetition_penalty": 1.3,  # 반복 방지 강화
                "stop": [
                    "\n\n---\n\n", 
                    "\n---  \n*※",  # footer 반복 패턴
                    "---  \n*※",
                    "(※ 최종", 
                    "(※ 본 요약",
                    "*※ 보고서는 제공된 데이터를 기반으로"  # 정확한 footer 시작 부분
                ],
            }
        }
        
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                
                result = response.json()
                text = result.get("text", "").strip()
                
                # 후처리: 반복되는 패턴 제거
                text = self._remove_repetitive_patterns(text)
                
                return text
                
        except httpx.TimeoutException:
            logger.error(f"SGLang 서버 타임아웃: {endpoint}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"SGLang 서버 HTTP 오류: {e}")
            raise
        except Exception as e:
            logger.error(f"SGLang 호출 중 오류: {e}")
            raise
    
    async def generate_answer_async(self, content: str, max_tokens: int = 8192) -> str:
        """비동기 버전의 generate_answer"""
        if not content or content.isspace():
            return "(관련된 구글 검색 결과를 찾을 수 없습니다)"
        
        try:
            prompt = f"""You are an expert summarizer. Read the following document carefully and provide a clear, accurate, and well-structured summary.
Focus on the key ideas, main arguments, important data points, and overall conclusions.
Avoid unnecessary details or examples.
Use concise and professional language suitable for an executive or technical audience.

The summary must be written entirely in Korean.

Please organize the output as follows:

Overview: A brief description of the document’s purpose and scope.

Key Points: The most important findings, arguments, or insights (in bullet points).

Conclusion/Implications: What the document ultimately conveys or recommends.

(Optional) Notable Quotes or Data: If there are any key phrases or statistics worth highlighting.

Input document:
{content}

**output:** """
            
            endpoint = self._get_next_endpoint()
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._call_sglang_async(endpoint, prompt, max_tokens, client)
            
            return response
            
        except Exception as e:
            logger.error(f"비동기 요약 생성 중 오류: {e}")
            return f"답변 생성에 실패했습니다: {str(e)}"
    
    async def _call_sglang_async(self, endpoint: str, prompt: str, max_tokens: int, client: httpx.AsyncClient) -> str:
        """비동기 SGLang 서버 호출 (공유 클라이언트 사용)"""
        url = f"{endpoint}/generate"
        
        payload = {
            "text": prompt,
            "sampling_params": {
                "max_new_tokens": max_tokens,
                "temperature": 0.7,
                "top_p": 0.9,
                "repetition_penalty": 1.1,
            }
        }
        
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            return result.get("text", "").strip()
                
        except httpx.TimeoutException:
            logger.error(f"SGLang 서버 타임아웃: {endpoint}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"SGLang 서버 HTTP 오류: {e}")
            raise
        except Exception as e:
            logger.error(f"비동기 SGLang 호출 중 오류: {e}")
            raise
    
    def _generate_with_chunking(self, content: str, max_tokens: int, max_input_tokens: int) -> str:
        """
        큰 문서를 청크로 나눠서 요약 (비동기 병렬 처리)
        
        Args:
            content: 전체 문서 내용
            max_tokens: 각 청크당 최대 생성 토큰
            max_input_tokens: 최대 입력 토큰 수
            
        Returns:
            str: 결합된 요약
        """
        from .md_parser import MDParser
        
        parser = MDParser()
        
        # 청크 크기 계산 (한글 기준: 1 토큰 ≈ 0.67 문자)
        # 안전하게 12,000 토큰 = ~8,000 문자로 설정 (컨텍스트 오버플로우 방지)
        chunk_size = 20000
        chunks = parser.chunk_text(content, chunk_size=chunk_size, overlap=300)
        
        logger.info(f"문서를 {len(chunks)}개 청크로 분할 (청크당 ~{chunk_size:,} 문자)")
        
        # 비동기 병렬 처리
        summaries = asyncio.run(self._process_chunks_parallel(chunks, max_tokens))
        
        # 최종 결과 결합 전 중복 제거
        deduplicated_summaries = self._deduplicate_summaries(summaries)
        combined_summary = "\n\n---\n\n".join(deduplicated_summaries)
        logger.info(f"Map 단계 완료: {len(summaries)}개 청크 → {len(deduplicated_summaries)}개 (중복 제거 후), 총 {len(combined_summary):,} 문자")
        
        # Reduce 단계: 모든 청크 요약을 다시 LLM에 넣어서 최종 통합 요약 생성
        # 단, combined_summary가 너무 크면 Reduce 단계도 컨텍스트 오버플로우 발생 가능
        if len(deduplicated_summaries) > 1:
            # combined_summary가 너무 크면 Reduce 스킵 (이미 중복 제거됨)
            estimated_reduce_tokens = int(len(combined_summary) * 1.5) + 2000 + max_tokens
            if estimated_reduce_tokens > 60000:
                logger.warning(f"Reduce 단계 스킵: combined_summary가 너무 큼 (예상 토큰: {estimated_reduce_tokens:,}). 중복 제거된 요약들을 그대로 반환합니다.")
                final_summary = combined_summary
            else:
                logger.info("Reduce 단계 시작: 모든 청크 요약을 통합하여 최종 요약 생성...")
                final_summary = self._reduce_summaries(combined_summary, max_tokens)
        else:
            final_summary = combined_summary
        
        logger.info(f"전체 요약 완료: 최종 {len(final_summary):,} 문자")
        return final_summary
    
    async def _process_chunks_parallel(self, chunks: list, max_tokens: int) -> list:
        """
        청크들을 비동기 병렬로 처리 (듀얼 GPU 활용)
        
        Args:
            chunks: 청크 리스트
            max_tokens: 각 청크당 최대 생성 토큰
            
        Returns:
            list: 요약 리스트
        """
        # 연결 제한을 늘린 공유 AsyncClient 생성
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        
        async with httpx.AsyncClient(timeout=self.timeout, limits=limits) as client:
            async def process_single_chunk(i: int, chunk: str) -> tuple:
                """단일 청크 처리"""
                logger.info(f"청크 {i}/{len(chunks)} 요약 중... ({len(chunk):,} 문자)")
                
                try:
                    simple_prompt = f"""You are an expert summarizer. Read the following document carefully and provide a clear, accurate, and well-structured summary.
Focus on the key ideas, main arguments, important data points, and overall conclusions.
Avoid unnecessary details or examples.
Use concise and professional language suitable for an executive or technical audience.

The summary must be written entirely in Korean.

Please organize the output as follows:

Overview: A brief description of the document's purpose and scope.

Key Points: The most important findings, arguments, or insights (in bullet points).

Conclusion/Implications: What the document ultimately conveys or recommends.

(Optional) Notable Quotes or Data: If there are any key phrases or statistics worth highlighting.

Input document:
{chunk}

**output:** """
                    
                    endpoint = self._get_next_endpoint()
                    summary = await self._call_sglang_async(endpoint, simple_prompt, max_tokens=3000, client=client)
                    
                    # 후처리: 불필요한 반복 제거
                    summary = self._clean_summary(summary)
                    
                    logger.info(f"청크 {i} 완료 ({len(summary)} 문자)")
                    return (i, summary)
                    
                except Exception as e:
                    logger.error(f"청크 {i} 요약 실패: {e}")
                    return (i, f"## 파트 {i}\n\n(요약 실패: {str(e)})")
            
            # 모든 청크를 병렬로 처리
            tasks = [process_single_chunk(i+1, chunk) for i, chunk in enumerate(chunks)]
            results = await asyncio.gather(*tasks)
            
            # 순서대로 정렬
            results.sort(key=lambda x: x[0])
            summaries = [summary for _, summary in results]
            
            return summaries
    
    def _reduce_summaries(self, combined_summary: str, max_tokens: int) -> str:
        """
        Reduce 단계: 여러 청크 요약을 하나의 통합된 요약으로 재구성
        
        Args:
            combined_summary: 병합된 청크 요약들
            max_tokens: 최대 생성 토큰 수
            
        Returns:
            str: 최종 통합 요약
        """
        reduce_prompt = f"""You are an expert summarizer. You have been given multiple summaries of different parts of a document.
Your task is to synthesize these summaries into ONE coherent, comprehensive summary that:
1. Eliminates redundancy and repetition
2. Maintains all key information
3. Provides a unified narrative
4. Is well-structured and professional

The final summary must be written entirely in Korean.

Please organize the output as follows:

Overview: A comprehensive description of the entire document's purpose and scope.

Key Points: The most important findings, arguments, or insights from ALL parts (in bullet points).

Conclusion/Implications: What the entire document ultimately conveys or recommends.

(Optional) Notable Quotes or Data: Key phrases or statistics worth highlighting.

Input summaries from different parts:
{combined_summary}

**output:** Synthesize the above summaries into ONE unified, non-redundant summary in Korean."""

        try:
            endpoint = self._get_next_endpoint()
            # Reduce 단계에서는 더 많은 토큰 허용
            reduce_max_tokens = max_tokens
            final_summary = self._call_sglang(endpoint, reduce_prompt, reduce_max_tokens)
            
            # 요약이 너무 짧으면 원본 반환 (최소 500자)
            if len(final_summary) < 500:
                logger.warning(f"Reduce 결과가 너무 짧음 ({len(final_summary)} 문자), 병합된 요약 반환")
                return combined_summary
            
            logger.info(f"Reduce 단계 완료: 최종 요약 생성됨 ({len(final_summary)} 문자)")
            return final_summary
        except Exception as e:
            logger.error(f"Reduce 단계 실패: {e}, 병합된 요약 반환")
            return combined_summary
    
    def _deduplicate_summaries(self, summaries: List[str]) -> List[str]:
        """
        요약 리스트에서 중복된 섹션 제거
        - 완전히 동일한 요약 제거
        - 유사도 기반 중복 제거 (80% 이상 유사하면 중복으로 간주)
        """
        if not summaries:
            return summaries
        
        unique_summaries = []
        seen_hashes = set()
        
        for summary in summaries:
            # 정규화: 공백, 줄바꿈 제거 후 해시 계산
            normalized = ''.join(summary.split())
            summary_hash = hash(normalized)
            
            # 완전히 동일한 요약은 건너뛰기
            if summary_hash in seen_hashes:
                logger.info(f"중복 요약 발견 (완전 일치), 제거")
                continue
            
            # 유사도 체크 (개선된 방식: n-gram 기반 유사도)
            is_duplicate = False
            for existing in unique_summaries:
                # 두 요약의 시작 1000자를 비교 (더 많은 텍스트로 정확도 향상)
                sample_len = min(1000, len(summary), len(existing))
                if sample_len > 100:
                    similarity = self._calculate_similarity(
                        summary[:sample_len], 
                        existing[:sample_len]
                    )
                    # 임계값을 70%로 낮춰서 더 민감하게 중복 감지
                    if similarity > 0.7:
                        logger.info(f"유사 요약 발견 (유사도: {similarity:.2%}), 제거")
                        is_duplicate = True
                        break
            
            if not is_duplicate:
                unique_summaries.append(summary)
                seen_hashes.add(summary_hash)
        
        return unique_summaries
    
    def _remove_repetitive_patterns(self, text: str) -> str:
        """
        LLM 출력에서 반복되는 패턴 제거
        - 같은 문단이 여러 번 반복되는 경우 첫 번째만 유지
        """
        if not text:
            return text
        
        # --- 구분선으로 분할
        parts = text.split("\n\n---\n\n")
        
        # 반복이 없으면 원본 그대로 반환
        if len(parts) <= 1:
            # (※ 로 시작하는 메타 정보만 제거
            lines = text.split('\n')
            cleaned_lines = []
            for line in lines:
                if line.strip().startswith('(※'):
                    break
                cleaned_lines.append(line)
            return '\n'.join(cleaned_lines).strip()
        
        # 여러 파트가 있으면 첫 번째만 유지
        first_part = parts[0].strip()
        
        # (※ 로 시작하는 메타 정보 제거
        lines = first_part.split('\n')
        cleaned_lines = []
        for line in lines:
            if line.strip().startswith('(※'):
                break
            cleaned_lines.append(line)
        
        result = '\n'.join(cleaned_lines).strip()
        
        # 결과가 너무 짧으면 원본 반환 (과도한 제거 방지)
        if len(result) < len(text) * 0.3:
            logger.warning(f"반복 제거 결과가 너무 짧음 ({len(result)} < {len(text) * 0.3}), 원본 반환")
            return text
        
        return result
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        두 텍스트의 유사도 계산 (n-gram 기반 개선)
        """
        if not text1 or not text2:
            return 0.0
        
        # n-gram 기반 유사도 (3-gram 사용)
        def get_ngrams(text: str, n: int = 3) -> set:
            # 공백 제거 후 n-gram 생성
            text_clean = ''.join(text.split())
            return set(text_clean[i:i+n] for i in range(len(text_clean) - n + 1))
        
        ngrams1 = get_ngrams(text1)
        ngrams2 = get_ngrams(text2)
        
        if not ngrams1 or not ngrams2:
            return 0.0
        
        # Jaccard 유사도
        intersection = len(ngrams1 & ngrams2)
        union = len(ngrams1 | ngrams2)
        
        return intersection / union if union > 0 else 0.0
    
    def _clean_summary(self, summary: str) -> str:
        """
        요약 결과 후처리
        - 반복되는 문장 제거 (완전 일치 + 유사 문장)
        - 불필요한 메타 정보 제거
        """
        lines = summary.split('\n')
        cleaned_lines = []
        seen_lines = set()
        seen_sentences = []
        
        for line in lines:
            # 빈 줄은 유지
            if not line.strip():
                cleaned_lines.append(line)
                continue
            
            line_normalized = line.strip()
            
            # 1. 완전히 동일한 줄 제거
            if line_normalized in seen_lines:
                continue
            
            # 2. 유사한 문장 제거 (70% 이상 유사)
            is_similar = False
            if len(line_normalized) > 20:  # 짧은 줄은 스킵
                for seen_sent in seen_sentences:
                    if len(seen_sent) > 20:
                        similarity = self._calculate_similarity(line_normalized, seen_sent)
                        if similarity > 0.7:
                            is_similar = True
                            break
            
            if is_similar:
                continue
            
            seen_lines.add(line_normalized)
            if len(line_normalized) > 20:
                seen_sentences.append(line_normalized)
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def cleanup_model(self):
        """기존 AnswerGenerator와의 호환성을 위한 메서드 (SGLang은 서버 기반이므로 불필요)"""
        logger.info("SGLang 클라이언트는 서버 기반이므로 cleanup이 불필요합니다.")
        pass
    
    @staticmethod
    def make_llm_input_data(save_dir, json_data):
        """기존 AnswerGenerator와 동일한 정적 메서드"""
        processed_data = []
        
        for item in json_data:
            processed_item = {
                "link": item.get("link", ""),
                "data": ""
            }
            
            data = item.get("data")
            if not data or (isinstance(data, str) and data.strip() == ""):
                processed_item["data"] = item.get("google_snipping", "")
            else:
                processed_item["data"] = data
            
            processed_data.append(processed_item)
        
        if save_dir:
            import os
            try:
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir, exist_ok=True)
                with open(os.path.join(save_dir, "processed_data.json"), "w", encoding="utf-8") as f:
                    json.dump(processed_data, f, ensure_ascii=False, indent=4)
                logger.info("처리된 데이터가 JSON 파일로 저장되었습니다.")
            except Exception as e:
                logger.error(f"JSON 파일 저장 중 오류 발생: {e}")
        
        return processed_data
    
    @staticmethod
    def get_timestamp():
        """현재 시간을 문자열로 반환"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# 기존 시스템과의 호환성을 위한 별칭
AnswerGenerator = SGLangClient
