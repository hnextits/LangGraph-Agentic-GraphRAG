import os
import subprocess
import sys
import time

import magic
from PIL import Image
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.data_pipeline.pipe.bootstrap import ensure_backend_root
from backend.data_pipeline.pipe.parser import (
    convert_to_pdf,
    is_office_file,
    SUPPORTED_OFFICE_EXTENSIONS,
)

ensure_backend_root()

load_dotenv()

# 디렉토리 설정
# LAYOUT_DIR = "/home/nextits2/.conda/envs/workbox/image_test/data_pipeline/Results/2.LayoutDetection"
CONVERTED = os.getenv("CONVERTED")


def log_stage_event(stage: str, status: str, message: str = ""):
    """단계별 진행 상황을 일관되게 출력"""
    prefix = f"[PIPELINE][{stage}] {status}"
    if message:
        prefix += f" - {message}"
    print(prefix, flush=True)


def is_pdf_file(file_path: str) -> bool:
    """
    파일이 PDF인지 확인합니다.
    """
    # 파일 확장자 확인
    if file_path.lower().endswith('.pdf'):
        return True
        
    # MIME 타입 확인
    try:
        mime = magic.Magic(mime=True)
        mime_type = mime.from_file(file_path)
        return mime_type == 'application/pdf'
    except Exception:
        # 오류 발생 시 확장자만으로 판단
        return False

def is_image_file(file_path: str) -> bool:
    """
    파일이 이미지인지 확인합니다.
    """
    # 이미지 확장자 확인
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp']
    if any(file_path.lower().endswith(ext) for ext in image_extensions):
        return True
        
    # MIME 타입 확인
    try:
        mime = magic.Magic(mime=True)
        mime_type = mime.from_file(file_path)
        return mime_type.startswith('image/')
    except Exception:
        # 오류 발생 시 확장자만으로 판단
        return False

def is_sound_file(file_path: str) -> bool:
    """
    파일이 음성, 영상인지 확인합니다.
    """
    # 이미지 확장자 확인
    sound_extensions = ['.wav', '.mp3', '.ogg', '.flac', '.webm', '.mp4', '.mov', '.avi', '.wmv' ]
    if any(file_path.lower().endswith(ext) for ext in sound_extensions):
        return True
        
    # MIME 타입 확인
    try:
        mime = magic.Magic(mime=True)
        mime_type = mime.from_file(file_path)
        return mime_type.startswith('sound/')
    except Exception:
        # 오류 발생 시 확장자만으로 판단
        return False

def run_udp_checkfiletype():
    """
    udp_checkfiletype.py 스크립트를 실행하고 결과 파일 목록을 반환합니다.
    """
    try:
        script_path = Path(__file__).parent / 'main_pipe/UDP_File_meta.py'
        if not script_path.exists():
            print(f"오류: 스크립트를 찾을 수 없습니다: {script_path}")
            return []
            
        print(f"UDP_File_meta.py 스크립트 실행 중...")
        
        # 스크립트 실행
        subprocess.run(
            [sys.executable, str(script_path)],
            check=True
        )
        
        print("스크립트 실행 완료")
        
        # 메타데이터 파일에서 결과 가져오기
        metadata_file = Path(__file__).parent.parent / 'doc/metadata/file_metadata.json'
        if metadata_file.exists():
            import json
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
                
            # 파일 목록 추출 (metadata 키에서 파일 경로 가져오기)
            file_paths = [item['file_path'] for item in metadata['metadata']]
            return file_paths
        else:
            print(f"오류: 메타데이터 파일을 찾을 수 없습니다: {metadata_file}")
            return []
            
    except Exception as e:
        print(f"오류: 스크립트 실행 중 오류 발생: {str(e)}")
        return []

