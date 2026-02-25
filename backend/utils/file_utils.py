"""Common file utility functions."""
import re


def sanitize_filename(filename: str) -> str:
    """
    파일명에서 사용할 수 없는 문자를 제거하고 안전한 파일명으로 변환
    
    Args:
        filename: 원본 파일명
        
    Returns:
        str: 안전한 파일명
    """
    # 파일명에 사용할 수 없는 문자 제거
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    # 연속된 공백을 하나로
    filename = re.sub(r'\s+', ' ', filename)
    # 앞뒤 공백 제거
    filename = filename.strip()
    # 최대 길이 제한 (255자)
    if len(filename) > 255:
        filename = filename[:255]
    # 빈 문자열이면 기본값
    if not filename:
        filename = "untitled"
    return filename


__all__ = ["sanitize_filename"]
