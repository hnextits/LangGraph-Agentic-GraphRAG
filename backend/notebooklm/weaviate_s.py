import weaviate
import logging
import datetime 

# Weaviate 클라이언트 정보 (코드에서 사용한 정보와 동일)
WEAVIATE_HOST = "127.0.0.1"
WEAVIATE_PORT = 8080
TEXT_CLASS_NAME = "TextDocument"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

try:
    # 1. v4 클라이언트 연결
    client = weaviate.connect_to_custom(
        http_host=WEAVIATE_HOST,
        http_port=WEAVIATE_PORT,
        http_secure=False,
        grpc_host=WEAVIATE_HOST,
        grpc_port=50051,
        grpc_secure=False
    )
    logger.info(f"Weaviate 클라이언트 연결 성공: http://{WEAVIATE_HOST}:{WEAVIATE_PORT}")

    # 2. 객체 수 확인 쿼리 (v4 API)
    collection = client.collections.get(TEXT_CLASS_NAME)
    
    # aggregate를 사용하여 총 개수 확인
    result = collection.aggregate.over_all(total_count=True)
    object_count = result.total_count
    
    # 3. 결과 출력
    print(f"\n Weaviate 클래스 '{TEXT_CLASS_NAME}'의 총 객체 수: {object_count}개")
    print(datetime.datetime.now())

    if object_count > 0:
        print("데이터베이스에 데이터가 성공적으로 저장된 것으로 보입니다.")
    else:
        print("데이터베이스에 객체가 없습니다. 저장 실패 또는 스키마 문제일 수 있습니다.")

except Exception as e:
    logger.error(f"\n❌ Weaviate 데이터 확인 중 오류 발생: {str(e)}")
    print("클라이언트 연결 또는 쿼리 실행에 문제가 있습니다. Weaviate 서버 상태를 확인하세요.")
finally:
    if 'client' in locals():
        client.close()