from neo4j_manager import Neo4jManager
import json

mgr = Neo4jManager(auth=None)  # 인증 비활성화 상태면 None 유지
data = json.load(open("/home/jeonghs/workspace/LangGraph_GraphRAG/backend/data_pipeline/Results/graph_metadata/RL_Slides_13_RLHF_DPO_r2.graph.json", encoding="utf-8"))
mgr.upsert_graph(data)
mgr.close()