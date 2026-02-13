#!/usr/bin/env python
# -*- coding: utf-8 -*-

# FlashAttention 모듈과의 잠재적 충돌을 피하기 위해 비활성화하는 환경 변수 설정
# 특정 하드웨어나 라이브러리 버전에서 예기치 않은 오류가 발생하는 것을 방지합니다.
import os
import sys

os.environ["DISABLE_FLASH_ATTENTION"] = "1"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

# 시스템 모듈 경로에서 flash_attn 관련 모듈 제거 (안전장치)
sys.modules.pop('flash_attn', None)
sys.modules.pop('flash_attn_2_cuda', None)

"""
RAG 시스템 통합 파이프라인 - 전체 RAG 시스템을 통합하고 실행합니다. (수정된 최종 버전)
"""

import json
import logging
import argparse
import threading
from typing import List, Dict, Any, Optional, Set

# 컴포넌트 임포트
from image_processor import image_processor 


from config import RAGConfig
from router import RAGRouter
from generator import SGLangGenerator as Generator
from evaluator import Evaluator
from refiner import Refiner
from graph_reasoner import GraphReasoner

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RAGPipeline:
    """
    RAG 시스템 통합 파이프라인
    전체 RAG 시스템을 통합하고 실행합니다.
    """
    
    def __init__(self):
        """
        파이프라인 초기화
        """
        self.config = RAGConfig()
        
        # 컴포넌트 초기화
        self.router = RAGRouter(self.config)
        self.generator = Generator(self.config)
        self.evaluator = Evaluator(self.config)
        # 환경 문제로 인해 Refiner 사용 안함
        self.refiner = None
        # LangGraph 기반 그래프 라우터 (필요 시)
        try:
            self.graph_reasoner = GraphReasoner(self.config)
        except Exception as exc:
            logger.warning("GraphReasoner 초기화 실패: %s", exc)
            self.graph_reasoner = None
        logger.info("환경 문제로 인해 Refiner를 사용하지 않습니다.")
        
        logger.info("RAG 파이프라인 초기화 완료")
    
    def load_engine_sync(self):
        """SGLang 엔진을 명시적으로 로드합니다. (메인 스레드에서 직접 호출 필수)"""
        try:
            if self.generator and hasattr(self.generator, "ensure_model_loaded"):
                # to_thread를 사용하지 않고 직접 호출하여 메인 스레드 유지
                self.generator.ensure_model_loaded()
                logger.info("Generator 엔진 로드 완료")
            
            if self.refiner and hasattr(self.refiner, "ensure_model_loaded"):
                self.refiner.ensure_model_loaded()
                logger.info("Refiner 엔진 로드 완료")
        except Exception as e:
            logger.error(f"엔진 로드 중 오류 발생: {e}")
            raise

    async def load_engine(self):
        """SGLang 엔진을 비동기 인터페이스로 로드 (하위 호환성용)"""
        # 내부적으로는 동기 함수를 호출하지만, 호출하는 쪽이 메인 스레드여야 함
        self.load_engine_sync()

    def cleanup(self):
        """파이프라인이 사용하는 모든 리소스를 정리합니다."""
        try:
            if self.generator and hasattr(self.generator, "cleanup_model"):
                self.generator.cleanup_model()
        except Exception:
            logger.exception("Generator 정리 중 오류 발생")
        try:
            if self.refiner and hasattr(self.refiner, "cleanup_model"):
                self.refiner.cleanup_model()
        except Exception:
            logger.exception("Refiner 정리 중 오류 발생")
        try:
            if self.router and hasattr(self.router, "cleanup"):
                self.router.cleanup()
        except Exception:
            logger.exception("Router 정리 중 오류 발생")
        try:
            if self.graph_reasoner and hasattr(self.graph_reasoner, "close"):
                self.graph_reasoner.close()
        except Exception:
            logger.exception("GraphReasoner 정리 중 오류 발생")
    
    def _process_image_document(self, img_doc: Dict[str, Any], processed_images: List[Dict[str, Any]], image_paths: List[str]) -> None:
        """
        단일 이미지 문서를 처리하여 base64로 변환합니다.
        
        Args:
            img_doc: 처리할 이미지 문서
            processed_images: 처리된 이미지를 추가할 리스트
            image_paths: 이미지 경로를 추가할 리스트
        """
        image_base64 = img_doc.get('image_base64')
        file_path = img_doc.get('file_path')
        
        if image_base64:
            # 이미 인코딩된 base64 데이터 사용
            logger.debug(f"이미 인코딩된 base64 데이터 사용: {file_path}")
            img_doc['base64'] = image_base64
            img_doc['image_available'] = True
            processed_images.append(img_doc)
            
            if file_path:
                image_paths.append(file_path)
                
        elif file_path:
            # 이미지 경로 저장
            image_paths.append(file_path)
            
            # 파일 존재 여부 확인
            if not os.path.exists(file_path):
                logger.error(f"이미지 파일이 존재하지 않음: {file_path}")
                return
            
            # base64 변환 시도
            try:
                base64_data = image_processor.encode_image_to_base64(file_path)
                if base64_data:
                    img_doc['base64'] = base64_data
                    img_doc['image_available'] = True
                    processed_images.append(img_doc)
                    logger.debug(f"이미지 base64 변환 성공: {file_path}")
                else:
                    img_doc['image_available'] = False
                    logger.warning(f"이미지 base64 변환 실패: {file_path}")
            except Exception as e:
                logger.error(f"이미지 base64 변환 중 오류: {file_path}, 오류: {str(e)}")
                img_doc['image_available'] = False
        else:
            logger.warning(f"이미지 문서에 file_path가 없음: {img_doc.get('id', 'unknown')}")
    
    def _build_graph_search_results(self, graph_payload: Dict[str, Any]) -> Dict[str, Any]:
        """GraphReasoner의 결과를 generator가 기대하는 search_results 형태로 변환합니다."""
        retrieval_path = graph_payload.get("retrieval_path", "unknown")
        max_hops = graph_payload.get("max_hops", 1)
        snippets = graph_payload.get("context_snippets", [])
        nodes = graph_payload.get("nodes", [])
        relations = graph_payload.get("relations", [])

        # 노드에서 document_id 수집 → 실제 문서명 출처로 사용
        doc_ids = set()
        for node in nodes:
            did = node.get("document_id", "") or node.get("doc_id", "")
            if did:
                doc_ids.add(did)
        # 문서명이 없으면 retrieval_path 표시
        doc_source = ", ".join(sorted(doc_ids)) if doc_ids else f"GraphRAG/{retrieval_path}"

        text_results = []
        seen_texts = set()  # 중복 스니펫 제거
        for snippet in snippets:
            if snippet in seen_texts:
                continue
            seen_texts.add(snippet)
            # 스니펫에서 이름 추출: [엔티티] Name (Type) 또는 [관계] A --[rel]--> B
            title = snippet.split("]", 1)[-1].strip() if "]" in snippet else snippet
            title = title[:60] + "…" if len(title) > 60 else title
            text_results.append({
                "text": snippet,
                "title": title,
                "source": doc_source,
                "score": 1.0,
                "content_type": "text",
            })
        return {
            "text_documents": text_results,
            "image_documents": [],
            "metadata": {
                "search_mode": "GraphRAG",
                "retrieval_path": retrieval_path,
                "max_hops": max_hops,
                "graph_notes": graph_payload.get("notes", []),
            },
        }

    def process_query(
        self,
        query: str,
        top_k: int = 5,
        cancellation_event: Optional[threading.Event] = None,
        allowed_document_uuids: Optional[Set[str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        질문 처리 및 답변 생성 (수정된 메서드)
        
        Args:
            query: 사용자 질문
            top_k: 각 파이프라인에서 반환할 최대 결과 수
            cancellation_event: 취소 이벤트
            allowed_document_uuids: 허용된 문서 UUID 집합
            session_id: 세션 ID (필터링용)
            
        Returns:
            처리 결과 딕셔너리
        """
        logger.info(f"질문 처리 시작 (session: {session_id}): '{query}'")

        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before routing and search")

        use_graph_rag = False
        graph_payload = None

        if (
            self.graph_reasoner
            and getattr(self.graph_reasoner, "graph_enabled", False)
        ):
            try:
                graph_payload = self.graph_reasoner.retrieve(
                    query, session_id=session_id,
                    allowed_document_uuids=allowed_document_uuids,
                )
                rp = graph_payload.get("retrieval_path", "unknown")
                mh = graph_payload.get("max_hops", 1)
                quality = graph_payload.get("retrieval_quality", 0.0)
                logger.info("GraphReasoner 결과: path=%s, hops=%d, quality=%.2f, snippets=%d",
                            rp, mh, quality, len(graph_payload.get("context_snippets", [])))
                if rp == "vector":
                    logger.info(
                        "GraphReasoner [%s] → 기존 벡터 검색으로 위임 (max_hops=%d)",
                        rp, mh,
                    )
                elif graph_payload.get("context_snippets") and quality >= 0.3:
                    search_results = self._build_graph_search_results(graph_payload)
                    use_graph_rag = True
                    logger.info(
                        "GraphReasoner [%s] 검색 완료 (max_hops=%d, %d 스니펫, quality=%.2f)",
                        rp, mh, len(graph_payload.get("context_snippets", [])), quality,
                    )
                elif graph_payload.get("context_snippets"):
                    logger.info(
                        "GraphReasoner [%s] quality 부족 (%.2f < 0.3), 기본 벡터 검색으로 폴백",
                        rp, quality,
                    )
                else:
                    logger.info("GraphReasoner 결과 스니펫이 없어 기본 RAG로 대체")
            except Exception as exc:
                logger.warning("GraphReasoner 실행 실패, 기본 RAG로 전환: %s", exc)

        if not use_graph_rag:
            # 1. 라우팅 및 검색 (기존 RAG)
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before search")
            search_results = self.router.search(
                query,
                top_k=top_k,
                cancellation_event=cancellation_event,
                allowed_document_uuids=allowed_document_uuids,
                session_id=session_id,
            )
        

        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before response generation")

        # 3. 답변 생성
        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before generation")
        results = self.generator.generate_response(
            query,
            search_results,
            cancellation_event=cancellation_event,
            allowed_document_uuids=allowed_document_uuids,
        )

        if use_graph_rag and graph_payload:
            results["graph_reasoner"] = graph_payload
            notes = graph_payload.get("notes") or []
            results.setdefault("answer_notes", notes)
        
        # 4. 피드백 루프 (필요시)
        if self.config.use_feedback_loop:
            results = self.evaluator.feedback_loop(
                query, 
                results, 
                self.router, 
                self.generator
            )
        
        # 5. 이미지 결과 처리 및 base64 변환
        processed_images = []
        image_paths = []
        processed_ids = set()  # 중복 방지를 위한 ID 추적
        
        # search_results에서 이미지 문서 추출 및 처리
        
        # 모든 이미지 문서를 수집
        all_image_docs = []
        
        # 1. 직접 image_documents 키에서 수집
        if isinstance(search_results, dict) and 'image_documents' in search_results:
            all_image_docs.extend(search_results['image_documents'])
        
        # 2. searcher별 구조에서 수집 (하위 호환성)
        for searcher_name, searcher_results in search_results.items():
            if searcher_name in ["text_documents", "image_documents", "metadata"]:
                continue
            
            if isinstance(searcher_results, dict) and 'image_documents' in searcher_results:
                all_image_docs.extend(searcher_results['image_documents'])
        
        # 3. 수집된 모든 이미지 문서를 한 번에 처리 (중복 제거)
        for img_doc in all_image_docs:
            # ID 기반 중복 체크
            doc_id = img_doc.get('id')
            if doc_id and doc_id in processed_ids:
                logger.debug(f"중복된 이미지 문서 건너뜀: {doc_id}")
                continue
            
            # 이미지 처리
            self._process_image_document(img_doc, processed_images, image_paths)
            
            # 처리된 ID 기록
            if doc_id:
                processed_ids.add(doc_id)
        
        # 처리된 이미지를 결과에 추가
        if processed_images:
            results['images'] = processed_images
            results['image_count'] = len(processed_images)
            logger.info(f"이미지 처리 완료: {len(processed_images)}개")
        
        if image_paths:
            results['image_paths'] = image_paths

        # 취소 확인
        if cancellation_event and cancellation_event.is_set():
            raise InterruptedError("Operation cancelled before refinement")

        # 6. 답변 정제 (필요시)
        if self.config.use_refiner and self.refiner is not None and "answer" in results:
            original_answer = results.get("answer", "")
            logger.info(f"Refiner 입력 (원본 답변): {original_answer[:150]}...")
            
            # 취소 확인
            if cancellation_event and cancellation_event.is_set():
                raise InterruptedError("Operation cancelled before refinement")
            refined_answer = self.refiner.refine_answer(query, original_answer, cancellation_event=cancellation_event)
            results["answer"] = refined_answer
            logger.info(f"Refiner 출력 (정제된 답변): {refined_answer[:150]}...")
        elif self.config.use_refiner and self.refiner is None:
            logger.warning("Refiner가 초기화되지 않아 답변 정제를 건너뜁니다.")

        # 7. 최종 결과 정리
        # 최종적으로 사용할 context 정보 저장
        results["context"] = results.get("context_used", "")
        # 최종 결과에 검색 결과 포함
        results["search_results"] = search_results

        # 디버그 모드가 아닐 경우, 응답에 불필요한 중간 데이터 제거
        if not self.config.debug_mode:
            keys_to_delete = ["context_used", "evaluation", "feedback_history"]
            for key in keys_to_delete:
                if key in results:
                    del results[key]
        
        logger.info("질문 처리 완료")
        return results

def main():
    """명령줄 인터페이스"""
    parser = argparse.ArgumentParser(description="RAG 시스템 실행")
    parser.add_argument("--query", type=str, help="처리할 질문")
    parser.add_argument("--top-k", type=int, default=5, help="반환할 최대 결과 수")
    parser.add_argument("--debug", action="store_true", help="디버그 모드 활성화")
    parser.add_argument("--interactive", action="store_true", help="대화형 모드 실행")
    
    args = parser.parse_args()
    
    # 파이프라인 초기화
    pipeline = RAGPipeline()
    
    # 디버그 모드 설정
    if args.debug:
        pipeline.config["debug_mode"] = True
    
    # 대화형 모드
    if args.interactive:
        print("\n=== RAG 시스템 대화형 모드 ===")
        print("종료하려면 'exit' 또는 'quit'을 입력하세요.\n")
        
        while True:
            try:
                query = input("\n질문: ")
                if query.lower() in ["exit", "quit", "종료"]:
                    break
                
                final_results = pipeline.process_query(query, args.top_k)
                print(f"\n답변: {final_results.get('answer', '답변을 생성하지 못했습니다.')}")

                if args.debug:
                    print("\n--- DEBUG INFO ---")
                    print(json.dumps(final_results, indent=2, ensure_ascii=False))
                    print("--- END DEBUG INFO ---")

            except (KeyboardInterrupt, EOFError):
                break
        print("\n대화형 모드를 종료합니다.")

    # 단일 질문 처리
    elif args.query:
        final_results = pipeline.process_query(args.query, args.top_k)
        
        print(f"\n질문: {args.query}")
        print(f"\n답변: {final_results.get('answer', '답변을 생성하지 못했습니다.')}")
        
        if args.debug:
            print("\n--- DEBUG INFO ---")
            # 디버그 모드에서는 전체 결과를 예쁘게 출력
            print(json.dumps(final_results, indent=2, ensure_ascii=False))
            print("--- END DEBUG INFO ---")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