def process_file(file_path: str, skip_existing: bool = True, resume: bool = True, results_base: Path = None):
    """
    파일을 처리하고 유형을 판단합니다.
    
    Args:
        file_path (str): 처리할 파일 경로
        skip_existing (bool): 이미 처리된 파일은 건너뛸지 여부
        resume (bool): 중단된 작업을 이어서 처리할지 여부
        results_base (Path): 결과 저장 최상위 경로
    """
    if results_base is None:
        results_base = Path(__file__).parent.parent / 'Results'

    file_type = "알 수 없음"
    
    if is_pdf_file(file_path):
        file_type = "PDF"
        print(f"PDF 파일 감지: {file_path}")
        # PDF 처리 알고리즘 실행 (udp_pdftopng_300dpi.py)
        process_pdf_file(file_path, skip_existing=skip_existing, resume=resume, results_base=results_base)

    elif is_office_document(file_path):
        file_type = "Office"
        print(f"Office/HWP 파일 감지: {file_path}")
        # Office → PDF 변환 후 PDF 파이프라인 재사용
        pdf_output_dir = results_base / '0.Office_converted_pdf'
        pdf_output_dir.mkdir(parents=True, exist_ok=True)

        converted_pdf = convert_to_pdf(file_path, output_dir=str(pdf_output_dir))
        if converted_pdf:
            print(f"변환된 PDF로 처리 진행: {converted_pdf}")
            pdf_ok = process_pdf_file(converted_pdf, skip_existing=skip_existing, resume=resume, results_base=results_base)
            if not pdf_ok:
                raise RuntimeError(f"PDF 처리(PDF→PNG) 실패: {converted_pdf}")
            file_type = "PDF"
        else:
            print(f"Office → PDF 변환 실패: {file_path}")
            raise RuntimeError(f"Office → PDF 변환 실패: {file_path}")

    elif is_image_file(file_path):
        file_type = "이미지"
        print(f"이미지 파일 감지: {file_path}")
        # 이미지 처리 알고리즘 실행 (UVDoc/demo.py)
        process_image_file(file_path, skip_existing=skip_existing, resume=resume, results_base=results_base)

    elif is_sound_file(file_path):
        file_type = "음성"
        print(f"음성 파일 감지: {file_path}")
        process_sound_file(file_path, skip_existing=skip_existing, resume=resume, results_base=results_base)
        
    else:
        print(f"지원되지 않는 파일 유형: {file_path}")
    
    return file_type

def is_office_document(file_path: str) -> bool:
    """
    Office/HWP/HWPX 파일인지 확인합니다.
    """
    return is_office_file(file_path)

def process_image_file(file_path: str, skip_existing: bool = True, resume: bool = True, results_base: Path = None):
    """
    이미지 파일을 처리합니다. UVDoc/demo.py를 실행하여 이미지 왕곡 보정을 수행합니다.
    
    Args:
        file_path (str): 처리할 이미지 파일 경로
        skip_existing (bool): 이미 처리된 파일은 건너뛸지 여부
        resume (bool): 중단된 작업을 이어서 처리할지 여부
        results_base (Path): 결과 저장 최상위 경로
    """
    if results_base is None:
        results_base = Path(__file__).parent.parent / 'Results'

    try:
        print(f"이미지 파일 처리 중: {file_path}")
        
        # demo.py 스크립트 경로
        script_path = Path(__file__).parent.parent / 'UVDoc/demo.py'
        if not script_path.exists():
            print(f"오류: 이미지 처리 스크립트를 찾을 수 없습니다: {script_path}")
            log_stage_event("IMAGE_UNWARP", "FAILED", "스크립트 없음")
            return False
        
        # 기본 출력 디렉토리
        output_dir = results_base / '1.Converted_images/IMG'
        
        # 출력 디렉토리 생성
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 이미지 파일명으로 폴더 생성
        image_name = Path(file_path).stem
        image_folder = output_dir / image_name
        image_folder.mkdir(parents=True, exist_ok=True)
        
        # 출력 파일 경로
        output_file = image_folder / f"{image_name}_unwarp.png"
        
        # 이미 처리된 파일이 있는지 확인
        if skip_existing and os.path.exists(output_file):
            print(f"이미 처리된 파일이 존재합니다: {output_file}. 건너뜁니다.")
            log_stage_event("IMAGE_UNWARP", "SKIPPED", f"{image_name}")
            return True
        
        # 원본 이미지 복사
        import shutil
        original_copy = image_folder / Path(file_path).name
        shutil.copy2(file_path, original_copy)
        print(f"원본 이미지 복사됨: {original_copy}")
        
        # demo.py가 생성할 출력 파일 경로 계산
        expected_output = str(original_copy).rsplit('.', 1)[0] + "_unwarp.png"
        
        # 모델 경로
        model_path = Path(__file__).parent.parent / 'UVDoc/model/best_model.pkl'
        if not model_path.exists():
            print(f"오류: 모델 파일을 찾을 수 없습니다: {model_path}")
            return False
        
        # demo.py 실행
        print(f"이미지 왕곡 보정 중... (출력 디렉토리: {image_folder})")
        result = subprocess.run(
            [sys.executable, str(script_path), '--ckpt-path', str(model_path), '--img-path', str(original_copy)],
            text=True,
            check=False
        )
        
        # 결과 출력
        if result.returncode == 0:
            print(f"이미지 처리 성공: {file_path}")
            # 처리 결과 확인
            if os.path.exists(expected_output):
                # 원하는 경로로 파일 이동
                output_file = image_folder / f"{image_name}_unwarp.png"
                if expected_output != str(output_file):
                    shutil.move(expected_output, output_file)
                print(f"이미지 처리 성공: {file_path} -> {output_file}")
                log_stage_event("IMAGE_UNWARP", "SUCCESS", f"{image_name}")
                return True
            else:
                print(f"오류: 처리된 파일을 찾을 수 없습니다: {expected_output}")
                log_stage_event("IMAGE_UNWARP", "FAILED", "출력 파일 없음")
                return False
        else:
            print(f"이미지 처리 실패: {result.stderr}")
            log_stage_event("IMAGE_UNWARP", "FAILED", "스크립트 실행 오류")
            return False
            
    except Exception as e:
        print(f"이미지 처리 중 오류 발생: {str(e)}")
        log_stage_event("IMAGE_UNWARP", "FAILED", str(e))
        import traceback
        traceback.print_exc()
        return False

