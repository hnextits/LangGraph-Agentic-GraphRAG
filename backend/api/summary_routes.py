from fastapi import APIRouter, Body, HTTPException
import os
import sys
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
search_test_dir = os.path.join(parent_dir, 'search_test')
sys.path.insert(0, search_test_dir)

# crawler_summary_llm 모듈 임포트
try:
    from crawler_summary_llm import AnswerGenerator
    logger.info("AnswerGenerator 모듈 임포트 성공")
except ImportError as e:
    logger.error(f"AnswerGenerator 모듈 임포트 실패: {e}")
    raise

# OCR 결과 디렉토리 경로
OCR_RESULTS_DIR = os.path.join(parent_dir, 'nextits_data', 'Results', '3.OCR_results')

# 라우터 생성
router = APIRouter()

# API 응답 모델 정의
class SummarizeRequest(BaseModel):
    file_names: List[str]

class SummarizeResponse(BaseModel):
    summary: str
    files: List[str]
    timestamp: str

# 요약 생성기 인스턴스 (싱글톤으로 관리)
answer_generator = None

def get_answer_generator():
    global answer_generator
    if answer_generator is None:
        answer_generator = AnswerGenerator()
        logger.info("AnswerGenerator 인스턴스 생성 완료")
    return answer_generator

@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_files(request_data: SummarizeRequest) -> SummarizeResponse:
    # 요청 본문에서 file_names 추출
    file_names = request_data.file_names
    """
    선택된 파일들을 요약하는 API 엔드포인트
    """
    logger.info(f"요약 요청 받음: {file_names}")
    
    try:
        # AnswerGenerator 인스턴스 가져오기
        generator = get_answer_generator()
        
        # OCR 결과 디렉토리 존재 여부 확인
        if not os.path.exists(OCR_RESULTS_DIR):
            logger.error(f"OCR 결과 디렉토리가 존재하지 않습니다: {OCR_RESULTS_DIR}")
            raise HTTPException(status_code=404, detail=f"OCR 결과 디렉토리가 존재하지 않습니다: {OCR_RESULTS_DIR}")
            
        # OCR 결과 디렉토리가 비어있는지 확인
        if not os.listdir(OCR_RESULTS_DIR):
            logger.error(f"OCR 결과 디렉토리가 비어 있습니다: {OCR_RESULTS_DIR}")
            raise HTTPException(status_code=404, detail=f"OCR 결과 디렉토리가 비어 있습니다. OCR 처리가 완료되었는지 확인하세요.")
            
        # 파일 내용 수집
        file_contents = []
        missing_files = []
        for file_name in file_names:
            file_path = os.path.join(OCR_RESULTS_DIR, file_name)
            if not os.path.exists(file_path):
                logger.warning(f"파일을 찾을 수 없음: {file_path}")
                missing_files.append(file_name)
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    file_contents.append({
                        "title": file_name,
                        "content": content
                    })
                logger.info(f"파일 로드 성공: {file_name}")
            except Exception as e:
                logger.error(f"파일 읽기 오류 ({file_name}): {str(e)}")
        
        if not file_contents:
            if missing_files:
                raise HTTPException(status_code=404, detail=f"요청한 파일을 찾을 수 없습니다: {', '.join(missing_files)}")
            else:
                raise HTTPException(status_code=404, detail="유효한 파일을 찾을 수 없습니다")
        
        # 임시 저장 디렉토리 설정
        temp_dir = os.path.join(parent_dir, 'nextits_data', 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        
        # 파일 내용을 make_llm_input_data에 맞는 형식으로 변환
        formatted_data = []
        for item in file_contents:
            formatted_data.append({
                "link": item["title"],  # 파일명을 링크로 사용
                "data": item["content"],  # 파일 내용을 데이터로 사용
                "google_snipping": ""  # 빈 스니핑
            })
        
        # make_llm_input_data 호출하여 입력 데이터 생성
        processed_data = generator.make_llm_input_data(temp_dir, formatted_data)
        
        # generate_answer 호출하여 요약 생성
        summary = generator.generate_answer(processed_data)
        
        # 요약 결과 저장 디렉토리 설정
        summary_dir = os.path.join(parent_dir, 'nextits_data', 'summarize')
        os.makedirs(summary_dir, exist_ok=True)

        # 타임스탬프 기반 파일명 생성
        timestamp = generator.get_timestamp().replace(" ", "_").replace(":", "-")
        summary_filename = f"summary_{timestamp}.md"
        summary_path = os.path.join(summary_dir, summary_filename)

        # 요약 결과를 마크다운 파일로 저장
        with open(summary_path, "w", encoding="utf-8") as f:
            # 헤더 정보 추가
            f.write(f"# 요약 결과 ({generator.get_timestamp()})\n\n")
            f.write(f"## 요약 대상 파일\n")
            for file_name in file_names:
                f.write(f"- {file_name}\n")
            f.write("\n## 요약 내용\n\n")
            f.write(summary)

        # API 응답에 파일 경로 추가
        return {
            "summary": summary,
            "files": file_names,
            "timestamp": generator.get_timestamp(),
            "summary_file": summary_path  # 저장된 파일 경로 추가
        }
        
    except Exception as e:
        logger.error(f"요약 생성 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"요약 생성 중 오류 발생: {str(e)}")
