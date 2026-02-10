"""Utility script to delete all TextDocument objects from Weaviate."""

import json
import sys
from typing import Any, Dict

from config import RAGConfig


def delete_all_image_documents() -> Dict[str, Any]:
    """Delete every object stored under the configured ImageDocument class."""
    config = RAGConfig()
    client = config.get_weaviate_client()

    if client is None:
        raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다. 서버 상태를 확인하세요.")

    try:
        # v4 API: collection을 가져와서 삭제
        collection = client.collections.get(config.WEAVIATE_IMAGE_CLASS)
        
        # 모든 객체 가져오기
        all_objects = collection.query.fetch_objects(limit=10000)
        
        # 객체들을 개별적으로 삭제
        deleted_count = 0
        for obj in all_objects.objects:
            try:
                collection.data.delete_by_id(obj.uuid)
                deleted_count += 1
            except Exception as e:
                print(f"객체 삭제 실패 {obj.uuid}: {e}")
        
        return {
            "deleted": deleted_count,
            "status": "success"
        }
    finally:
        client.close()


def delete_all_text_documents() -> Dict[str, Any]:
    """Delete every object stored under the configured TextDocument class."""
    config = RAGConfig()
    client = config.get_weaviate_client()

    if client is None:
        raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다. 서버 상태를 확인하세요.")

    try:
        # v4 API: collection을 가져와서 삭제
        collection = client.collections.get(config.WEAVIATE_TEXT_CLASS)
        
        # 모든 객체 가져오기
        all_objects = collection.query.fetch_objects(limit=10000)
        
        # 객체들을 개별적으로 삭제
        deleted_count = 0
        for obj in all_objects.objects:
            try:
                collection.data.delete_by_id(obj.uuid)
                deleted_count += 1
            except Exception as e:
                print(f"객체 삭제 실패 {obj.uuid}: {e}")
        
        return {
            "deleted": deleted_count,
            "status": "success"
        }
    finally:
        client.close()


def main() -> None:
    try:
        print("🗑️  Weaviate 데이터 정리 시작...")
        
        # TextDocument 삭제
        print("\n📄 TextDocument 데이터 삭제 중...")
        text_result = delete_all_text_documents()
        print(f"✅ TextDocument: {text_result['deleted']}개 삭제 완료")
        
        # ImageDocument 삭제
        print("\n🖼️  ImageDocument 데이터 삭제 중...")
        image_result = delete_all_image_documents()
        print(f"✅ ImageDocument: {image_result['deleted']}개 삭제 완료")
        
        # 총합 결과
        total_deleted = text_result['deleted'] + image_result['deleted']
        print(f"\n🎉 총 {total_deleted}개의 객체를 성공적으로 삭제했습니다!")
        
    except Exception as exc:
        print(f"❌ 삭제 중 오류 발생: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