def process_sound_file(file_path: str, skip_existing: bool = True, resume: bool = True, results_base: Path = None):
    """음성 또는 영상 파일을 STT 파이프라인에 전달하고 결과를 저장합니다.
    
    저장 위치:
    - 4.OCR_results: 화자 정보 포함 (클릭 시 표시용)
    - 7.stt: 텍스트만 (임베딩용)
    """
    if results_base is None:
        results_base = Path(__file__).parent.parent / 'Results'

    try:
        print(f"음성/영상 파일 처리 중: {file_path}")

        # 4.OCR_results와 7.stt 디렉토리에서 이미 처리된 파일 확인
        ocr_results_dir = results_base / '4.OCR_results'
        stt_dir = results_base / '7.stt'
        ocr_results_dir.mkdir(parents=True, exist_ok=True)
        stt_dir.mkdir(parents=True, exist_ok=True)
        
        ocr_path = ocr_results_dir / f"{Path(file_path).stem}.md"
        stt_path = stt_dir / f"{Path(file_path).stem}.md"
        
        if skip_existing and ocr_path.exists() and stt_path.exists():
            print(f"이미 처리된 음성/영상 결과가 존재하여 건너뜁니다:")
            print(f"  - 화자 정보 포함: {ocr_path}")
            print(f"  - 텍스트만: {stt_path}")
            log_stage_event("STT", "SKIPPED", Path(file_path).stem)
            return True

        # STT 파이프라인 실행 (필요할 때만 import)
        from pipeline_sound import run_sound_pipeline
        result = run_sound_pipeline(file_path, markdown_dir=None)

        if not result or not result.get("text_path") or not result.get("markdown_path"):
            print("경고: STT 결과가 비어 있거나 경로를 찾을 수 없습니다.")
            return False

        print(f"음성/영상 처리 완료:")
        print(f"  - 화자 정보 포함: {result['markdown_path']}")
        print(f"  - 텍스트만: {result['text_path']}")
        log_stage_event("STT", "SUCCESS", Path(file_path).stem)
        return True

    except Exception as e:
        print(f"음성/영상 처리 중 오류 발생: {str(e)}")
        log_stage_event("STT", "FAILED", str(e))
        import traceback
        traceback.print_exc()
        return False

