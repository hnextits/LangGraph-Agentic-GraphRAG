### 공통으로 사용되는 모듈들 모아둔 파일

import requests
from urllib.parse import urlparse, unquote, quote
import os

def remove_think(response):
    '''
    Qwen의 답변에서 think태그를 달고 생각하는 내용 출력해주는 부분을 삭제하기 위한 함수

    Args:
        response : Qwen의 답변
    
    Returns:
        think태그 부분이 삭제된 Qwen의 답변
    '''

    if "<think>" in response and "</think>" in response:
        try:
            answer_parts = response.split("<think>", 1)
            think_and_rest = answer_parts[1].split("</think>", 1)
            answer = answer_parts[0].strip() + " " + think_and_rest[1].strip()
            print(f"[INFO] <think> 태그 제거 후 원본 답변 길이: {len(answer)}")
        except IndexError:
            print("[WARNING] 원본 답변의 <think> 태그 처리 중 오류 발생")
    elif "<think>" in answer:
        try:
            parts = answer.split("<think>", 1)
            if "\n\n" in parts[1]:
                answer = parts[0].strip() + " " + parts[1].split("\n\n", 1)[1].strip()
                print(f"[INFO] <think> 태그 제거 후 원본 답변 길이: {len(answer)}")
        except IndexError:
            print("[WARNING] 원본 답변의 <think> 태그 처리 중 오류 발생")
    return answer

def filter_search_results(results, max_results=10):
    """
    검색 결과에서 나무위키와 위키피디아만 포함하고 다른 사이트는 제외하여 상위 N개만 반환
    
    Args:
        results: 구글 검색 결과
        max_results: 반환할 최대 결과 수 (기본값: 10)
    
    Returns:
        필터링된 검색 결과 리스트
    """
    # 포함할 사이트 목록 (나무위키와 위키피디아만 포함)
    included_sites = [
        'namu.wiki',
        'wikipedia.org'
    ]
    
    filtered_results = []
    
    if 'items' in results:
        for item in results['items']:
            link = item.get('link', '')
            
            # 포함할 사이트인지 확인 (대소문자 구분 없이)
            is_included = any(included_site in link.lower() for included_site in included_sites)
            
            if is_included:
                data = {
                    'title': item.get('title', '제목 없음'), 
                    'link': link, 
                    'snippet': item.get('snippet', '요약 없음')
                }
                filtered_results.append(data)
                
                # 최대 결과 수에 도달하면 중단
                if len(filtered_results) >= max_results:
                    break
    
    return filtered_results

def request_url(url):
    
    try:
        path = urlparse(url).path
        title = unquote(path[3:]) if path.startswith('/w/') else os.path.basename(path)
        print(f"추출된 문서 제목: {title}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }

        print("페이지 콘텐츠 요청 중...")
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response, title

    except requests.exceptions.HTTPError as e:
        print(f"\n[에러] HTTP 오류가 발생했습니다: {e}")
        return None, None


def convert_all_markdown_tables_to_html(markdown_text: str) -> str:
    """
    마크다운 텍스트에서 테이블만 찾아서 HTML 형식으로 변환합니다.
    """
    import re

    # 마크다운 테이블 패턴을 찾아내는 정규식
    md_table_pattern = re.compile(r'(?:^\|.*\|$\n?)+', re.MULTILINE)
    
    def replace_with_html(match):
        table_lines = match.group(0).strip().split('\n')
        
        if len(table_lines) < 2:
            return '\n'.join(table_lines) # 테이블 형식이 아니면 그대로 반환

        html_parts = ['<table>']
        
        # 헤더 처리
        header_cells = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]
        html_parts.append('<thead><tr>')
        for cell in header_cells:
            html_parts.append(f'<th>{cell}</th>')
        html_parts.append('</tr></thead>')
        
        # 본문 처리 (구분선 --- 제외)
        html_parts.append('<tbody>')
        for line in table_lines[2:]:
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            html_parts.append('<tr>')
            for cell in cells:
                html_parts.append(f'<td>{cell}</td>')
            html_parts.append('</tr>')
        html_parts.append('</tbody>')
        
        html_parts.append('</table>')
        return '\n'.join(html_parts)

    return md_table_pattern.sub(replace_with_html, markdown_text)

def find_table_and_remove_style(article,soup):
    tables = []
    for i, table in enumerate(article.find_all('table')):
        placeholder = f"---TABLE-PLACEHOLDER-{i}---"
        # 테이블에서 모든 style 속성 제거
        for tag in table.find_all(True):
            if tag.has_attr('style'):
                del tag['style']
            if tag.has_attr('class'):
                del tag['class']
            if tag.has_attr('bgcolor'):
                del tag['bgcolor']
            if tag.has_attr('width'):
                del tag['width']
            if tag.has_attr('height'):
                del tag['height']
            if tag.has_attr('align'):
                del tag['align']
            if tag.has_attr('valign'):
                del tag['valign']
            if tag.has_attr('border'):
                del tag['border']
            if tag.has_attr('cellspacing'):
                del tag['cellspacing']
            if tag.has_attr('cellpadding'):
                del tag['cellpadding']
        
        # 테이블 자체의 스타일 속성도 제거
        if table.has_attr('style'):
            del table['style']
        if table.has_attr('data-dark-style'):
            del table['data-dark-style']
        if table.has_attr('data-v-d7de5c75'):
            del table['data-v-d7de5c75']
        if table.has_attr('class'):
            del table['class']
        if table.has_attr('bgcolor'):
            del table['bgcolor']
        if table.has_attr('width'):
            del table['width']
        if table.has_attr('height'):
            del table['height']
        if table.has_attr('align'):
            del table['align']
        if table.has_attr('border'):
            del table['border']
        if table.has_attr('cellspacing'):
            del table['cellspacing']
        if table.has_attr('cellpadding'):
            del table['cellpadding']
        if table.has_attr('img'):
            del table['img']
        if table.has_attr('src'):
            del table['src']
        if table.has_attr('srcset'):
            del table['srcset']
        if table.has_attr('span'):
            del table['span']

        tables.append(str(table))
        table.replace_with(soup.new_string(placeholder))

    return tables, article