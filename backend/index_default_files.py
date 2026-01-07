#!/usr/bin/env python3
"""
기본 파일들을 Weaviate에 인덱싱하는 스크립트
세션 ID 없이 마스터 데이터로 저장됨
"""

import os
import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.append(str(Path(__file__).parent.parent))

from notebooklm.config import RAGConfig
from notebooklm.weaviate_utils import create_schema, batch_import_text_documents, batch_import_image_documents
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def process_default_files(target_file=None):
    """기본 파일들을 처리하여 Weaviate에 인덱싱"""
    config = RAGConfig()
    
    # 1. 스키마 생성
    logger.info("Weaviate 스키마 생성 중...")
    client = config.get_weaviate_client()
    if not client:
        logger.error("Weaviate 클라이언트 연결 실패")
        return False
    
    if not create_schema(client, recreate=False):
        logger.error("스키마 생성 실패")
        client.close()
        return False
    
    # 2. 처리할 파일들 결정
    if target_file:
        # 특정 파일만 처리
        pdf_files = [Path(target_file)]
        logger.info(f"특정 파일만 처리: {target_file}")
    else:
        # 기본 디렉토리의 모든 PDF 파일 처리
        logger.info(f"기본 파일 디렉토리: {config.DEFAULT_DOC_DIR}")
        
        if not config.DEFAULT_DOC_DIR.exists():
            logger.warning(f"기본 파일 디렉토리가 존재하지 않음: {config.DEFAULT_DOC_DIR}")
            client.close()
            return False
        
        pdf_files = list(config.DEFAULT_DOC_DIR.glob("*.pdf"))
    
    # 3. 파일 처리 파이프라인 실행
    logger.info("기본 파일들 처리 파이프라인 실행 중...")
    
    # 파일 처리 파이프라인 임포트
    pipe_dir = config.DATA_ROOT / "pipe"
    run_file_processor = pipe_dir / "run_file_processor.py"
    
    if not run_file_processor.exists():
        logger.error(f"파일 처리 파이프라인을 찾을 수 없음: {run_file_processor}")
        client.close()
        return False
    
    # 각 PDF 파일 처리
    for pdf_file in pdf_files:
        try:
            logger.info(f"처리 중: {pdf_file.name}")
            
            # 파일 처리 파이프라인 실행 (세션 ID 없이)
            import subprocess
            result = subprocess.run([
                sys.executable, 
                str(run_file_processor),
                "--file", str(pdf_file),
                "--no_skip_existing"  # 강제 재처리
            ], capture_output=True, text=True, cwd=str(config.DATA_ROOT))
            
            if result.returncode == 0:
                logger.info(f"✅ {pdf_file.name} 처리 완료")
            else:
                logger.error(f"❌ {pdf_file.name} 처리 실패: {result.stderr}")
                continue
            
            # 4. 텍스트 인덱싱
            logger.info(f"텍스트 인덱싱 중: {pdf_file.name}")
            
            # OCR 결과 파일 찾기
            ocr_results_dir = config.DATA_ROOT / "Results" / "4.OCR_results"
            base_name = pdf_file.stem
            
            # 가능한 파일명들
            candidate_files = [
                ocr_results_dir / f"{base_name}.md",
                ocr_results_dir / f"{base_name}.txt",
                ocr_results_dir / pdf_file.name
            ]
            
            processed_file = None
            for candidate in candidate_files:
                if candidate.exists():
                    processed_file = candidate
                    break
            
            if processed_file:
                # qwen3_late_chunking 실행
                from notebooklm.qwen3_late_chunking import process_markdown_files
                
                # 문서 UUID 생성
                from notebooklm.weaviate_utils import _compute_document_uuid_from_path
                document_uuid = _compute_document_uuid_from_path(str(pdf_file))
                
                # 텍스트 처리 (session_id=None으로 기본 파일로 표시)
                process_markdown_files(
                    client, 
                    [str(processed_file)], 
                    session_id=None  # 기본 파일들은 세션 ID 없음
                )
                
                # 클라이언트 연결 정리
                if client:
                    client.close()
                    client = None
                    
                logger.info(f"✅ {pdf_file.name} 텍스트 인덱싱 완료")
                
                # 5. 이미지 인덱싱
                logger.info(f"이미지 인덱싱 중: {pdf_file.name}")
                
                # 이미지 처리 결과 디렉토리
                layout_results_dir = config.DATA_ROOT / "Results" / "2.LayoutDetection" / "PDF" / pdf_file.stem
                
                if layout_results_dir.exists():
                    # 이미지 처리를 위해 JSON 파일들을 embedding_system 호환 형식으로 변환
                    import json
                    
                    # 임시 디렉토리 생성
                    temp_dir = config.DATA_ROOT / "temp_image_metadata"
                    temp_dir.mkdir(exist_ok=True)
                    
                    # 모든 JSON 파일을 순회하며 embedding_system 호환 형식으로 변환
                    for json_file in layout_results_dir.glob("*.json"):
                        try:
                            with open(json_file, 'r', encoding='utf-8') as f:
                                layout_data = json.load(f)
                            
                            # embedding_system 호환 형식으로 변환
                            converted_data = {
                                "metadata": {}
                            }
                            
                            # 이미지 경로 추출
                            input_path = layout_data.get("input_path", "")
                            if input_path and os.path.exists(input_path):
                                # 파일명에서 페이지 번호 추출
                                page_num = int(os.path.basename(input_path).split('.')[0])
                                
                                # metadata 객체 생성
                                item_id = f"{pdf_file.stem}_page_{page_num:03d}"
                                converted_data["metadata"][item_id] = {
                                    "id": item_id,
                                    "file_path": input_path,
                                    "image_path": input_path,
                                    "page_num": page_num,
                                    "title": f"{pdf_file.name} - Page {page_num}",
                                    "text": f"Page {page_num} of {pdf_file.name}",
                                    "con_type": "image"
                                }
                                
                                # 변환된 데이터 저장
                                temp_json = temp_dir / f"{json_file.stem}_converted.json"
                                with open(temp_json, 'w', encoding='utf-8') as f:
                                    json.dump(converted_data, f, ensure_ascii=False, indent=2)
                                    
                        except Exception as e:
                            logger.error(f"JSON 변환 오류 {json_file}: {e}")
                    
                    # embedding_system.py를 사용하여 이미지 임베딩 처리
                    from notebooklm.embedding_system import VectorDBService
                    
                    image_service = VectorDBService(content_type="image", recreate_schema=False)
                    indexed_images = image_service.process_json_data(
                        str(temp_dir), 
                        append_mode=True, 
                        content_type="image"
                    )
                    
                    # 임시 디렉토리 정리
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    
                    if indexed_images > 0:
                        logger.info(f"✅ {pdf_file.name} 이미지 인덱싱 완료: {indexed_images}개")
                    else:
                        logger.warning(f"❌ {pdf_file.name} 이미지 인덱싱 실패")
                else:
                    logger.warning(f"❌ {pdf_file.name} 레이아웃 감지 결과를 찾지 못함")
                    
            else:
                logger.warning(f"❌ {pdf_file.name} OCR 결과 파일을 찾지 못함")
            
        except Exception as e:
            logger.error(f"파일 처리 중 오류 {pdf_file.name}: {e}")
    
    # 마지막에 클라이언트 닫기
    if client is not None:
        client.close()
    logger.info("기본 파일 인덱싱 완료")
    return True

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="기본 파일들을 Weaviate에 인덱싱")
    parser.add_argument("--file", type=str, help="처리할 특정 파일 경로")
    args = parser.parse_args()
    
    success = process_default_files(target_file=args.file)
    if success:
        print("✅ 기본 파일 인덱싱 성공")
    else:
        print("❌ 기본 파일 인덱싱 실패")
        sys.exit(1)