def process_pdf_file(file_path: str, skip_existing: bool = True, resume: bool = True, results_base: Path = None):
    """
    PDF 파일을 처리합니다. udp_pdftopng_300dpi.py를 사용하여 PNG로 변환합니다.
    
    Args:
        file_path (str): 처리할 PDF 파일 경로
        skip_existing (bool): 이미 처리된 파일은 건너뛸지 여부
        resume (bool): 중단된 작업을 이어서 처리할지 여부
        results_base (Path): 결과 저장 최상위 경로
    """
    if results_base is None:
        results_base = Path(__file__).parent.parent / 'Results'

    try:
        print(f"PDF 파일 처리 중: {file_path}")
        
        # udp_pdftopng_300dpi.py에서 PDF2PNGForLayout 클래스 import
        try:
            from main_pipe.udp_pdftopng_300dpi import PDF2PNGForLayout
        except ImportError as e:
            print(f"오류: PDF 변환 모듈을 import할 수 없습니다: {e}")
            return False
        
        # 기본 출력 디렉토리 (PDF 폴더)
        base_output_dir = results_base / '1.Converted_images/PDF'
        base_output_dir.mkdir(parents=True, exist_ok=True)
        
        # PDF 파일명으로 하위 폴더 생성
        pdf_name = Path(file_path).stem
        pdf_output_dir = base_output_dir / pdf_name
        pdf_output_dir.mkdir(parents=True, exist_ok=True)
        
        # 이미 처리된 파일 건너뛰기 기능
        if skip_existing:
            # 출력 디렉토리에 PNG 파일이 있는지 확인
            existing_pngs = list(pdf_output_dir.glob("*.png"))
            if existing_pngs:
                # PDF 페이지 수와 PNG 파일 수 비교를 위해 PDF 정보 확인
                try:
                    import fitz
                    doc = fitz.open(file_path)
                    total_pages = doc.page_count
                    doc.close()
                    
                    # PNG 파일 수가 적어도 1개 이상이면 처리된 것으로 간주
                    # (레벨 필터링으로 인해 전체 페이지보다 적을 수 있음)
                    print(f"이미 처리된 PDF 파일입니다: {file_path}")
                    print(f"PDF 총 페이지 수: {total_pages}개")
                    print(f"기존 PNG 파일 수: {len(existing_pngs)}개")
                    print(f"출력 디렉토리: {pdf_output_dir}")
                    return True
                except Exception as e:
                    print(f"PDF 정보 확인 중 오류: {e}")
                    # 오류가 발생해도 PNG 파일이 있으면 처리된 것으로 간주
                    print(f"이미 처리된 PDF 파일입니다: {file_path}")
                    print(f"기존 PNG 파일 수: {len(existing_pngs)}개")
                    print(f"출력 디렉토리: {pdf_output_dir}")
                    log_stage_event("PDF_TO_PNG", "SKIPPED", f"{file_path} ({len(existing_pngs)} png)")
                    return True
        
        print(f"PDF를 PNG로 변환 중... (출력 디렉토리: {pdf_output_dir})")
        
        # PDF2PNGForLayout 인스턴스 생성
        converter = PDF2PNGForLayout()
        
        # PDF 변환 실행
        result_files = converter.convert_pdf(
            pdf_path=str(file_path),
            output_dir=str(pdf_output_dir),
            dpi=150,  # udp_pdftopng_300dpi.py의 기본값 사용
            long_side=1280,  # udp_pdftopng_300dpi.py의 기본값 사용
            remove_marks=True,
            margin_percent=0.00,
            skip_existing=skip_existing,
            resume=resume,
            max_workers=64,  # udp_pdftopng_300dpi.py의 기본값 사용
            filter_by_level=True
        )
        
        # 결과 출력
        if result_files:
            print(f"PDF 변환 성공: {file_path}")
            print(f"출력 디렉토리: {pdf_output_dir}")
            print(f"생성된 파일 수: {len(result_files)}개")
            log_stage_event("PDF_TO_PNG", "SUCCESS", f"{file_path} ({len(result_files)} png)")
            return result_files
        else:
            print(f"PDF 변환 실패: 결과 파일이 없습니다.")
            log_stage_event("PDF_TO_PNG", "FAILED", "결과 파일 없음")
            return False
            
    except Exception as e:
        print(f"PDF 처리 중 오류 발생: {str(e)}")
        log_stage_event("PDF_TO_PNG", "FAILED", str(e))
        import traceback
        traceback.print_exc()
        return False

