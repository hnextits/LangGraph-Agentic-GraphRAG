"""Utility script to delete all TextDocument objects from Weaviate."""

import json
import sys
from typing import Any, Dict

from config import RAGConfig


def delete_all_text_documents() -> Dict[str, Any]:
    """Delete every object stored under the configured TextDocument class."""
    config = RAGConfig()
    client = config.get_weaviate_client()

    if client is None:
        raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다. 서버 상태를 확인하세요.")

    try:
        # v4 API: collection을 가져와서 삭제
        collection = client.collections.get(config.WEAVIATE_TEXT_CLASS)
        
        # 모든 객체 삭제
        result = collection.data.delete_many(
            where={
                "path": ["chunk_id"],
                "operator": "Like",
                "valueText": "*",
            }
        )
        
        return {
            "deleted": result.matches if hasattr(result, 'matches') else 0,
            "status": "success"
        }
    finally:
        client.close()


def main() -> None:
    try:
        result = delete_all_text_documents()
    except Exception as exc:
        print(f"❌ 삭제 중 오류 발생: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("✅ TextDocument 클래스의 데이터를 모두 삭제했습니다.")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
