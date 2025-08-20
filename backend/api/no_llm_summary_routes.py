from fastapi import APIRouter, Body, HTTPException, BackgroundTasks
import os
import sys
import logging
import json
import uuid
from typing import List, Dict, Any
from datetime import datetime

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
search_test_dir = os.path.join(parent_dir, 'search_test')
sys.path.insert(0, search_test_dir)

# 필요한 모듈 임포트
try:
    from crawler_pipeline import search, crawling_web
    from first_summary_no_llm import summarize_markdown_file
    logger.info("크롤링 및 요약 모듈 임포트 성공")
except ImportError as e:
    logger.error(f"모듈 임포트 실패: {e}")
    raise

# 라우터 생성
router = APIRouter()

# 작업 상태 저장소
task_status = {}

# 크롤링 결과 저장 디렉토리
CRAWLING_DIR = os.path.join(parent_dir, 'search_test', 'Crawling_data')
SNIPPET_DIR = os.path.join(CRAWLING_DIR, '4.snippet')
CLEAN_MD_DIR = os.path.join(CRAWLING_DIR, '6.clean_md')

# 디렉토리 생성
os.makedirs(SNIPPET_DIR, exist_ok=True)
os.makedirs(CLEAN_MD_DIR, exist_ok=True)

@router.post("/search_and_summarize")
async def search_and_summarize(
    background_tasks: BackgroundTasks,
    request_data: dict = Body(...)
):
    """
    검색어를 받아 구글 검색 결과를 크롤링하고 LLM 없이 요약하는 API 엔드포인트
    """
    query = request_data.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="검색어가 필요합니다")
    
    # 작업 ID 생성
    task_id = str(uuid.uuid4())
    task_status[task_id] = {
        "status": "pending",
        "message": "작업이 대기 중입니다",
        "progress": 0,
        "result": None,
        "error": None
    }
    
    # 백그라운드 작업으로 검색 및 요약 실행
    background_tasks.add_task(
        process_search_and_summarize,
        task_id=task_id,
        query=query
    )
    
    return {"task_id": task_id, "status": "pending"}

@router.get("/task_status/{task_id}")
async def get_task_status(task_id: str):
    """
    작업 상태를 확인하는 API 엔드포인트
    """
    if task_id not in task_status:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    
    return task_status[task_id]

async def process_search_and_summarize(task_id: str, query: str):
    """
    백그라운드에서 검색, 크롤링, 요약을 처리하는 함수
    """
    try:
        # 상태 업데이트: 검색 시작
        task_status[task_id].update({
            "status": "running",
            "message": "구글 검색 중...",
            "progress": 10
        })
        
        # 1. 구글 검색 수행
        total_result_link = []
        results = search(query, 5, total_result_link)
        
        if not results:
            task_status[task_id].update({
                "status": "completed",
                "message": "검색 결과가 없습니다",
                "progress": 100,
                "result": {"summary": "검색 결과가 없습니다", "sources": []}
            })
            return
        
        # 상태 업데이트: 크롤링 시작
        task_status[task_id].update({
            "status": "running",
            "message": "웹 페이지 크롤링 중...",
            "progress": 30
        })
        
        # 2. 크롤링 수행
        crawled_files = []
        for i, result in enumerate(results):
            try:
                # 크롤링 수행
                file_path = crawling_web(result=result, output_dir=SNIPPET_DIR)
                if file_path and os.path.exists(file_path):
                    crawled_files.append({
                        "title": result.get("title", "제목 없음"),
                        "link": result.get("link", ""),
                        "file_path": file_path
                    })
                    
                # 진행률 업데이트 (30% ~ 70%)
                progress = 30 + int((i + 1) / len(results) * 40)
                task_status[task_id].update({
                    "message": f"웹 페이지 크롤링 중... ({i+1}/{len(results)})",
                    "progress": progress
                })
            except Exception as e:
                logger.error(f"크롤링 중 오류 발생 ({result.get('link', '')}): {str(e)}")
                # 오류가 발생해도 계속 진행
        
        if not crawled_files:
            task_status[task_id].update({
                "status": "completed",
                "message": "크롤링된 파일이 없습니다",
                "progress": 100,
                "result": {"summary": "크롤링된 파일이 없습니다", "sources": []}
            })
            return
        
        # 상태 업데이트: 요약 시작
        task_status[task_id].update({
            "status": "running",
            "message": "크롤링된 내용 요약 중...",
            "progress": 70
        })
        
        # 3. 요약 수행
        summaries = []
        sources = []
        
        for i, file_info in enumerate(crawled_files):
            try:
                # 파일 요약
                summary = summarize_markdown_file(file_info["file_path"], ratio=0.3)
                
                if summary and summary != "요약할 텍스트가 없습니다.":
                    summaries.append(summary)
                    sources.append({
                        "title": file_info["title"],
                        "link": file_info["link"],
                        "summary": summary[:200] + "..." if len(summary) > 200 else summary
                    })
                
                # 진행률 업데이트 (70% ~ 90%)
                progress = 70 + int((i + 1) / len(crawled_files) * 20)
                task_status[task_id].update({
                    "message": f"요약 중... ({i+1}/{len(crawled_files)})",
                    "progress": progress
                })
            except Exception as e:
                logger.error(f"요약 중 오류 발생 ({file_info['file_path']}): {str(e)}")
                # 오류가 발생해도 계속 진행
        
        # 4. 최종 결과 생성
        if not summaries:
            final_summary = "요약할 내용이 없습니다."
        else:
            # 모든 요약을 하나로 합침
            final_summary = f"# '{query}'에 대한 검색 결과 요약\n\n"
            for i, summary in enumerate(summaries):
                final_summary += f"## 출처 {i+1}: {sources[i]['title']}\n\n{summary}\n\n"
        
        # 결과 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = os.path.join(CLEAN_MD_DIR, f"summary_{timestamp}.md")
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(final_summary)
        
        # 상태 업데이트: 완료
        task_status[task_id].update({
            "status": "completed",
            "message": "요약이 완료되었습니다",
            "progress": 100,
            "result": {
                "summary": final_summary,
                "sources": sources,
                "result_file": result_file
            }
        })
        
    except Exception as e:
        logger.error(f"작업 처리 중 오류 발생: {str(e)}", exc_info=True)
        task_status[task_id].update({
            "status": "failed",
            "message": f"오류 발생: {str(e)}",
            "progress": 100,
            "error": str(e)
        })