def run_layout_detection(input_dir=None, output_dir=None, skip_existing=True, resume=True):
    """
    레이아웃 감지 스크립트를 실행합니다.
    
    Args:
        input_dir (Path): 입력 디렉토리 (변환된 이미지가 저장된 디렉토리)
        output_dir (Path): 출력 디렉토리 (레이아웃 감지 결과가 저장될 디렉토리)
        skip_existing (bool): 이미 처리된 파일은 건너뛸지 여부
        resume (bool): 중단된 작업을 이어서 처리할지 여부
    """
    try:
        import time
        start = time.time()
        print("\n레이아웃 감지 시작...")
        
        # udp_layoutdetection.py 스크립트 경로
        script_path = Path(__file__).parent / 'main_pipe/udp_layoutdetection.py'
        if not script_path.exists():
            print(f"오류: 레이아웃 감지 스크립트를 찾을 수 없습니다: {script_path}")
            log_stage_event("LAYOUT_DETECTION", "FAILED", "스크립트 없음")
            return False
        
        # 기본 디렉토리 설정 (인자로 전달되지 않은 경우)
        if input_dir is None:
            input_dir = Path(__file__).parent.parent / 'Results/1.Converted_images'
        
        if output_dir is None:
            output_dir = Path(__file__).parent.parent / 'Results/2.LayoutDetection'
        
        # 출력 디렉토리 생성
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 명령행 인수 구성
        cmd = [sys.executable, str(script_path), '--input_dir', str(input_dir), '--output_dir', str(output_dir)]
        
        # 건너뛰기 옵션 추가
        if not skip_existing:
            cmd.append('--no_skip_existing')
        
        # 이어서 처리하기 옵션 추가
        if not resume:
            cmd.append('--no_resume')
        
        # test_LayouyDetection.py 실행
        print(f"레이아웃 감지 실행 중... (입력 디렉토리: {input_dir}, 출력 디렉토리: {output_dir})")
        print(f"옵션: 이미 처리된 파일 건너뛰기={skip_existing}, 중단된 작업 이어서 처리하기={resume}")
        
        # subprocess.run 대신 Popen을 사용하여 실시간 로그 출력 보장
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # stderr를 stdout으로 통합
            text=True,
            bufsize=1 # Line buffering
        )

        # read1/read fallback: 줄바꿈 없는 출력(tqdm 등)도 바로 전달되도록 chunk 단위로 읽는다
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                if process.poll() is not None:
                    break
                # 프로세스는 아직 살아있고 출력이 없으면 잠깐 쉰다
                time.sleep(0.05)
                continue
            print(chunk, end='', flush=True)

        returncode = process.wait()
        
        print(f"레이아웃 감지 소요 시간: {time.time() - start}초")
        # 결과 출력
        if returncode == 0:
            print("레이아웃 감지 성공!")
            log_stage_event("LAYOUT_DETECTION", "SUCCESS")
            return True
        else:
            print(f"레이아웃 감지 실패: returncode={returncode}")
            log_stage_event("LAYOUT_DETECTION", "FAILED", f"returncode={returncode}")
            return False
            
    except Exception as e:
        print(f"레이아웃 감지 중 오류 발생: {str(e)}")
        log_stage_event("LAYOUT_DETECTION", "FAILED", str(e))
        return False

