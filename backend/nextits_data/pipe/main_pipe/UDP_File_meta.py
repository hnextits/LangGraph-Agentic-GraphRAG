import os
import json
import magic
import time
import hashlib
import shutil
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import mimetypes
from pathlib import Path
from dotenv import load_dotenv
from typing import Union, Optional

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
class EnvManager:
    """
    환경 변수 관리를 위한 클래스
    """
    def __init__(self, env_path: Optional[Union[str, Path]] = None):
        """
        EnvManager 초기화
        
        매개변수:
            env_path (Optional[Union[str, Path]]): .env 파일 경로 (기본값: None)
        """
        # .env 파일 경로 설정
        self.env_path = Path(env_path) if env_path else None
        
        # .env 파일이 있으면 로드 (없어도 오류 발생 X)
        if self.env_path and self.env_path.exists():
            load_dotenv(self.env_path)
        
    def get_target_directory(self) -> str:
        """
        대상 디렉토리 경로를 반환
        
        반환값:
            str: 대상 디렉토리 경로
        """
        # 현재 스크립트 위치를 기준으로 상대 경로 계산
        base_dir = Path(__file__).resolve().parent.parent.parent
        target_dir = base_dir / "doc"  # 기본값으로 doc 폴더 사용
        return str(target_dir)

    def get_output_json_path(self, target_dir: Optional[str] = None) -> str:
        """
        출력 JSON 파일 경로를 반환
        
        매개변수:
            target_dir (Optional[str]): 대상 디렉토리 경로 (기본값: self.get_target_directory())
            
        반환값:
            str: 출력 JSON 파일 경로
        """
        base_dir = target_dir if target_dir else self.get_target_directory()
        output_json = str(Path(base_dir) / "metadata" / "file_metadata.json")
        
        # 디렉토리 생성
        os.makedirs(os.path.dirname(output_json), exist_ok=True)
        
        return output_json
        
    def get_paths(self) -> Tuple[str, str]:
        """
        대상 디렉토리와 출력 JSON 파일 경로를 튜플로 반환
        
        반환값:
            Tuple[str, str]: (target_dir, output_json) 경로 튜플
        """
        return self.get_target_directory(), self.get_output_json_path()

def cleanup_old_backups(directory: str, file_pattern: str, months: int = 3) -> None:
    """
    지정된 기간보다 오래된 백업 파일을 삭제합니다.
    
    매개변수:
        directory (str): 백업 파일이 있는 디렉토리 경로
        file_pattern (str): 백업 파일 패턴 (예: 'file_metadata.json.*.bak')
        months (int): 보관할 최대 개월 수 (기본값: 3)
    """
    import glob
    import re
    
    # 현재 시간에서 지정된 개월 수를 뺀 시간 계산
    cutoff_date = datetime.now() - timedelta(days=30 * months)
    
    # 패턴에 맞는 모든 백업 파일 찾기
    backup_files = glob.glob(os.path.join(directory, file_pattern))
    
    # 날짜 추출 정규식 패턴 (YYYYMMDDHHMMSS 형식)
    date_pattern = re.compile(r'\.(\d{14})\.bak$')
    
    for backup_file in backup_files:
        match = date_pattern.search(backup_file)
        if match:
            date_str = match.group(1)
            try:
                # 백업 파일의 날짜 파싱
                file_date = datetime.strptime(date_str, '%Y%m%d%H%M%S')
                
                # 기준일보다 오래된 파일 삭제
                if file_date < cutoff_date:
                    os.remove(backup_file)
                    logging.info(f"오래된 백업 파일 삭제: {backup_file}")
            except (ValueError, OSError) as e:
                logging.error(f"백업 파일 처리 중 오류 발생: {backup_file} - {e}")

def backup_existing_file(file_path: str) -> None:
    """
    기존 파일이 있으면 .bak 확장자로 백업합니다.
    
    매개변수:
        file_path (str): 백업할 파일 경로
    """
    if not os.path.exists(file_path):
        return
        
    backup_path = f"{file_path}.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
    try:
        shutil.copy2(file_path, backup_path)
        logging.info(f"기존 파일이 백업되었습니다: {backup_path}")
        
        # 오래된 백업 파일 정리
        directory = os.path.dirname(file_path)
        file_pattern = f"{os.path.basename(file_path)}.*.bak"
        cleanup_old_backups(directory, file_pattern)
    except Exception as e:
        logging.error(f"파일 백업 중 오류 발생: {e}")

def get_file_metadata(file_path: str) -> Dict[str, Any]:
    """
    파일의 메타데이터를 수집합니다.
    
    매개변수:
        file_path (str): 메타데이터를 수집할 파일 경로
        
    반환값:
        Dict[str, Any]: 파일 메타데이터를 포함한 딕셔너리
    """
    if not os.path.isfile(file_path):
        return {}
    
    # 파일 기본 정보
    stat_info = os.stat(file_path)
    
    # 파일 해시 계산 (MD5)
    file_hash = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            file_hash.update(chunk)
    
    # MIME 타입 감지
    mime = magic.Magic(mime=True, mime_encoding=True)
    mime_type = mime.from_file(file_path)
    
    # 파일 확장자로부터 MIME 타입 추정
    mime_guess = mimetypes.guess_type(file_path)
    
    # 파일 설명 (MIME 타입 설명)
    mime_desc = magic.Magic()
    file_description = mime_desc.from_file(file_path)
    
    return {
        'file_path': file_path,
        'file_name': os.path.basename(file_path),
        'file_size': stat_info.st_size,  # 바이트 단위
        'file_extension': os.path.splitext(file_path)[1].lower(),
        'file_hash_md5': file_hash.hexdigest(),
        'mime_type': mime_type,
        'mime_encoding': mime_type.split(';')[1].strip() if ';' in mime_type else None,
        'mime_type_guess': mime_guess[0],
        'mime_encoding_guess': mime_guess[1],
        'file_description': file_description,
        'created_time': datetime.fromtimestamp(stat_info.st_ctime).isoformat(),
        'modified_time': datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
        'accessed_time': datetime.fromtimestamp(stat_info.st_atime).isoformat(),
        'is_file': os.path.isfile(file_path),
        'is_dir': os.path.isdir(file_path),
        'is_link': os.path.islink(file_path),
        'file_mode': oct(stat_info.st_mode)[-3:],  # 파일 권한 (8진수)
        'inode': stat_info.st_ino,
        'device': stat_info.st_dev,
    }

