"""
MD Summarizer 사용 예시
기존 nextitslm 시스템과 동일한 방식으로 사용 가능
"""

import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src import SGLangClient, MDParser, MDSummaryIndex


def example_1_basic_summarization():
    """예시 1: 기본 요약 (기존 AnswerGenerator와 동일)"""
    print("=" * 60)
    print("예시 1: 기본 요약")
    print("=" * 60)
    
    # SGLang 클라이언트 생성 (기존 AnswerGenerator 대체)
    client = SGLangClient(endpoints=["http://localhost:30000", "http://localhost:30001"])
    
    # 샘플 텍스트
    sample_text = """
    # 인공지능의 발전
    
    인공지능(AI)은 최근 몇 년간 급속도로 발전하고 있습니다. 
    특히 대규모 언어 모델(LLM)의 등장으로 자연어 처리 분야에서 
    혁신적인 성과를 보이고 있습니다.
    
    ## 주요 발전 사항
    
    1. GPT 시리즈의 등장
    2. 멀티모달 AI의 발전
    3. 오픈소스 모델의 성장
    """
    
    # 요약 생성 (기존 방식과 동일)
    summary = client.generate_answer(sample_text)
    
    print("\n[원본 텍스트]")
    print(sample_text)
    print("\n[요약 결과]")
    print(summary)
    print()


def example_2_file_summarization():
    """예시 2: 파일 요약"""
    print("=" * 60)
    print("예시 2: 파일 요약")
    print("=" * 60)
    
    # MD 파서 생성
    parser = MDParser()
    client = SGLangClient(endpoints=["http://localhost:30000"])
    
    # 파일 읽기
    file_path = "path/to/your/document.md"  # 실제 파일 경로로 변경
    
    # 파일이 존재하는 경우에만 실행
    if Path(file_path).exists():
        content = parser.read_file(file_path)
        
        # 요약 생성
        summary = client.generate_answer(content)
        
        print(f"\n[파일]: {file_path}")
        print(f"[내용 길이]: {len(content)} 문자")
        print("\n[요약 결과]")
        print(summary)
    else:
        print(f"파일을 찾을 수 없습니다: {file_path}")
    print()


def example_3_summary_index():
    """예시 3: 요약 인덱스 시스템 (고급 RAG)"""
    print("=" * 60)
    print("예시 3: 요약 인덱스 시스템")
    print("=" * 60)
    
    # 요약 인덱스 시스템 초기화
    summarizer = MDSummaryIndex(
        sglang_endpoints=["http://localhost:30000", "http://localhost:30001"]
    )
    
    # 문서 추가 (예시)
    documents = [
        {
            "id": "doc1.md",
            "content": "# AI 발전\n\n인공지능은 빠르게 발전하고 있습니다..."
        },
        {
            "id": "doc2.md",
            "content": "# 머신러닝 기초\n\n머신러닝은 데이터로부터 학습합니다..."
        },
        {
            "id": "doc3.md",
            "content": "# 딥러닝 응용\n\n딥러닝은 다양한 분야에 응용됩니다..."
        }
    ]
    
    # 문서 추가
    for doc in documents:
        summarizer.add_document(doc["id"], content=doc["content"])
    
    print(f"\n총 {len(documents)}개 문서 추가됨")
    
    # 요약 생성
    print("\n요약 생성 중...")
    summarizer.generate_summaries(max_tokens=1000)
    
    # 검색
    query = "인공지능"
    print(f"\n검색 쿼리: '{query}'")
    results = summarizer.search(query, top_k=2)
    
    print(f"\n검색 결과 ({len(results)}개):")
    for i, result in enumerate(results, 1):
        print(f"\n{i}. {result['doc_id']} (점수: {result['score']:.4f})")
        print(f"   요약: {result['summary'][:100]}...")
    
    # 통계 정보
    stats = summarizer.get_statistics()
    print(f"\n[통계 정보]")
    print(f"- 총 문서 수: {stats['total_documents']}")
    print(f"- 총 요약 수: {stats['total_summaries']}")
    print(f"- 평균 내용 길이: {stats['avg_content_length']} 문자")
    print(f"- 평균 요약 길이: {stats['avg_summary_length']} 문자")
    print()


def example_4_batch_processing():
    """예시 4: 배치 처리"""
    print("=" * 60)
    print("예시 4: 배치 처리")
    print("=" * 60)
    
    summarizer = MDSummaryIndex(sglang_endpoints=["http://localhost:30000"])
    
    # 여러 파일을 배치로 추가
    file_paths = [
        "path/to/doc1.md",
        "path/to/doc2.md",
        "path/to/doc3.md",
    ]
    
    # 실제 존재하는 파일만 필터링
    existing_files = [f for f in file_paths if Path(f).exists()]
    
    if existing_files:
        print(f"\n{len(existing_files)}개 파일 배치 처리 중...")
        summarizer.add_documents_batch(existing_files)
        summarizer.generate_summaries()
        
        print("\n배치 처리 완료!")
        print(summarizer.get_statistics())
    else:
        print("처리할 파일이 없습니다.")
    print()


def example_5_save_and_load():
    """예시 5: 인덱스 저장 및 로드"""
    print("=" * 60)
    print("예시 5: 인덱스 저장 및 로드")
    print("=" * 60)
    
    # 인덱스 생성 및 저장
    summarizer = MDSummaryIndex(sglang_endpoints=["http://localhost:30000"])
    
    # 문서 추가
    summarizer.add_document("test.md", content="# 테스트 문서\n\n이것은 테스트입니다.")
    summarizer.generate_summaries()
    
    # 인덱스 저장
    save_path = "results/index.json"
    summarizer.save_index(save_path)
    print(f"\n인덱스 저장 완료: {save_path}")
    
    # 새로운 인스턴스에서 로드
    new_summarizer = MDSummaryIndex(sglang_endpoints=["http://localhost:30000"])
    new_summarizer.load_index(save_path)
    print(f"인덱스 로드 완료: {len(new_summarizer.documents)}개 문서")
    
    # 로드된 데이터 확인
    stats = new_summarizer.get_statistics()
    print(f"\n로드된 인덱스 통계:")
    print(f"- 문서 수: {stats['total_documents']}")
    print(f"- 요약 수: {stats['total_summaries']}")
    print()


def main():
    """메인 함수"""
    print("\n" + "=" * 60)
    print("MD Summarizer 사용 예시")
    print("=" * 60 + "\n")
    
    # 예시 실행
    try:
        example_1_basic_summarization()
        # example_2_file_summarization()  # 파일 경로 설정 후 주석 해제
        example_3_summary_index()
        # example_4_batch_processing()  # 파일 경로 설정 후 주석 해제
        example_5_save_and_load()
        
    except Exception as e:
        print(f"\n오류 발생: {e}")
        print("SGLang 서버가 실행 중인지 확인하세요:")
        print("  bash scripts/start_sglang_dual.sh")


if __name__ == "__main__":
    main()
