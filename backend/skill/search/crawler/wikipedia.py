import requests
import re
import os
from urllib.parse import urlparse, unquote
from markdownify import markdownify as md
from bs4 import BeautifulSoup
from util import request_url, find_table_and_remove_style
import hashlib

# 정규식 패턴: 링크 제거는 BeautifulSoup이 처리하므로 관련 규칙 삭제
CLEAN_PATTERNS = re.compile(
    r"^(\s*위키백과, 우리 모두의 백과사전\.?|"
    r"\s*\(.*?위키낱말사전, 말과 글의 누리 사전\.\)|"
    r"\s*이 문서는 명칭은 같지만 대상이 다를 때에 쓰이는 동음이의어 문서입니다.*?살펴보실 수 있습니다\.)|"
    r"\[\d+\]|"                  # 각주 링크 [1], [2] 등
    r"\n{3,}"                    # 3번 이상의 연속된 개행을 2번으로
)

def crawl_wikipedia_page(url: str, output_dir: str = "./"):
    """
    (최종 안정화 버전)
    모든 하이퍼링크를 제거하고, 테이블도 텍스트로 변환하여 깔끔한 마크다운 텍스트만 출력합니다.
    """
    try:
        # 1. URL 크롤링 및 lxml 파싱
        response, _ = request_url(url)
        if response is None:
            print(f"[ERROR] URL에 접근할 수 없습니다: {url}")
            return None
        soup = BeautifulSoup(response.text, 'lxml')

        # 2. 본문 콘텐츠 추출
        article = soup.select_one("#mw-content-text .mw-parser-output")
        if not article:
            print("[WARNING] 본문 콘텐츠('#mw-content-text .mw-parser-output')를 찾을 수 없습니다.")
            return None

        # 3. HTML 단계에서 모든 불필요한 요소 제거
        # 3-1. 사이드바, 편집 버튼 등 제거
        for element in article.select('.sidebar, .mw-editsection, .thumbcaption .magnify, .noprint, .catlinks, #toc, span[typeof]'):
            element.decompose()

        # 3-2. (핵심) 모든 하이퍼링크 제거 (텍스트는 유지)
        for a_tag in article.find_all('a'):
            a_tag.unwrap()
            
        # 3-3. 테이블 처리 - 테이블을 텍스트로 변환하기 위한 전처리
        for table in article.find_all('table'):
            # 테이블 내 모든 태그의 속성 제거
            for tag in table.find_all(True):
                for attr in list(tag.attrs):
                    del tag[attr]
            
            # 테이블 내 불필요한 태그 unwrap
            for tag in table.find_all(['span', 'div', 'strong', 'em', 'i', 'b']):
                tag.unwrap()

        # 4. 모든 HTML을 마크다운으로 변환 (테이블 포함)
        article_html = str(article)
        article_md = md(article_html, heading_style="ATX")
        clean_md = CLEAN_PATTERNS.sub('\n\n', article_md).strip()
        
        # 5. 추가 정리: 각주 번호 제거 및 여러 줄바꿈 정리
        clean_md = re.sub(r'\[\d+\]', '', clean_md)  # 각주 번호 제거
        clean_md = re.sub(r'\n{3,}', '\n\n', clean_md)  # 여러 줄바꿈을 2개로
        
        # 6. 최종 텍스트 설정
        final_content = clean_md

        # 7. 페이지 제목 추가
        page_title = soup.select_one("#firstHeading")
        if page_title:
            final_content = f"# {page_title.get_text(strip=True)}\n\n{final_content}"

        # 8. 파일 저장
        path = urlparse(url).path
        title = unquote(path.split('/')[-1])
        
        # 한글 파일명 처리 개선
        safe_title = re.sub(r'[\/*?:"<>|]', "_", title)
        
        # 한글 파일명 길이 제한 및 해시 추가로 고유성 확보
        if len(safe_title) > 10:  # 한글은 글자당 3바이트이므로 길이 제한 확대
            # 한글 인코딩 고려하여 앞부분 추출
            short_title = safe_title[:8]  # 한글 2-3글자 정도
            # 원본 제목의 해시값 추가하여 구분성 확보
            hash_suffix = hashlib.md5(safe_title.encode()).hexdigest()[:4]
            safe_title = f"{short_title}_{hash_suffix}"
        
        os.makedirs(output_dir, exist_ok=True)
        
        output_path = os.path.join(output_dir, f"{safe_title}_위키.md")
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_content.strip())
        
        # OCR 결과 디렉토리에도 동일한 파일 저장
        ocr_results_dir = os.path.join(os.path.dirname(output_dir), 'Results', '4.OCR_results')
        os.makedirs(ocr_results_dir, exist_ok=True)
        ocr_file_path = os.path.join(ocr_results_dir, f"{safe_title}_위키.md")
        
        with open(ocr_file_path, "w", encoding="utf-8") as f:
            f.write(final_content.strip())
        
        print(f"\n✅ 성공! '{output_path}' 파일이 저장되었습니다.")
        return output_path
        
    except Exception as e:
        import traceback
        print(f"\n[에러] 처리 중 알 수 없는 오류가 발생했습니다: {e}")
        print(traceback.format_exc())
        return None

# --- main 함수는 이전과 동일하게 사용 ---
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='위키피디아 페이지를 크롤링하여 마크다운으로 저장합니다.')
    parser.add_argument('url', nargs='?', default="", help='크롤링할 위키피디아 URL')
    parser.add_argument('output_dir', nargs='?', default="", help='출력 디렉토리 경로')

    args = parser.parse_args()
    url = args.url
    output_dir = args.output_dir

    if not url:
        url = "https://ko.wikipedia.org/wiki/%ED%95%9C%ED%99%94_%EC%9D%B4%EA%B8%80%EC%8A%A4"
        if not output_dir:
            output_dir = "./Crawling_data"
    
    if 'wikipedia' not in url:
        print("[ERROR] 유효한 위키피디아 문서 URL이 아닙니다.")
        return
    
    crawl_wikipedia_page(url, output_dir=output_dir)

if __name__ == "__main__":
    main()