def list_files_recursively(directory):
    """
    주어진 디렉토리와 하위 디렉토리의 모든 파일을 재귀적으로 탐색하여 리스트로 반환합니다.
    metadata 폴더는 검색에서 제외합니다.
    
    매개변수:
        directory (str): 검색할 디렉토리 경로
        
    반환값:
        list: 파일 경로들의 리스트
    """
    files = []
    
    for root, dirs, filenames in os.walk(directory):
        # metadata 폴더 제외
        if 'metadata' in dirs:
            dirs.remove('metadata')
        
        for filename in filenames:
            file_path = os.path.join(root, filename)
            if os.path.isfile(file_path):
                files.append(file_path)
    
    return files

def save_metadata_to_json(metadata_list: List[Dict[str, Any]], output_file: str) -> None:
    """
    메타데이터 리스트를 JSON 파일로 저장합니다.
    
    매개변수:
        metadata_list (List[Dict[str, Any]]): 저장할 메타데이터 리스트
        output_file (str): 출력할 JSON 파일 경로 (상대 경로)
    """
    try:
        # 현재 작업 디렉토리 기준으로 절대 경로 생성
        base_dir = Path.cwd()
        output_path = Path(output_file)
        
        # 상위 디렉토리 생성 (없는 경우)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 기존 파일 백업
        if output_path.exists():
            backup_existing_file(str(output_path))
        
        # JSON으로 직렬화 (한글 깨짐 방지를 위해 ensure_ascii=False)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                'metadata': metadata_list,
                'total_files': len(metadata_list),
                'generated_at': datetime.now().isoformat(),
                'version': '1.0',
                'source_directory': str(base_dir)
            }, f, ensure_ascii=False, indent=2, default=str)
        
        logging.info(f"메타데이터 저장 완료: {output_path} (처리된 파일 수: {len(metadata_list)}개)")
        
    except Exception as e:
        logging.error(f"JSON 파일 저장 중 오류가 발생했습니다: {e}")
        raise

def main(target_dir: Optional[str] = None):
    try:
        # 환경 변수에서 설정 로드
        env_manager = EnvManager()
        
        # 외부에서 target_dir이 제공된 경우 그것을 사용, 아니면 기본값 사용
        if not target_dir:
            target_dir, output_json = env_manager.get_paths()
        else:
            output_json = env_manager.get_output_json_path(target_dir)
        
        # 디렉토리 존재 여부 확인
        if not os.path.exists(target_dir):
            logging.error(f"'{target_dir}' 디렉토리가 존재하지 않습니다.")
            return
            
        if not os.path.isdir(target_dir):
            logging.error(f"'{target_dir}'는 디렉토리가 아닙니다.")
            return
        
        logging.info(f"'{target_dir}' 디렉토리에서 파일을 검색 중입니다...")
        
        # 재귀적으로 모든 파일 가져오기
        files = list_files_recursively(target_dir)
        
        if not files:
            logging.info("디렉토리 내에 파일이 없습니다.")
            return
        
        logging.info(f"총 {len(files)}개의 파일을 찾았습니다. 메타데이터를 수집 중입니다...")
        
        # 각 파일에 대한 메타데이터 수집
        metadata_list = []
        total_files = len(files)
        
        for idx, file_path in enumerate(files, 1):
            try:
                if idx % 100 == 0 or idx == 1 or idx == total_files:
                    logging.info(f"[{idx}/{total_files}] 처리 중...")
                metadata = get_file_metadata(file_path)
                if metadata:  # 메타데이터가 있는 경우에만 추가
                    metadata_list.append(metadata)
            except Exception as e:
                logging.error(f"{file_path} 처리 중 오류 발생 - {str(e)}")
                continue
        
        if not metadata_list:
            logging.warning("처리 가능한 파일이 없습니다.")
            return
            
        # 메타데이터를 JSON 파일로 저장
        save_metadata_to_json(metadata_list, output_json)
        
        # 오래된 백업 파일 정리
        directory = os.path.dirname(output_json)
        file_pattern = f"{os.path.basename(output_json)}.*.bak"
        cleanup_old_backups(directory, file_pattern)
        
    except Exception as e:
        logging.error(f"프로그램 실행 중 오류가 발생했습니다: {str(e)}")
        raise

if __name__ == "__main__":
    try:
        import magic  # 여기서 임포트하여 설치 여부 확인
        import sys
        from dotenv import load_dotenv
        main()
    except ImportError as e:
        logging.error(f"필요한 라이브러리가 설치되지 않았습니다: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"오류가 발생했습니다: {str(e)}")
        sys.exit(1)
