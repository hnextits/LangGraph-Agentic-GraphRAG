from neo4j import GraphDatabase
import logging

logger = logging.getLogger(__name__)

class Neo4jManager:
    def __init__(self, uri="bolt://127.0.0.1:7687", auth=None):
        self.driver = GraphDatabase.driver(uri, auth=auth)

    def close(self):
        self.driver.close()

    def upsert_graph(self, graph_json: dict):
        doc_id = graph_json.get("document_id", "unknown")
        entities = graph_json.get("entities", [])
        relations = graph_json.get("relations", [])

        with self.driver.session() as session:
            # 1. 엔티티 생성 (MERGE 사용으로 중복 방지)
            for ent in entities:
                session.run("""
                    MERGE (e:Entity {id: $id})
                    SET e.name = $name, e.type = $type, e.doc_id = $doc_id
                """, id=ent['entity_id'], name=ent['name'], type=ent['type'], doc_id=doc_id)

            # 2. 관계 생성
            for rel in relations:
                session.run("""
                    MATCH (s:Entity {id: $src}), (t:Entity {id: $tgt})
                    MERGE (s)-[r:RELATED]->(t)
                    SET r.relation = $rel_type, r.doc_id = $doc_id
                """, src=rel['source_id'], tgt=rel['target_id'], 
                   rel_type=rel.get('relation', 'related_to'), doc_id=doc_id)
        
        logger.info(f"Neo4j 업로드 완료: {doc_id} ({len(entities)} nodes)")