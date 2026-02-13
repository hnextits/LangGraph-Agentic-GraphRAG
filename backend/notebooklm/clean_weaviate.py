"""Utility script to delete all Weaviate + Neo4j data (Text, Image, Graph)."""

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


def delete_all_collection(class_name: str) -> Dict[str, Any]:
    """지정된 Weaviate 컬렉션의 모든 객체를 삭제합니다."""
    config = RAGConfig()
    client = config.get_weaviate_client()

    if client is None:
        raise RuntimeError("Weaviate 클라이언트를 초기화할 수 없습니다.")

    try:
        # 컬렉션 존재 여부 확인
        if not client.collections.exists(class_name):
            return {"deleted": 0, "status": "not_found"}

        collection = client.collections.get(class_name)
        all_objects = collection.query.fetch_objects(limit=10000)

        deleted_count = 0
        for obj in all_objects.objects:
            try:
                collection.data.delete_by_id(obj.uuid)
                deleted_count += 1
            except Exception as e:
                print(f"객체 삭제 실패 {obj.uuid}: {e}")

        return {"deleted": deleted_count, "status": "success"}
    finally:
        client.close()


def delete_all_neo4j_nodes() -> Dict[str, Any]:
    """Neo4j의 모든 노드와 관계를 삭제합니다 (MATCH (n) DETACH DELETE n)."""
    config = RAGConfig()
    uri = getattr(config, "NEO4J_URI", "")
    user = getattr(config, "NEO4J_USER", "")
    password = getattr(config, "NEO4J_PASSWORD", "")
    if not uri:
        return {"deleted": 0, "status": "no_uri"}
    try:
        from neo4j import GraphDatabase
        auth = (user, password) if user else None
        driver = GraphDatabase.driver(uri, auth=auth)
        with driver.session() as session:
            # 먼저 노드 수 확인
            count_result = session.run("MATCH (n) RETURN count(n) AS cnt")
            node_count = count_result.single()["cnt"]
            # 전체 삭제 (대량 데이터 시 배치 처리)
            if node_count > 0:
                session.run("MATCH (n) DETACH DELETE n")
        driver.close()
        return {"deleted": node_count, "status": "success"}
    except ImportError:
        return {"deleted": 0, "status": "neo4j_not_installed"}
    except Exception as exc:
        return {"deleted": 0, "status": f"error: {exc}"}


def main() -> None:
    try:
        print("🗑️  Weaviate + Neo4j 데이터 정리 시작...")
        
        # TextDocument 삭제
        print("\n📄 TextDocument 데이터 삭제 중...")
        text_result = delete_all_text_documents()
        print(f"✅ TextDocument: {text_result['deleted']}개 삭제 완료")
        
        # ImageDocument 삭제
        print("\n🖼️  ImageDocument 데이터 삭제 중...")
        image_result = delete_all_image_documents()
        print(f"✅ ImageDocument: {image_result['deleted']}개 삭제 완료")
        
        # GraphEntity 삭제
        print("\n🔵 GraphEntity 데이터 삭제 중...")
        entity_result = delete_all_collection("GraphEntity")
        if entity_result['status'] == 'not_found':
            print("⏭️  GraphEntity 컬렉션이 존재하지 않습니다.")
        else:
            print(f"✅ GraphEntity: {entity_result['deleted']}개 삭제 완료")
        
        # GraphEvent 삭제
        print("\n🟡 GraphEvent 데이터 삭제 중...")
        event_result = delete_all_collection("GraphEvent")
        if event_result['status'] == 'not_found':
            print("⏭️  GraphEvent 컬렉션이 존재하지 않습니다.")
        else:
            print(f"✅ GraphEvent: {event_result['deleted']}개 삭제 완료")
        
        # GraphRelation 삭제
        print("\n🔗 GraphRelation 데이터 삭제 중...")
        relation_result = delete_all_collection("GraphRelation")
        if relation_result['status'] == 'not_found':
            print("⏭️  GraphRelation 컬렉션이 존재하지 않습니다.")
        else:
            print(f"✅ GraphRelation: {relation_result['deleted']}개 삭제 완료")
        
        # Neo4j 삭제
        print("\n🔴 Neo4j 데이터 삭제 중...")
        neo4j_result = delete_all_neo4j_nodes()
        if neo4j_result['status'] == 'no_uri':
            print("⏭️  Neo4j URI가 설정되지 않았습니다.")
        elif neo4j_result['status'] == 'neo4j_not_installed':
            print("⏭️  neo4j 패키지가 설치되지 않았습니다.")
        elif neo4j_result['status'] == 'success':
            print(f"✅ Neo4j: {neo4j_result['deleted']}개 노드 삭제 완료")
        else:
            print(f"⚠️  Neo4j: {neo4j_result['status']}")

        # 총합 결과
        total_deleted = (
            text_result['deleted'] + image_result['deleted']
            + entity_result['deleted'] + event_result['deleted']
            + relation_result['deleted'] + neo4j_result['deleted']
        )
        print(f"\n🎉 총 {total_deleted}개의 객체를 성공적으로 삭제했습니다!")
        
    except Exception as exc:
        print(f"❌ 삭제 중 오류 발생: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