def run_image_pipeline(
    skip_existing: bool = True,
    resume: bool = True,
    add_numbering: bool = True,
    min_width: int = 200,
    min_height: int = 200,
    max_width: int = 800,
    max_height: int = 850,
    results_base: Path = None,
):
    """
    이미지 파이프라인 스크립트(pipeline_image.py)를 실행하는 함수
    """
    if results_base is None:
        results_base = Path(__file__).parent.parent / 'Results'

    try:
        print("\n===== 이미지 파이프라인 실행 중... =====\n")
        pipeline_script = Path(__file__).parent / 'pipeline_image.py'
        if not pipeline_script.exists():
            print(f"오류: 이미지 파이프라인 스크립트를 찾을 수 없습니다: {pipeline_script}")
            log_stage_event("IMAGE_PIPELINE", "FAILED", "스크립트 없음")
            return False

        cmd = [sys.executable, str(pipeline_script)]
        
        # 결과 베이스 디렉토리 전달 (pipeline_image.py가 이를 지원하도록 수정 필요할 수 있음)
        # 현재는 환경 변수나 인자로 전달 가능하다고 가정
        if results_base:
            cmd.extend(['--results_base', str(results_base)])

        if skip_existing is not None:
            cmd.append('--skip_existing' if skip_existing else '--no_skip_existing')
        if resume is not None:
            cmd.append('--resume' if resume else '--no_resume')
        if add_numbering is not None:
            cmd.append('--add_numbering' if add_numbering else '--no_add_numbering')
        if min_width is not None:
            cmd.append(f'--min_width={min_width}')
        if min_height is not None:
            cmd.append(f'--min_height={min_height}')
        if max_width is not None:
            cmd.append(f'--max_width={max_width}')
        if max_height is not None:
            cmd.append(f'--max_height={max_height}')

        subprocess.run(cmd, check=True)
        print("\n===== 이미지 파이프라인 완료 =====\n")
        log_stage_event("IMAGE_PIPELINE", "SUCCESS")
        return True
    except Exception as e:
        print(f"이미지 파이프라인 실행 중 오류 발생: {str(e)}")
        log_stage_event("IMAGE_PIPELINE", "FAILED", str(e))
        import traceback
        traceback.print_exc()
        return False


def run_ocr_processing(image_source_dir, exclude_labels=None, skip_ocr=False, skip_existing=True, resume=True, batch_size=64, output_dir=None):
    """`inference.py`를 사용하여 OCR 처리를 수행합니다.

    Args:
        image_source_dir: OCR을 수행할 이미지가 저장된 상위 디렉토리.
        exclude_labels: 제외할 레이블 목록 (현재 사용되지 않음).
        skip_ocr: OCR 처리 건너뛰기 여부.
        skip_existing: 기존 파일 건너뛰기 여부.
        resume: 중단된 작업 이어서 처리 여부 (현재 사용되지 않음).
        batch_size: 배치 크기.
        output_dir: 결과를 저장할 디렉토리 (기본값: Results/4.OCR_results).

    Returns:
        bool: OCR 처리 성공 여부.
    """
    if skip_ocr:
        print("OCR 처리 건너뛰기 옵션이 설정되어 있습니다.")
        log_stage_event("OCR", "SKIPPED", "skip_ocr=True")
        return True

    print(f"\n===== OCR 처리 시작 (Using inference.py) =====\n")

    try:
        # inference.py에서 필요한 함수와 설정 import
        from main_pipe.ocr_pipe.inference import process_image_folder, CONFIG as ocr_config
    except ImportError as e:
        print(f"오류: OCR 추론 모듈을 import할 수 없습니다: {e}")
        print("경로가 정확한지, `__init__.py` 파일이 필요한지 확인하세요.")
        return False

    # 결과를 저장할 최상위 폴더 설정
    if output_dir is None:
        ocr_results_dir = Path(__file__).parent.parent / 'Results/4.OCR_results'
    else:
        ocr_results_dir = Path(output_dir)
    
    ocr_results_dir.mkdir(parents=True, exist_ok=True)

    # layout_output_dir의 하위 폴더들을 순회
    # (e.g., Results/1.Converted_images/PDF/doc1, Results/1.Converted_images/IMG/img1)
    subfolders = [d for d in Path(image_source_dir).rglob('*') if d.is_dir() and any(f.suffix.lower() in ['.png', '.jpg', '.jpeg'] for f in d.glob('*.*'))]

    if not subfolders:
        print(f"오류: {image_source_dir} 에서 처리할 이미지 폴더를 찾을 수 없습니다.")
        log_stage_event("OCR", "FAILED", "입력 폴더 없음")
        return False

    print(f"총 {len(subfolders)}개의 폴더에 대해 OCR을 실행합니다.")
    success_count = 0

    for i, folder in enumerate(subfolders, 1):
        folder_name = folder.name
        print(f"\n--- [{i}/{len(subfolders)}] 폴더 처리 중: {folder_name} ---")

        # 이미 결과 파일이 있는지 확인
        expected_output_file = ocr_results_dir / f"{folder_name}.md"
        if skip_existing and expected_output_file.exists():
            print(f"결과 파일이 이미 존재하여 건너뜁니다: {expected_output_file}")
            success_count += 1
            log_stage_event("OCR", "SKIPPED", folder_name)
            continue

        try:
            # OCR 설정 복사 및 수정
            current_config = ocr_config.copy()
            current_config['input_image_folder'] = str(folder)
            current_config['output_folder'] = str(ocr_results_dir)
            current_config['batch_size'] = batch_size

            # OCR 실행
            process_image_folder(current_config)
            success_count += 1

        except Exception as e:
            print(f"폴더 {folder_name} 처리 중 오류 발생: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n===== OCR 처리 완료 =====\n")
    print(f"성공적으로 처리된 폴더: {success_count}/{len(subfolders)}")
    print(f"결과 저장 위치: {ocr_results_dir}")

    if success_count > 0:
        log_stage_event("OCR", "SUCCESS", f"{success_count}/{len(subfolders)} 폴더")
        return True
    log_stage_event("OCR", "FAILED", "처리된 폴더 없음")
    return False

