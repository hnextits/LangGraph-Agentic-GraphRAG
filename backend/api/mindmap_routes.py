"""
Mindmap API Routes
마인드맵 생성 API
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
import uuid
import os
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/mindmap", tags=["Mindmap"])

# SGLang 기반 마인드맵 생성기 임포트
try:
    from skill.mindmap.mindmap_generator import generate_mindmap_for_api
    from skill.mindmap import generate_mermaid_html, generate_interactive_html
    logger.info("SGLang 기반 MindMapGenerator 모듈 임포트 성공")
except ImportError as e:
    logger.error(f"MindMapGenerator 모듈 임포트 실패: {e}")
    generate_mindmap_for_api = None


# 작업 상태 저장소
mindmap_tasks: Dict[str, Dict[str, Any]] = {}

# 마인드맵 저장 디렉토리
MINDMAP_DIR = Path(__file__).parent.parent / "nextits_data" / "Results" / "8.mindmap"
MINDMAP_DIR.mkdir(parents=True, exist_ok=True)


# === Pydantic 모델 ===
class MindmapGenerateRequest(BaseModel):
    """마인드맵 생성 요청"""
    filename: str
    max_topics: Optional[int] = 8


class MindmapTaskResponse(BaseModel):
    """작업 응답"""
    task_id: str
    status: str
    message: Optional[str] = None


class MindmapStatusResponse(BaseModel):
    """작업 상태 응답"""
    task_id: str
    status: str
    message: Optional[str] = None
    progress: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MindmapListResponse(BaseModel):
    """마인드맵 목록 응답"""
    mindmaps: List[str]


class MindmapContentResponse(BaseModel):
    """마인드맵 내용 응답"""
    filename: str
    format: str
    content: str


# === 백그라운드 작업 함수 ===
async def generate_mindmap_task(task_id: str, filename: str, max_topics: int):
    """백그라운드에서 마인드맵 생성 (원본 알고리즘 사용)"""
    try:
        logger.info(f"[{task_id}] 마인드맵 생성 시작: {filename}")
        mindmap_tasks[task_id] = {
            "status": "processing",
            "message": "파일 읽는 중...",
            "progress": 10
        }
        
        # 3.OCR_results에서만 파일 찾기
        base_dir = Path(__file__).parent.parent / "nextits_data"
        ocr_dir = base_dir / "Results" / "3.OCR_results"
        file_path = ocr_dir / filename
        
        if not file_path.exists():
            raise FileNotFoundError(f"3.OCR_results에서 파일을 찾을 수 없습니다: {filename}")
        
        # 파일 내용 읽기
        with open(file_path, 'r', encoding='utf-8') as f:
            document_content = f.read()
        
        if not document_content or document_content.isspace():
            raise ValueError("파일 내용이 비어있습니다")
        
        mindmap_tasks[task_id].update({
            "message": "마인드맵 생성 중...",
            "progress": 20
        })
        
        # 별도 프로세스로 마인드맵 생성 스크립트 실행
        import subprocess
        import json
        import tempfile
        
        # 원본 파일명을 유지하면서 임시 파일 생성
        base_filename = Path(filename).stem
        temp_dir = Path(tempfile.gettempdir())
        tmp_path = temp_dir / f"{base_filename}.txt"
        
        with open(tmp_path, 'w', encoding='utf-8') as tmp:
            tmp.write(document_content)
        
        try:
            # 별도 프로세스로 실행
            backend_dir = Path(__file__).parent.parent  # backend 디렉토리
            script_path = backend_dir / "skill" / "mindmap" / "mindmap_generator.py"
            
            # PYTHONPATH 환경변수 설정
            import os
            env = os.environ.copy()
            env['PYTHONPATH'] = str(backend_dir)
            
            cmd = [
                "python",
                "-u",  # unbuffered output (실시간 로그)
                str(script_path),
                str(tmp_path),
                "--request-id", task_id,
                "--max-topics", str(max_topics),
                "--output-json"  # JSON 형식으로 결과 출력
            ]
            
            # subprocess 실행 (stdout=JSON, stderr=로그)
            logger.info(f"[{task_id}] 마인드맵 생성 프로세스 시작...")
            
            try:
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10분 타임아웃
                    cwd=str(backend_dir),
                    env=env
                )
            except subprocess.TimeoutExpired:
                raise Exception("마인드맵 생성 타임아웃 (10분)")
            
            # stderr 로그 출력
            if process.stderr:
                for line in process.stderr.split('\n'):
                    if line.strip():
                        logger.info(f"[{task_id}] {line.strip()}")
            
            if process.returncode != 0:
                logger.error(f"[{task_id}] Exit code: {process.returncode}")
                logger.error(f"[{task_id}] Stderr: {process.stderr}")
                raise Exception(f"마인드맵 생성 실패 (exit code: {process.returncode})")
            
            # stdout이 비어있는지 확인
            if not process.stdout or not process.stdout.strip():
                logger.error(f"[{task_id}] stdout이 비어있습니다")
                logger.error(f"[{task_id}] stderr: {process.stderr}")
                raise Exception("마인드맵 생성 실패: 출력 없음")
            
            # JSON 결과 파싱
            try:
                result = json.loads(process.stdout)
            except json.JSONDecodeError as e:
                logger.error(f"[{task_id}] JSON 파싱 실패: {e}")
                logger.error(f"[{task_id}] stdout 내용: {process.stdout[:500]}")
                raise Exception(f"JSON 파싱 실패: {e}")
        finally:
            # 임시 파일 삭제
            Path(tmp_path).unlink(missing_ok=True)
        
        if not result or result.get("status") != "success":
            raise Exception("마인드맵 생성 실패")
        
        # 파일 경로에서 내용 읽기
        output_files = result.get("output_files", {})
        
        # 파일명 추출
        mermaid_file = None
        markdown_file = None
        html_file = None
        interactive_html_file = None
        
        for filepath in output_files.keys():
            filename = Path(filepath).name
            if filename.endswith('_mindmap.txt'):
                mermaid_file = filename
            elif filename.endswith('_mindmap_outline.md'):
                markdown_file = filename
            elif filename.endswith('_mindmap.html'):
                html_file = filename
                interactive_html_file = filename  # 동일한 파일
        
        # 완료
        mindmap_tasks[task_id].update({
            "status": "completed",
            "message": "마인드맵 생성 완료",
            "progress": 100,
            "result": {
                "mermaid_file": mermaid_file,
                "markdown_file": markdown_file,
                "html_file": html_file,
                "interactive_html_file": interactive_html_file,
                "generated_at": datetime.now().isoformat()
            }
        })
        
        logger.info(f"[{task_id}] 마인드맵 생성 완료")
        
    except Exception as e:
        logger.error(f"[{task_id}] 마인드맵 생성 실패: {e}", exc_info=True)
        mindmap_tasks[task_id] = {
            "status": "failed",
            "message": "마인드맵 생성 실패",
            "progress": 100,
            "error": str(e)
        }


# === API 엔드포인트 ===

@router.post("/generate", response_model=MindmapTaskResponse)
async def generate_mindmap(
    request: MindmapGenerateRequest,
    background_tasks: BackgroundTasks
):
    """
    마인드맵 생성 시작
    
    - **filename**: 마인드맵을 생성할 파일명
    - **max_topics**: 최대 주제 수 (기본값: 8)
    """
    task_id = str(uuid.uuid4())
    
    # 백그라운드 작업 추가
    background_tasks.add_task(
        generate_mindmap_task,
        task_id,
        request.filename,
        request.max_topics
    )
    
    mindmap_tasks[task_id] = {
        "status": "pending",
        "message": "마인드맵 생성 대기 중...",
        "progress": 0
    }
    
    return {
        "task_id": task_id,
        "status": "pending",
        "message": "마인드맵 생성이 시작되었습니다"
    }


@router.get("/status/{task_id}", response_model=MindmapStatusResponse)
async def get_mindmap_status(task_id: str):
    """
    마인드맵 생성 상태 확인
    
    - **task_id**: 작업 ID
    """
    if task_id not in mindmap_tasks:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    
    task = mindmap_tasks[task_id]
    
    return {
        "task_id": task_id,
        "status": task.get("status", "unknown"),
        "message": task.get("message"),
        "progress": task.get("progress"),
        "result": task.get("result"),
        "error": task.get("error")
    }


@router.get("/list", response_model=MindmapListResponse)
async def list_mindmaps():
    """
    생성된 마인드맵 목록 조회
    """
    try:
        # HTML 파일만 목록에 표시
        mindmaps = [
            f.name for f in MINDMAP_DIR.iterdir() 
            if f.is_file() and f.suffix == '.html'
        ]
        mindmaps.sort(reverse=True)  # 최신순
        
        return {"mindmaps": mindmaps}
        
    except Exception as e:
        logger.error(f"마인드맵 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/content/{filename}")
async def get_mindmap_content(filename: str, format: str = "html"):
    """
    마인드맵 내용 조회
    
    - **filename**: 파일명 (확장자 제외)
    - **format**: 출력 형식 (html, markdown, mermaid)
    """
    try:
        base_filename = Path(filename).stem
        
        # 형식에 따라 파일 찾기
        if format == "html":
            file_path = MINDMAP_DIR / f"{base_filename}.html"
        elif format == "markdown" or format == "md":
            file_path = MINDMAP_DIR / f"{base_filename}.md"
        elif format == "mermaid" or format == "mmd":
            file_path = MINDMAP_DIR / f"{base_filename}.mmd"
        else:
            # 확장자가 포함된 경우
            file_path = MINDMAP_DIR / filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return {
            "filename": file_path.name,
            "format": format,
            "content": content
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"마인드맵 내용 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{filename}")
async def delete_mindmap(filename: str):
    """
    마인드맵 삭제 (관련된 모든 형식 파일 삭제)
    
    - **filename**: 파일명
    """
    try:
        base_filename = Path(filename).stem
        deleted_files = []
        
        # 모든 형식 파일 삭제
        for ext in ['.html', '.md', '.mmd']:
            file_path = MINDMAP_DIR / f"{base_filename}{ext}"
            if file_path.exists():
                file_path.unlink()
                deleted_files.append(file_path.name)
        
        if not deleted_files:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
        
        return {
            "message": "마인드맵이 삭제되었습니다",
            "deleted_files": deleted_files
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"마인드맵 삭제 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
