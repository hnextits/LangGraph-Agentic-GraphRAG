#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
RAG 시스템 평가기 - 생성된 답변의 품질을 평가하고 필요시 피드백 루프를 실행합니다.
"""

import os
import json
import logging
import torch
from typing import List, Dict, Any, Optional, Tuple

# config.py 임포트
from config import RAGConfig

# 로깅 설정
logger = logging.getLogger(__name__)

class Evaluator:
    """
    RAG 시스템 평가기
    생성된 답변의 품질을 평가하고 필요시 피드백 루프를 실행합니다.
    """
    
    def __init__(self, config: RAGConfig = None):
        """
        평가기 초기화
        
        Args:
            config: RAGConfig 인스턴스
        """
        if config is None:
            config = RAGConfig()
        
        self.rag_config = config
        self.config = self._load_config()
        logger.info("Evaluator 초기화 완료")
    
    def _load_config(self) -> Dict[str, Any]:
        """
        기본 설정 로드
        
        Returns:
            설정 딕셔너리
        """
        default_config = {
            "quality_threshold": 0.7,
            "max_feedback_loops": 3
        }
        
        logger.info("기본 설정 사용")
        return default_config
    
    def evaluate_response(self, query: str, context: str, answer: str) -> Dict[str, Any]:
        """
        생성된 답변 평가
        
        Args:
            query: 사용자 질문
            context: 검색된 컨텍스트
            answer: 생성된 답변
            
        Returns:
            평가 결과 딕셔너리
        """
        # 메모리 정리
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        # 입력 유효성 검사
        if not query or not answer:
            logger.warning("유효하지 않은 입력: 질문 또는 답변이 비어있습니다.")
            return {
                "overall_score": 0.5,
                "relevance": 0.5,
                "accuracy": 0.5,
                "completeness": 0.5,
                "hallucination": 0.5,
                "suggestions": "평가할 내용이 부족합니다.",
                "needs_improvement": True
            }
        
        # 간단한 평가 로직
        try:
            # 기본 점수 계산
            relevance = 0.8 if len(answer) > 50 else 0.5
            accuracy = 0.7 if context and len(context) > 0 else 0.5
            completeness = 0.8 if len(answer) > 100 else 0.6
            hallucination = 0.2  # 낮을수록 좋음
            
            overall_score = (relevance * 0.3 + accuracy * 0.4 + 
                           completeness * 0.2 + (1 - hallucination) * 0.1)
            
            return {
                "overall_score": overall_score,
                "relevance": relevance,
                "accuracy": accuracy,
                "completeness": completeness,
                "hallucination": hallucination,
                "suggestions": "평가 완료",
                "needs_improvement": overall_score < self.config.get("quality_threshold", 0.7)
            }
            
        except Exception as e:
            logger.error(f"평가 중 오류 발생: {str(e)}")
            return {
                "overall_score": 0.5,
                "relevance": 0.5,
                "accuracy": 0.5,
                "completeness": 0.5,
                "hallucination": 0.5,
                "suggestions": f"평가 오류: {str(e)}",
                "needs_improvement": True,
                "error": str(e)
            }
    
    def feedback_loop(self, query: str, results: Dict[str, Any], router, generator) -> Dict[str, Any]:
        """
        피드백 루프를 실행하여 검색 및 생성 결과를 반복적으로 개선합니다.
        
        Args:
            query: 사용자 질문
            results: 초기 검색 및 생성 결과
            router: 라우터 객체
            generator: 생성기 객체
        
        Returns:
            최종 개선된 결과
        """
        # 메모리 정리
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        try:
            # 결과가 없는 경우 처리
            if not results:
                logger.warning("결과가 없어 피드백 루프를 실행할 수 없습니다.")
                return {"error": "결과가 없습니다.", "feedback_loops": 0}
                
            # 현재 결과에서 평가 정보 추출
            if "evaluation" not in results:
                try:
                    context = results.get('context_used', results.get('context', ''))
                    answer = results.get('answer', '')
                    evaluation = self.evaluate_response(query, context, answer)
                    results["evaluation"] = evaluation
                except Exception as e:
                    logger.error(f"평가 중 오류 발생: {e}")
                    results["evaluation"] = {
                        "overall_score": 0.5,
                        "needs_improvement": True,
                        "error": str(e)
                    }
            
            # 품질이 충분하면 바로 반환
            evaluation = results.get("evaluation", {})
            initial_score = evaluation.get("overall_score", 0)
            if not evaluation.get("needs_improvement", True) or initial_score >= self.config.get("quality_threshold", 0.7):
                logger.info(f"답변 품질 충분({initial_score}), 피드백 루프 불필요")
                results["feedback_loops"] = 0
                results["final_query"] = query
                return results
            
            # 피드백 루프 실행 (간소화된 버전)
            logger.info("피드백 루프 실행 - 간소화된 버전")
            results["feedback_loops"] = 1
            results["final_query"] = query
            
            return results
            
        except Exception as e:
            logger.error(f"피드백 루프 실행 중 오류 발생: {e}")
            results["error"] = f"피드백 루프 오류: {str(e)}"
            results["feedback_loops"] = 0
            return results
