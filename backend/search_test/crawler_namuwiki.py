import requests
import re
import os
from urllib.parse import urlparse, unquote
from markdownify import markdownify as md
from bs4 import BeautifulSoup
from util import request_url, find_table_and_remove_style
import hashlib

# 정규식 패턴: HTML에서 제거 후 남은 텍스트 잔여물 처리용
NAMU_CLEAN_PATTERNS = re.compile(
    # --- 상단 및 특정 구문 제거 ---
    r"^\d+\s*편집\s*편집|"  # "36 편집 편집" 같은 최상단 숫자 및 버튼
    r"IP 우회 수단.*?바랍니다\.|" # IP 우회 경고 문구 전체
    r"닫기|"
    r"광고|"
    r"파워링크|"
    r"광고 등록|"
    r"토론역사|"
    r"wZYMnyDJ|"
    r".*?에서 넘어옴|" # 문서 이동 추적 메시지
    r"주의\. 사건·사고 관련 내용을 설명합니다\..*?규정을 유의하시기 바랍니다\.|" # 사건/사고 경고
    r"\[편집\]|" # 남아있을 수 있는 편집 버튼
    # --- 라이선스 및 기타 정보 ---
    r"최근 수정 시각:\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}|"
    r"이 저작물은.*?(CC BY-NC-SA 2.0 KR|크리에이티브 커먼즈 라이선스).*|저작권은 나무위키에 있습니다\.",
    flags=re.DOTALL | re.MULTILINE # 여러 줄에 걸친 패턴 및 라인 시작(^) 처리
)

def crawl_namuwiki_page(url: str, output_dir: str = "./"):
    """
    (최종 클리닝 버전)
    모든 이미지 및 UI 요소를 제거하고, 테이블은 완벽히 보존하는 나무위키 크롤러.
    """
    try:
        # 1. URL 크롤링 및 lxml 파서 사용
        response, title = request_url(url)
        if response is None:
            print(f"[ERROR] URL에 접근할 수 없습니다: {url}")
            return None
        soup = BeautifulSoup(response.text, 'lxml')

        # 2. 본문 콘텐츠 추출
        article = soup.select_one("div.T4Q1I9Wt")
        if not article:
            print("[WARNING] 본문 콘텐츠('div.T4Q1I9Wt')를 찾을 수 없습니다.")
            return None

        # 3. HTML 단계에서 모든 불필요한 요소 제거 (가장 안정적인 방식)
        selectors_to_remove = [
            '.wiki-macro-toc',          # 목차
            '.wiki-edit-section',       # 편집 버튼
            'div.wiki-macro-footnote',  # 각주
            'div.wiki-category',        # 분류
            'dl.wiki-folding',          # [펼치기·접기]가 포함된 접힘 메뉴
            'img',                      # 모든 이미지 태그 (data:image 포함)
            'iframe',                   # 유튜브 등 외부 콘텐츠 프레임
            # 'table',                    # 모든 테이블 제거
            'noscript',                 # noscript 태그 제거
            'style',                    # 스타일 태그 제거
            'script',                   # 스크립트 태그 제거
            'svg',                      # SVG 태그 제거
            'lite-youtube'              # 유튜브 임베드 제거
        ]
        for selector in selectors_to_remove:
            for element in article.select(selector):
                element.decompose()

        # 3-1. 모든 하이퍼링크 제거 (텍스트는 유지)
        for a_tag in article.find_all('a'):
            a_tag.unwrap()
            
        # 3-2. 모든 HTML 태그의 속성 제거 (텍스트만 유지)
        for tag in article.find_all(True):
            # 태그의 모든 속성을 복사하여 순회합니다. (원본을 수정하면서 순회하면 에러 발생)
            # list(tag.attrs)를 통해 복사본을 만듭니다.
            for attr in list(tag.attrs):
                # 모든 속성 제거
                del tag[attr]
                
        # 3-3. 모든 HTML 태그를 텍스트로 변환 (태그 구조 제거)
        for tag in article.find_all(['div', 'span', 'strong', 'ruby', 'rt', 'rp', 'dl', 'dt', 'dd', 'br']):
            tag.unwrap()


        # 5. 텍스트로 변환 및 최종 정규식 정리
        article_text = article.get_text(separator='\n', strip=True)
        
        # 최적화된 단일 정규식으로 텍스트 잔여물 정리
        clean_text = NAMU_CLEAN_PATTERNS.sub('\n\n', article_text).strip()
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip() # 여러 줄바꿈을 2개로
        
        # 추가 정리: 빈 줄 제거 및 특수 문자 정리
        clean_text = re.sub(r'\[\d+\]', '', clean_text)  # 각주 번호 제거
        clean_text = re.sub(r'\s*\n\s*', '\n', clean_text)  # 줄바꿈 주변 공백 제거
        
        # 최종 텍스트 설정
        final_content = f"# {title}\n\n{clean_text}"

        # 7. 페이지 제목 추가
        final_content = f"# {title}\n\n{final_content}"

        # 8. 파일 저장
        # output_folder = os.path.join(output_dir, '1.namuwiki')
        os.makedirs(output_dir, exist_ok=True)
        safe_title = re.sub(r'[\/*?:"<>|]', "_", title)
        
        # 한글 파일명 길이 제한 및 해시 추가로 고유성 확보
        if len(safe_title) > 10:  # 한글은 글자당 3바이트이므로 길이 제한 확대
            # 한글 인코딩 고려하여 앞부분 추출
            short_title = safe_title[:8]  # 한글 2-3글자 정도
            # 원본 제목의 해시값 추가하여 구분성 확보
            hash_suffix = hashlib.md5(safe_title.encode()).hexdigest()[:4]
            safe_title = f"{short_title}_{hash_suffix}"
            
        output_path = os.path.join(output_dir, f"{safe_title}_나무.md")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        
        # OCR 결과 디렉토리에도 동일한 파일 저장
        ocr_results_dir = os.path.join(os.path.dirname(output_dir), 'Results', '3.OCR_results')
        os.makedirs(ocr_results_dir, exist_ok=True)
        ocr_file_path = os.path.join(ocr_results_dir, f"{safe_title}_나무.md")
        
        with open(ocr_file_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        
        print(f"\n✅ 성공! '{output_path}' 파일이 저장되었습니다.")
        return output_path

    except Exception as e:
        import traceback
        print(f"\n[에러] 처리 중 알 수 없는 오류가 발생했습니다: {e}")
        print(traceback.format_exc())
        return None

# --- main 함수는 이전과 동일하게 사용 ---
# (테스트를 위해 URL만 현재 문서로 변경)
def main():
    import argparse
    import time

    parser = argparse.ArgumentParser(description='나무위키 페이지를 크롤링하여 마크다운으로 저장합니다.')
    parser.add_argument('url', nargs='?', default="", help='(옵션) 크롤링할 나무위키 URL')
    parser.add_argument('output_dir', nargs='?', default="", help='(옵션) 저장할 디렉토리 경로')
    
    args = parser.parse_args()
    url = args.url
    output_dir = args.output_dir

    if not url: 
        url = "https://namu.wiki/w/%ED%95%9C%ED%99%94%20%EC%9D%B4%EA%B8%80%EC%8A%A4"
    if not output_dir:
        output_dir = "/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/search_test"
    
    if "namu.wiki/w/" not in url:
        print("[ERROR] 유효한 나무위키 문서 URL이 아닙니다.")
        return
    start = time.time()
    crawl_namuwiki_page(url, output_dir=output_dir)
    print(f"소요시간 : {time.time()-start:.2f}")
if __name__ == "__main__":
    main()
