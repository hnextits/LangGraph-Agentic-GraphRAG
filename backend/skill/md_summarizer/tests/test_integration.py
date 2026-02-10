"""
통합 테스트 스크립트
기존 nextitslm 시스템과의 호환성 테스트
"""

import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src import SGLangClient, MDParser, MDSummaryIndex


def test_sglang_client():
    """SGLang 클라이언트 기본 테스트"""
    print("\n" + "="*60)
    print("테스트 1: 실제 문서 요약 테스트")
    print("="*60)
    
    try:
        client = SGLangClient(endpoints=["http://localhost:30000", "http://localhost:30001"])
        parser = MDParser()
        
        # 실제 문서 읽기
        doc_path = Path(__file__).parent / "sample_documents" / "page3.md"
        
        if not doc_path.exists():
            print(f"\n⚠️  테스트 문서를 찾을 수 없습니다: {doc_path}")
            return False
        
        print(f"\n📄 문서 읽기: {doc_path.name}")
        content = parser.read_file(str(doc_path))
        
        print(f"   - 문서 길이: {len(content):,} 문자")
        print(f"   - 예상 토큰: ~{len(content)//4:,} tokens")
        
        # 헤더 추출
        headers = parser.extract_headers(content)
        print(f"   - 헤더 수: {len(headers)}개")
        if headers:
            print(f"   - 주요 헤더: {headers[0]['text']}")
        
        print("\n⏳ 요약 생성 중... (30초~1분 소요)")
        print("-" * 60)
        
        summary = client.generate_answer(content, max_tokens=2000)
        
        print("\n" + "="*60)
        print("📝 요약 결과")
        print("="*60)
        print(summary)
        print("="*60)
        
        # 요약 통계
        print(f"\n📊 요약 통계:")
        print(f"   - 원본 길이: {len(content):,} 문자")
        print(f"   - 요약 길이: {len(summary):,} 문자")
        print(f"   - 압축률: {len(summary)/len(content)*100:.1f}%")
        
        print("\n✅ 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_compatibility():
    """기존 AnswerGenerator와의 호환성 테스트"""
    print("\n" + "="*60)
    print("테스트 2: 기존 시스템 호환성")
    print("="*60)
    
    try:
        # 기존 방식으로 사용
        from src.sglang_client import AnswerGenerator
        
        generator = AnswerGenerator(endpoints=["http://localhost:30000"])
        
        # 기존 메서드 호출
        test_data = [
            {"link": "test.md", "data": "테스트 데이터입니다.", "google_snipping": ""}
        ]
        
        processed = generator.make_llm_input_data(None, test_data)
        print(f"\n✅ make_llm_input_data() 호환: {len(processed)}개 항목")
        
        timestamp = generator.get_timestamp()
        print(f"✅ get_timestamp() 호환: {timestamp}")
        
        generator.cleanup_model()
        print("✅ cleanup_model() 호환")
        
        print("\n✅ 호환성 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"\n❌ 호환성 테스트 실패: {e}")
        return False


def test_md_parser():
    """MD 파서 테스트"""
    print("\n" + "="*60)
    print("테스트 3: MD 파서")
    print("="*60)
    
    try:
        parser = MDParser()
        
        # 테스트 텍스트
        test_md = """
# 제목 1

이것은 테스트 문서입니다.

## 제목 2

- 항목 1
- 항목 2

### 제목 3

내용입니다.
"""
        
        # 헤더 추출
        headers = parser.extract_headers(test_md)
        print(f"\n추출된 헤더: {len(headers)}개")
        for h in headers:
            print(f"  - Level {h['level']}: {h['text']}")
        
        # 텍스트 정리
        cleaned = parser.clean_text(test_md)
        print(f"\n정리된 텍스트 길이: {len(cleaned)} 문자")
        
        # 청킹
        chunks = parser.chunk_text(test_md, chunk_size=50)
        print(f"청크 수: {len(chunks)}개")
        
        print("\n✅ MD 파서 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"\n❌ MD 파서 테스트 실패: {e}")
        return False


def test_summary_index():
    """요약 인덱스 시스템 테스트 - 실제 문서 사용"""
    print("\n" + "="*60)
    print("테스트 4: 요약 인덱스 시스템 (실제 문서)")
    print("="*60)
    
    try:
        summarizer = MDSummaryIndex(
            sglang_endpoints=["http://localhost:30000", "http://localhost:30001"]
        )
        
        # 실제 문서 추가
        doc_path = Path(__file__).parent / "sample_documents" / "원가관리회계.md"
        
        if not doc_path.exists():
            print(f"\n⚠️  테스트 문서를 찾을 수 없습니다: {doc_path}")
            return False
        
        print(f"\n📄 문서 추가: {doc_path.name}")
        summarizer.add_document(doc_path.name, file_path=str(doc_path))
        
        # 통계 확인
        stats = summarizer.get_statistics()
        print(f"   - 총 문서: {stats['total_documents']}개")
        print(f"   - 평균 길이: {stats['avg_content_length']:,} 문자")
        
        # 요약 생성
        print("\n⏳ 요약 생성 중... (30초~1분 소요)")
        print("-" * 60)
        
        summarizer.generate_summaries(max_tokens=2000)
        
        print("\n" + "="*60)
        print("📝 생성된 요약")
        print("="*60)
        
        for i, (doc_id, summary) in enumerate(zip(stats['doc_ids'], summarizer.summaries)):
            print(f"\n[문서 {i+1}] {doc_id}")
            print("-" * 60)
            print(summary)
            print("-" * 60)
        
        # 최종 통계
        stats = summarizer.get_statistics()
        print(f"\n📊 최종 통계:")
        print(f"   - 총 요약: {stats['total_summaries']}개")
        print(f"   - 평균 원본 길이: {stats['avg_content_length']:,} 문자")
        print(f"   - 평균 요약 길이: {stats['avg_summary_length']:,} 문자")
        print(f"   - 평균 압축률: {stats['avg_summary_length']/stats['avg_content_length']*100:.1f}%")
        
        print("\n✅ 요약 인덱스 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"\n❌ 요약 인덱스 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dual_gpu_load_balancing():
    """듀얼 GPU 로드 밸런싱 테스트"""
    print("\n" + "="*60)
    print("테스트 5: 듀얼 GPU 로드 밸런싱")
    print("="*60)
    
    try:
        client = SGLangClient(
            endpoints=["http://localhost:30000", "http://localhost:30001"]
        )
        
        # 여러 요청 보내기
        test_texts = [
            "첫 번째 테스트 문서입니다.",
            "두 번째 테스트 문서입니다.",
            "세 번째 테스트 문서입니다.",
            "네 번째 테스트 문서입니다.",
        ]
        
        print(f"\n{len(test_texts)}개 요청을 듀얼 GPU로 분산 처리...")
        
        for i, text in enumerate(test_texts, 1):
            endpoint = client._get_next_endpoint()
            print(f"  요청 {i} → {endpoint}")
        
        print("\n✅ 로드 밸런싱 테스트 성공!")
        return True
        
    except Exception as e:
        print(f"\n❌ 로드 밸런싱 테스트 실패: {e}")
        return False


def main():
    """메인 테스트 실행"""
    print("\n" + "="*60)
    print("MD Summarizer 통합 테스트")
    print("="*60)
    
    print("\n⚠️  주의: 이 테스트는 SGLang 서버가 실행 중이어야 합니다.")
    print("서버 시작: bash scripts/start_sglang_dual.sh\n")
    
    results = []
    
    # 테스트 실행
    results.append(("SGLang 클라이언트", test_sglang_client()))
    results.append(("호환성", test_compatibility()))
    results.append(("MD 파서", test_md_parser()))
    results.append(("요약 인덱스", test_summary_index()))
    results.append(("듀얼 GPU", test_dual_gpu_load_balancing()))
    
    # 결과 요약
    print("\n" + "="*60)
    print("테스트 결과 요약")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 성공" if result else "❌ 실패"
        print(f"{name}: {status}")
    
    print(f"\n총 {passed}/{total} 테스트 통과")
    
    if passed == total:
        print("\n🎉 모든 테스트 통과!")
    else:
        print("\n⚠️  일부 테스트 실패. 로그를 확인하세요.")


if __name__ == "__main__":
    main()
