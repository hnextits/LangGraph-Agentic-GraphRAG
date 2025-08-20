from config import SearchEngineConfig
from search_engine import GoogleSearchClient
from util import filter_search_results
import subprocess
import sys
import os
from pathlib import Path
from urllib.parse import urlparse
import time
import re
from kiwipiepy import Kiwi
config = SearchEngineConfig()

# 텍스트 요약 함수 직접 구현
def summarize_markdown_file(file_path, ratio=0.3):
    """마크다운 파일을 요약하는 함수 - 텍스트의 앞부분을 비율에 맞게 추출"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 내용이 없으면 바로 반환
        if not content.strip():
            return "요약할 텍스트가 없습니다."
            
        # 텍스트 길이에 따라 비율 조정
        summary_length = int(len(content) * ratio)
        if summary_length <= 0:
            return "요약할 텍스트가 없습니다."
            
        # 앞부분 추출 (더 복잡한 요약 알고리즘으로 대체 가능)
        return content[:summary_length]
    except Exception as e:
        print(f"[ERROR] 파일 요약 중 오류: {e}")
        return "요약할 텍스트가 없습니다."

# 조건부 임포트 - AnswerGenerator
try:
    from crawler_summary_llm import AnswerGenerator
    print("[INFO] crawler_summary_llm 모듈을 성공적으로 가져왔습니다.")
except ImportError:
    print("[WARNING] crawler_summary_llm 모듈을 가져올 수 없습니다. 대체 클래스를 사용합니다.")
    class AnswerGenerator:
        def __init__(self):
            pass
            
        def load_model(self):
            return True
            
        def generate_answer(self, query, documents):
            return "\n\n".join([f"질문: {query}", "답변: 모델을 로드할 수 없어 답변을 생성할 수 없습니다."])
            
        def cleanup_model(self):
            pass

def search(query, num,total_result_link):
    '''
    구글 검색 엔진을 불러와 구글에서 검색하는 역할을 하는 함수

    Args :
        query : 사용자가 검색한 내용
        num : 검색 결과 보여줄 개수
        total_result_link : 이미 가져온 링크들 (중복 제외용)
    '''
    try:
        ## 1. 구글 엔진 가져오기
        search_engine = GoogleSearchClient(
            api_key=config.API_KEY,
            cx_id=config.CX_ID
        )
        print(f"[INFO] 구글 검색 진행중... 쿼리: {query}")
        print(f"[INFO] 제외할 링크 수: {len(total_result_link) if total_result_link else 0}개")
        
     ## 2. 검색하기 (타임아웃 설정 포함)
        timeout_config = {
            'connection_timeout': 10,
            'read_timeout': 20
        }
        
        def search_google_batch(query, search_num, start_index=0):
            """검색 함수 내부 함수"""
            search_params = {
                'num': min(search_num, 10),  # 한 번에 최대 10개
                'start': start_index  # 검색 시작 인덱스
            }
            
            results = search_engine.search(query, extra_params=search_params, timeout_config=timeout_config)
        
            print(f"[DEBUG] API 응답 상태: {type(results)} (start: {start_index}, num: {search_params['num']})")
            
            if results is None:
                print("[WARNING] 검색 결과가 None입니다.")
                return []
                
            if not isinstance(results, dict) or 'items' not in results:
                print(f"[WARNING] 예상과 다른 API 응답 형식: {results}")
                return []
                
            print(f"[INFO] 검색 완료 - {len(results.get('items', []))}개 원본 결과 수신")
            
            # 검색 결과 필터링 (특정 사이트 제외)
            filtered_results = filter_search_results(results, max_results=search_params['num']) 
            print(f"[INFO] 1차 필터링 완료 - {len(filtered_results) if filtered_results else 0}개 결과")
            
            return filtered_results if filtered_results else []

        # 초기 검색 수행
        all_results = []
        start_index = 0
        batch_size = 10
        max_attempts = 5  # 최대 5번 시도 (최대 50개 검색)
        
        for attempt in range(max_attempts):
            print(f"[INFO] 검색 시도 {attempt + 1}/{max_attempts} (start: {start_index})")
            
            batch_results = search_google_batch(query, batch_size, start_index)
            
            if not batch_results:
                print("[INFO] 더 이상 검색 결과가 없습니다.")
                break
                
            # 이미 가져온 링크들 제외하면서 결과 추가
            unique_results = []
            for result in batch_results:
                link = result.get('link')
                # total_result_link와 이미 추가된 결과에서 중복 체크
                existing_links = (total_result_link or []) + [r.get('link') for r in all_results]
                if link not in existing_links:
                    unique_results.append(result)
                    
            all_results.extend(unique_results)
            print(f"[INFO] 이번 배치에서 {len(unique_results)}개 새 결과 추가, 총 {len(all_results)}개")
            
            # 원하는 개수에 도달하면 중단
            if len(all_results) >= num:
                all_results = all_results[:num]  # 정확히 num개만 자르기
                break
                
            # 다음 배치를 위해 시작 인덱스 업데이트
            start_index += batch_size
        
        final_results = all_results
        
        print(f"[INFO] 중복 제거 완료 - {len(final_results)}개 최종 결과 반환")
        return final_results
        
    except Exception as e:
        print(f"[ERROR] 검색 중 오류 발생: {str(e)}")
        import traceback
        print(f"[ERROR] 상세 오류: {traceback.format_exc()}")
        return []  # 오류 발생 시 빈 결과 반환          
        
def sanitize_filename(name: str, max_length: int = 100) -> str:
    """
    문자열을 받아 파일명으로 사용하기에 안전한 형태로 변환하는 함수.

    - 파일명에 사용할 수 없는 특수문자를 제거하거나 '_'로 변경합니다.
    - 공백을 '_'로 변경합니다.
    - 너무 긴 파일명을 적절한 길이로 자릅니다.
    """
    # 파일명에 사용할 수 없는 문자 및 기타 특수문자를 공백으로 변경
    name = re.sub(r'[\\/*?:"<>|.,…]', ' ', name)
    # 여러 공백을 하나의 언더스코어(_)로 변경
    name = re.sub(r'\s+', '_', name)
    return name

def save_snippet(result, output_dir):
    """
    (개선 버전)
    검색 결과를 받아 제목과 고유 ID를 조합한 안전한 파일명으로 저장합니다.
    """
    # 1. 제목과 링크에서 필요한 정보 추출
    title = result.get('title', 'no_title')
    link = result.get('link', '')

    # 2. 제목을 기반으로 안전한 파일명 생성
    sanitized_title = sanitize_filename(title)
    
    # 3. 링크에서 고유 ID 추출 (기존 방식 활용)
    # 예: https://blog.naver.com/kwonek1990/223253133310 -> 223253133310
    try:
        unique_id = urlparse(link).path.split('/')[-1]
        if not unique_id: # 경로가 '/'로 끝나는 경우 대비
             unique_id = urlparse(link).path.split('/')[-2]
    except IndexError:
        unique_id = "unknown"

    # 4. 안전한 제목과 고유 ID를 조합하여 최종 파일명 결정
    # 결과 예시: "영국_맨체스터_맨더비_암표_구하기_223253133310.md"
    final_filename = f"{sanitized_title}_{unique_id}.md"

    # 5. 파일 저장
    output_folder = os.path.join(output_dir) # 폴더명 오타 수정 (sinppet -> snippet)
    os.makedirs(output_folder, exist_ok=True)
    
    output_path = os.path.join(output_folder, final_filename)
    
    with open(output_path, "w", encoding="utf-8") as f:
        print(f"[INFO] {link} 스니펫 저장 중 -> {final_filename}")
        f.write(result.get('title', '') + "\n")
        f.write(result.get('snippet', '') + "\n")
        f.write(link + "\n")
    

## 3. 사이트별 크롤링
def crawling_web(result,output_dir):
    """
    웹서버에서 결과 확인하기 위해 만든 함수
    크롤링된 내용을 텍스트로 반환합니다.
    """
    url = result['link']
    parsed_url = urlparse(url)
    script_directory = Path(__file__).resolve().parent #파일 실행 위해 현재 위치 가져오기
    
    # 크롤링된 내용을 저장할 변수
    crawled_content = ""

    if parsed_url.netloc.endswith('namu.wiki'):
        start = time.time()
        print(f"[INFO] 나무위키 크롤링 진행중...")
        
        # 스크립트 디렉토리 정의
        script_directory = os.path.dirname(os.path.abspath(__file__))
        script_to_run = os.path.join(script_directory, "crawler_namuwiki.py")
        # print(script_to_run)
        
        # 스크립트 파일 존재 확인
        if not os.path.exists(script_to_run):
            print(f"[ERROR] 나무위키 크롤링 스크립트를 찾을 수 없습니다: {script_to_run}")
            return result.get('snippet', '나무위키 크롤링 스크립트를 찾을 수 없습니다.')
        
        command = [
            sys.executable,
            script_to_run,
            url,
            output_dir,
        ]
 
        try:
            subprocess_result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60  # 60초 타임아웃
            )
            
            # subprocess 결과 확인
            if subprocess_result.returncode != 0:
                print(f"[ERROR] 나무위키 크롤링 스크립트 실행 실패")
                print(f"[ERROR] stdout: {subprocess_result.stdout}")
                print(f"[ERROR] stderr: {subprocess_result.stderr}")
                return result.get('snippet', '나무위키 크롤링 실패')
            else:
                print(f"[DEBUG] 나무위키 스크립트 성공: {subprocess_result.stdout}")
                
        except subprocess.TimeoutExpired:
            print(f"[ERROR] 나무위키 크롤링 타임아웃 (60초)")
            return result.get('snippet', '나무위키 크롤링 타임아웃')
        except Exception as e:
            print(f"[ERROR] 나무위키 크롤링 실행 중 오류: {e}")
            return result.get('snippet', f'나무위키 크롤링 오류: {str(e)}')

        print(f"[INFO] 나무위키 크롤링 완료. 소요 시간: {time.time() - start:.2f}")

        # 생성된 파일에서 내용 읽기
        try:
            # output_dir에서 직접 .md 파일을 찾습니다.
            md_files = [f for f in os.listdir(output_dir) if f.endswith('.md')]
            if md_files:
                # Namuwiki에서 생성된 파일 이름은 URL 기반이므로, 가장 최신 파일을 선택합니다.
                # 또는, 생성된 파일 이름을 crawler_namuwiki.py에서 반환받아 사용해야 합니다.
                # 여기서는 가장 최신 .md 파일을 읽는 것으로 가정합니다.
                latest_file = max([os.path.join(output_dir, f) for f in md_files], key=os.path.getctime)
                print(f"[INFO] 나무위키 크롤링 완료, 파일 경로: {latest_file}")
                return latest_file  # 파일 경로를 직접 반환
            else:
                print(f"[WARNING] 나무위키 .md 파일을 찾을 수 없습니다: {output_dir}")
                
        except Exception as e:
            print(f"[WARNING] 나무위키 크롤링 파일 읽기 실패: {e}")
            import traceback
            print(f"[DEBUG] 상세 오류: {traceback.format_exc()}")
        
        # 파일 읽기 실패 시 None 반환 (검증 로직에서 처리됨)
        return None

    elif parsed_url.netloc.endswith('wikipedia.org'):
        start = time.time()
        print(f"[INFO] 위키피디아 크롤링 진행중...")
        
        wikipedia_dir = os.path.join(output_dir)
        script_to_run = os.path.join(script_directory,"crawler_wikipidia.py")
        command = [
            sys.executable,
            script_to_run,
            url,
            wikipedia_dir,
        ]

        try:
            subprocess_result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60  # 60초 타임아웃 설정
            )
            
            print(f"[INFO] 위키피디아 크롤링 완료. 소요 시간: {time.time() - start:.2f}")
            # subprocess 결과 확인
            if subprocess_result.returncode != 0:
                print(f"[ERROR] 위키피디아 크롤링 스크립트 실행 실패")
                print(f"[ERROR] stdout: {subprocess_result.stdout}")
                print(f"[ERROR] stderr: {subprocess_result.stderr}")
                return result.get('snippet', '위키피디아 크롤링 실패')
            else:
                print(f"[DEBUG] 위키피디아 스크립트 성공: {subprocess_result.stdout}")
                
                # 크롤러가 반환한 파일 경로 확인 (stdout에서 추출)
                output_path = None
                for line in subprocess_result.stdout.splitlines():
                    if "✅ 성공! 파일이 저장되었습니다:" in line:
                        output_path = line.split("✅ 성공! 파일이 저장되었습니다:")[1].strip()
                        break
                
                # 파일 경로를 찾았으면 해당 파일 경로 반환
                if output_path and os.path.exists(output_path):
                    print(f"[INFO] 위키피디아 크롤링 완료, 파일 경로: {output_path}")
                    return output_path
            
            # 기존 방식으로 파일 찾기 (백업)
            try:
                if os.path.exists(wikipedia_dir):
                    files = [f for f in os.listdir(wikipedia_dir) if f.endswith('.md')]
                    if files:
                        latest_file = max(files, key=lambda x: os.path.getctime(os.path.join(wikipedia_dir, x)))
                        file_path = os.path.join(wikipedia_dir, latest_file)
                        print(f"[INFO] 위키피디아 크롤링 완료 (백업), 파일 경로: {file_path}")
                        return file_path
            except Exception as e:
                print(f"[WARNING] 위키피디아 크롤링 파일 읽기 실패 (디렉토리 검색): {e}")
        
        except subprocess.TimeoutExpired:
            print(f"[ERROR] 위키피디아 크롤링 타임아웃 (60초)")
            return result.get('snippet', '위키피디아 크롤링 시간 초과')
        except Exception as e:
            print(f"[ERROR] 위키피디아 크롤링 중 예외 발생: {e}")
            return result.get('snippet', f'위키피디아 크롤링 오류: {str(e)}')
        
        return None  # 위키피디아 크롤링 실패
    elif parsed_url.netloc.endswith('velog'):
        start = time.time()
        print(f"[INFO] 벨로그 크롤링 진행중...")
        
        script_to_run = os.path.join(script_directory,"crawler_velog.py")
        command = [
            sys.executable,
            script_to_run,
            url,
            output_dir,
        ]

        subprocess_result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        
        print(f"[INFO] 벨로그 크롤링 완료. 소요 시간: {time.time() - start:.2f}")
        
        # 생성된 파일 경로 반환
        try:
            velog_dir = os.path.join(output_dir, "3.velog")
            if os.path.exists(velog_dir):
                files = [f for f in os.listdir(velog_dir) if f.endswith('.md')]
                if files:
                    latest_file = max(files, key=lambda x: os.path.getctime(os.path.join(velog_dir, x)))
                    file_path = os.path.join(velog_dir, latest_file)
                    print(f"[INFO] 벨로그 크롤링 완료, 파일 경로: {file_path}")
                    return file_path
        except Exception as e:
            print(f"[WARNING] 벨로그 크롤링 파일 읽기 실패: {e}")
        
        return None  # 벨로그 크롤링 실패
    else:
        start = time.time()
        save_snippet(result, output_dir=output_dir)
        print(f"[INFO] 일반 크롤링 완료. 소요 시간: {time.time() - start:.2f}")
        
        # 일반 사이트 snippet 파일 경로 반환
        try:
            snippet_dir = os.path.join(output_dir, "4.snippet")
            if os.path.exists(snippet_dir):
                files = [f for f in os.listdir(snippet_dir) if f.endswith('.md')]
                if files:
                    latest_file = max(files, key=lambda x: os.path.getctime(os.path.join(snippet_dir, x)))
                    file_path = os.path.join(snippet_dir, latest_file)
                    print(f"[INFO] 일반 사이트 크롤링 완료, 파일 경로: {file_path}")
                    return file_path
        except Exception as e:
            print(f"[WARNING] 일반 사이트 크롤링 파일 읽기 실패: {e}")
        
        # 파일 생성 실패 시 None 반환
        return None

def summary_with_llm(query, documents):
    '''
    문서 목록과 원본 쿼리를 받아 각 문서를 크롤링한 후 AI 모델을 통해 답변을 생성합니다.
    처리 과정:
    1. summarize_markdown_file 함수로 1차 요약
    2. AnswerGenerator로 최종 답변 생성
    
    Args:
        query : 사용자 질문
        document : 구글 검색 결과
    '''
    if not documents:
        return "검색 결과가 없습니다."
    
    # 1. 각 문서를 1차 요약
    summarized_documents = []
    for doc in documents:
        try:
            # 파일 경로가 있으면 해당 파일을 요약
            if 'file_path' in doc and os.path.exists(doc['file_path']):
                summary = summarize_markdown_file(doc['file_path'], ratio=0.3)
                if summary and summary != "요약할 텍스트가 없습니다.":
                    summarized_documents.append(summary)
            # 파일 경로가 없으면 URL에서 직접 크롤링
            elif 'link' in doc:
                content = crawl_and_get_content(doc['link'])
                if content:
                    # 임시 파일에 저장 후 요약
                    import uuid
                    temp_file = f"temp_{uuid.uuid4()}.md"
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    summary = summarize_markdown_file(temp_file, ratio=0.3)
                    os.remove(temp_file)  # 임시 파일 삭제
                    if summary and summary != "요약할 텍스트가 없습니다.":
                        summarized_documents.append(summary)
        except Exception as e:
            print(f"[ERROR] 문서 요약 중 오류: {e}")
            continue
    
    print(f"[INFO] 1차 요약 완료: {len(documents)}개 문서 → {len(summarized_documents)}개 요약문")
    
    # 2. AnswerGenerator 인스턴스 생성 및 모델 로드
    print("[INFO] AI 모델 로딩 중...")
    answer_generator = AnswerGenerator()
    if not answer_generator.load_model():
        return "모델 로딩에 실패하여 답변을 생성할 수 없습니다."

    # 3. 1차 요약된 내용을 컨텍스트로 조합
    context = "\n\n".join(summarized_documents)
    print(f"[INFO] 1차 요약 후 컨텍스트 길이: {len(context)} 문자")
    
    # 4. 최종 답변 생성
    try:
        print("[INFO] AI 최종 답변 생성 중...")
        final_answer = answer_generator.generate_answer(query, summarized_documents)
        print("[INFO] 최종 답변 생성 완료")
        return final_answer
    except Exception as e:
        print(f"[ERROR] 답변 생성 중 오류: {e}")
        return f"답변 생성에 실패했습니다: {str(e)}"
    finally:
        # 5. 모델 리소스 정리 (메모리 누수 방지)
        answer_generator.cleanup_model()
    
def crawl_and_get_content(url: str) -> str:
    """
    주어진 URL을 크롤링하여 텍스트 콘텐츠를 반환합니다.
    crawling_web 함수의 일부 로직을 재사용합니다.
    """
    try:
        # URL에서 바로 크롤링을 시도하기 위해 필요한 스크립트 경로 등을 설정합니다.
        python_executable = sys.executable
        script_path = os.path.join(os.path.dirname(__file__), 'wikipedia_crawler.py')
        
        # wikipedia.org 링크 처리
        if 'wikipedia.org' in url:
            command = [python_executable, script_path, url, ""]
            process = subprocess.run(command, capture_output=True, text=True, check=True)
            return process.stdout
        else:
            # 다른 웹사이트는 requests와 BeautifulSoup를 사용
            from bs4 import BeautifulSoup
            import requests
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            # 기본적인 태그 제거
            for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                tag.decompose()
            return soup.get_text(separator='\n', strip=True)

    except Exception as e:
        print(f"[ERROR] URL '{url}' 크롤링 중 오류 발생: {e}")
        return ""


def revove_table_stylesheet(md_file):
    from bs4 import BeautifulSoup
    with open(md_file, 'r', encoding='utf-8') as f:
        raw_md = f.read()

    soup = BeautifulSoup(raw_md, 'html.parser')

    for tag in soup.find_all(['style', 'script', 'link', 'img', 'noscript']):
        tag.decompose() #내용물 제거
    allowed_attributes = {'colspan', 'rowspan'}
    for tag in soup.find_all(True): # find_all(True)는 모든 태그를 선택합니다.
            # 현재 태그의 속성들을 복사하여 순회 (원본을 직접 수정하면 문제가 생길 수 있음)
            attributes = dict(tag.attrs)
            for attr, value in attributes.items():
                # 허용된 속성 목록에 없으면 모두 제거
                if attr not in allowed_attributes:
                    del tag[attr]

    # 4. 정리된 HTML 객체를 예쁘게 정렬된 문자열로 반환
    return soup.prettify()
def main():
    total_result_link = []
    while True:
        output_dir = "/home/nextits2/.conda/envs/workbox/serch_gui/chatbot/backend/search_test/Crawling_data"
        query = input("검색어를 입력하세요(종료를 원할 경우 CTRL+C 혹은 q를 입력하세요) : ")
        if query=="q":
            break
        results = search(query, 10,total_result_link)
        for result in results:
            total_result_link.append(result['link'])
            print(result)
            # print(result['link'])
            crawling_web(result = result,output_dir=output_dir)
            print()
if __name__ == "__main__":
    main()