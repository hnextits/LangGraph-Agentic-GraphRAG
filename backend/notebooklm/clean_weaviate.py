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

    where_filter: Dict[str, Any] = {
        "path": ["chunk_id"],
        "operator": "Like",
        "valueText": "*",
    }

    result = client.batch.delete_objects(
        class_name=config.WEAVIATE_TEXT_CLASS,
        where=where_filter,
        output="verbose",
    )
    return result


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
