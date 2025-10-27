"""
FastAPI Server for MD Summarizer
기존 nextitslm 시스템과 동일한 API 인터페이스 제공
"""

from fastapi import FastAPI, HTTPException, File, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from pathlib import Path
import uuid
import os
from datetime import datetime
from loguru import logger

from .sglang_client import SGLangClient
from .md_parser import MDParser
from .summary_index import MDSummaryIndex


# Pydantic 모델 정의 (기존 시스템과 동일)
class SummarizeRequest(BaseModel):
    filenames: List[str]

class SummarizeResponse(BaseModel):
    summary: str
    files: List[str]
    timestamp: str
    summary_file: Optional[str] = None

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    message: Optional[str] = None
    progress: Optional[int] = None
    result: Optional[Any] = None
    error: Optional[str] = None

class SearchRequest(BaseModel):
    query: str
    top_k: int = 3

class SearchResponse(BaseModel):
    results: List[Dict[str, Any]]


# FastAPI 앱 초기화
app = FastAPI(
    title="MD Summarizer API",
    description="SGLang + Qwen 기반 문서 요약 시스템",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 전역 변수
sglang_endpoints = [
    "http://localhost:30000",
    "http://localhost:30001"
]
summarizer = None
tasks = {}

# 경로 설정
BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
SUMMARIZE_DIR = RESULTS_DIR / "summaries"
UPLOAD_DIR = RESULTS_DIR / "uploads"

# 디렉토리 생성
for dir_path in [RESULTS_DIR, SUMMARIZE_DIR, UPLOAD_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 초기화"""
    global summarizer
    
    logger.info("MD Summarizer API 서버 시작")
    logger.info(f"SGLang 엔드포인트: {sglang_endpoints}")
    
    # 요약 시스템 초기화
    summarizer = MDSummaryIndex(sglang_endpoints)
    
    logger.info("초기화 완료")


@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "MD Summarizer API",
        "version": "1.0.0",
        "endpoints": {
            "summarize": "/api/v1/summarize",
            "search": "/api/v1/search",
            "tasks": "/api/v1/tasks/{task_id}",
            "statistics": "/api/v1/statistics"
        }
    }


@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/api/v1/summarize", response_model=SummarizeResponse)
async def summarize_files(request_data: SummarizeRequest):
    """
    파일 요약 API (기존 시스템과 동일한 인터페이스)
    
    Args:
        request_data: 요약할 파일명 리스트
        
    Returns:
        SummarizeResponse: 요약 결과
    """
    file_names = request_data.filenames
    logger.info(f"요약 요청 받음: {file_names}")
    
    try:
        # SGLang 클라이언트 생성
        client = SGLangClient(sglang_endpoints)
        
        # 파일 내용 수집
        file_contents = []
        missing_files = []
        
        for file_name in file_names:
            # 업로드된 파일 경로
            file_path = UPLOAD_DIR / file_name
            
            if not file_path.exists():
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
                raise HTTPException(
                    status_code=404,
                    detail=f"요청한 파일을 찾을 수 없습니다: {', '.join(missing_files)}"
                )
            else:
                raise HTTPException(status_code=404, detail="유효한 파일을 찾을 수 없습니다")
        
        # 각 파일 요약 생성
        summaries = []
        for item in file_contents:
            try:
                summary = client.generate_answer(item["content"])
                if summary and summary != "(관련된 구글 검색 결과를 찾을 수 없습니다)":
                    summaries.append(f"## {item['title']}\n\n{summary}")
            except Exception as e:
                logger.error(f"요약 생성 오류 ({item['title']}): {e}")
        
        if not summaries:
            raise HTTPException(status_code=500, detail="요약 생성에 실패했습니다")
        
        # 최종 요약 결합
        final_summary = "\n\n---\n\n".join(summaries)
        
        # 요약 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_filename = f"summary_{timestamp}.md"
        summary_path = SUMMARIZE_DIR / summary_filename
        
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"# 요약 결과 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})\n\n")
            f.write(f"## 요약 대상 파일\n")
            for file_name in file_names:
                f.write(f"- {file_name}\n")
            f.write("\n## 요약 내용\n\n")
            f.write(final_summary)
        
        logger.info(f"요약 완료: {summary_path}")
        
        return {
            "summary": final_summary,
            "files": file_names,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary_file": str(summary_path)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"요약 생성 중 오류 발생: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"요약 생성 중 오류 발생: {str(e)}")


@app.post("/api/v1/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    파일 업로드 API
    
    Args:
        file: 업로드할 파일
        
    Returns:
        dict: 업로드 결과
    """
    try:
        file_path = UPLOAD_DIR / file.filename
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        logger.info(f"파일 업로드 성공: {file.filename}")
        
        return {
            "message": "파일 업로드 성공",
            "filename": file.filename,
            "size": file_path.stat().st_size
        }
        
    except Exception as e:
        logger.error(f"파일 업로드 오류: {e}")
        raise HTTPException(status_code=500, detail=f"파일 업로드 실패: {str(e)}")


@app.post("/api/v1/search", response_model=SearchResponse)
async def search_documents(request: SearchRequest):
    """
    문서 검색 API (요약 인덱스 기반)
    
    Args:
        request: 검색 쿼리
        
    Returns:
        SearchResponse: 검색 결과
    """
    try:
        if not summarizer.documents:
            raise HTTPException(status_code=404, detail="인덱싱된 문서가 없습니다")
        
        results = summarizer.search(request.query, request.top_k)
        
        return {"results": results}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"검색 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"검색 실패: {str(e)}")


@app.get("/api/v1/statistics")
async def get_statistics():
    """
    시스템 통계 정보 API
    
    Returns:
        dict: 통계 정보
    """
    try:
        stats = summarizer.get_statistics()
        return stats
    except Exception as e:
        logger.error(f"통계 조회 오류: {e}")
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {str(e)}")


@app.get("/api/v1/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    작업 상태 조회 API (기존 시스템과 호환)
    
    Args:
        task_id: 작업 ID
        
    Returns:
        TaskStatusResponse: 작업 상태
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail=f"작업 ID {task_id}를 찾을 수 없습니다")
    
    return TaskStatusResponse(**tasks[task_id])


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.api_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
