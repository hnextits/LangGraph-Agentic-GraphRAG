import weaviate
import logging

# Weaviate 클라이언트 정보 (코드에서 사용한 정보와 동일)
WEAVIATE_URL = "http://127.0.0.1:8080"
TEXT_CLASS_NAME = "ImageDocument"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

try:
    # 1. 클라이언트 연결
    client = weaviate.Client(url=WEAVIATE_URL)
    logger.info(f"Weaviate 클라이언트 연결 성공: {WEAVIATE_URL}")

    # 2. 객체 수 확인 쿼리
    count_result = (
        client.query
        .aggregate(TEXT_CLASS_NAME)
        .with_meta_count()
        .do()
    )

    # 3. 결과 출력
    object_count = count_result["data"]["Aggregate"][TEXT_CLASS_NAME][0]["meta"]["count"]
    
    # 이전에 132개의 청크를 만들었으므로, 최소 132개 이상이어야 합니다.
    print(f"\n✅ Weaviate 클래스 '{TEXT_CLASS_NAME}'의 총 객체 수: {object_count}개")

    if object_count > 0:
        print("데이터베이스에 데이터가 성공적으로 저장된 것으로 보입니다.")
    else:
        print("데이터베이스에 객체가 없습니다. 저장 실패 또는 스키마 문제일 수 있습니다.")

except Exception as e:
    logger.error(f"\n❌ Weaviate 데이터 확인 중 오류 발생: {str(e)}")
    print("클라이언트 연결 또는 쿼리 실행에 문제가 있습니다. Weaviate 서버 상태를 확인하세요.")