def main():
    """
    메인 함수
    """
    try:
        # 명령행 인수 파싱
        import argparse
        parser = argparse.ArgumentParser(description="파일 처리 파이프라인")
        parser.add_argument("--file", type=str, help="처리할 파일 경로")
        parser.add_argument("--session_id", type=str, help="세션 ID")
        parser.add_argument("--skip_existing", action="store_true", help="이미 처리된 파일 건너뛰기")
        parser.add_argument("--no_skip_existing", dest="skip_existing", action="store_false", help="이미 처리된 파일도 다시 처리")
        parser.add_argument("--resume", action="store_true", help="중단된 작업 이어서 처리하기")
        parser.add_argument("--no_resume", dest="resume", action="store_false", help="처음부터 다시 처리하기")
        parser.add_argument("--skip_ocr", action="store_true", help="OCR 처리 건너뛰기")
        parser.add_argument("--batch_size", type=int, default=256, help="OCR 배치 크기 (기본값: 256)")
        parser.set_defaults(skip_existing=True, resume=True, skip_ocr=False)
        args = parser.parse_args()
        
        # 세션 경로 설정
        script_dir = Path(__file__).resolve().parent
        data_dir = script_dir.parent
        results_base = data_dir / 'Results'
        if args.session_id:
            results_base = data_dir / 'sessions' / args.session_id / 'Results'
            results_base.mkdir(parents=True, exist_ok=True)
            print(f"세션 모드 활성화: {args.session_id}, 결과 저장 위치: {results_base}")

        # 파일 경로가 지정되지 않은 경우 모든 파일 처리
        if not args.file:
            # udp_checkfiletype.py 실행하고 결과 파일 목록 가져오기 (세션 디렉토리 고려 필요 시 수정)
            file_paths = run_udp_checkfiletype()
            
            if file_paths:
                print(f"\n총 {len(file_paths)}개의 파일을 찾았습니다. 처리를 시작합니다...")
                
                # 파일 통계 초기화
                stats = {
                    'total': len(file_paths),
                    'pdf': 0,
                    'image': 0,
                    'other': 0,
                    'processed': 0,
                    'failed': 0
                }
                
                # 모든 파일 처리
                for idx, file_path in enumerate(file_paths, 1):
                    print(f"\n[{idx}/{len(file_paths)}] 파일 처리 중: {file_path}")
                    
                    if os.path.isfile(file_path):
                        # process_file 내부에서도 results_base를 사용하도록 수정
                        file_type = process_file(file_path, skip_existing=args.skip_existing, resume=args.resume, results_base=results_base)
                        
                        if file_type == "PDF":
                            stats['pdf'] += 1
                        elif file_type == "이미지":
                            stats['image'] += 1
                        else:
                            stats['other'] += 1
                    else:
                        print(f"오류: 유효한 파일이 아닙니다: {file_path}")
                        stats['failed'] += 1
                
                # 처리 결과 출력
                print("\n===== 파일 처리 결과 =====")
                print(f"총 파일: {stats['total']}개")
                print(f"PDF 파일: {stats['pdf']}개")
                print(f"이미지 파일: {stats['image']}개")
                print(f"기타 파일: {stats['other']}개")
                print(f"실패한 파일: {stats['failed']}개")
                
                # PDF 파일이 처리되었다면 레이아웃 감지 실행
                if stats['pdf'] > 0:
                    input_dir = results_base / '1.Converted_images'
                    output_dir = results_base / '2.LayoutDetection'
                    if run_layout_detection(input_dir, output_dir, args.skip_existing, args.resume):
                        # OCR 처리 실행 (입력 소스: 변환된 이미지 디렉토리)
                        ocr_results_dir = results_base / '4.OCR_results'
                        ocr_success = run_ocr_processing(input_dir, exclude_labels=["image", "table", "formula"], 
                                          skip_ocr=args.skip_ocr, 
                                          skip_existing=args.skip_existing, 
                                          resume=args.resume,
                                          batch_size=args.batch_size,
                                          output_dir=ocr_results_dir)
                        
                        if ocr_success:
                            print("\n===== OCR 처리 완료 =====\n")
                            
                            # 이미지 파이프라인 실행
                            run_image_pipeline(
                                skip_existing=args.skip_existing,
                                resume=args.resume,
                                results_base=results_base
                            )
                        
                        print("\n===== 파일 처리 완료 =====\n")
                    else:
                        print("\n오류: 처리할 파일을 찾을 수 없습니다.")
                else:
                    print("\n오류: 처리할 PDF 파일을 찾을 수 없습니다.")
            else:
                print("\n오류: 처리할 파일을 찾을 수 없습니다.")
        else:
            # 특정 파일만 처리
            file_path = args.file
            if os.path.isfile(file_path):
                # process_file이 사용하는 결과를 세션 경로로 변경하려면 process_file도 수정해야 함
                # 일단 여기서 필요한 디렉토리들은 session_id 기준으로 설정
                file_type = process_file(file_path, skip_existing=args.skip_existing, resume=args.resume, results_base=results_base)
                print(f"\n파일 유형: {file_type}")
                
                # PDF 또는 이미지 파일인 경우 레이아웃 감지 및 OCR 실행
                if file_type in ["PDF", "이미지"]:
                    input_dir = results_base / '1.Converted_images'
                    output_dir = results_base / '2.LayoutDetection'
                    
                    # 이미지 파일의 경우 1.Converted_images/IMG 하위를 참조해야 할 수도 있음
                    # 하지만 현재 구조상 1.Converted_images 전체를 input으로 쓰는 것이 안전
                    if run_layout_detection(input_dir, output_dir, args.skip_existing, args.resume):
                        # OCR 처리 실행 (입력 소스: 변환된 이미지 디렉토리)
                        ocr_results_dir = results_base / '4.OCR_results'
                        ocr_success = run_ocr_processing(input_dir, exclude_labels=["image", "table", "formula"], 
                                          skip_ocr=args.skip_ocr, 
                                          skip_existing=args.skip_existing, 
                                          resume=args.resume,
                                          batch_size=args.batch_size,
                                          output_dir=ocr_results_dir)
                        
                        if ocr_success:
                            # 이미지 파이프라인 실행
                            run_image_pipeline(results_base=results_base)
                        else:
                            raise RuntimeError("OCR 처리 실패 또는 산출물 없음")
                    else:
                        raise RuntimeError("레이아웃 감지 실패")
                elif file_type == "음성":
                    print("음성 파일 처리 완료 (STT 파이프라인)")
                else:
                    raise RuntimeError(f"지원되지 않거나 처리 실패한 파일 유형: {file_type}")
            else:
                print(f"오류: 유효한 파일이 아닙니다: {file_path}")
                raise RuntimeError(f"유효하지 않은 파일 경로: {file_path}")
            
    except Exception as e:
        print(f"오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
