import weaviate
import weaviate.classes as wvc
from weaviate.classes.config import Tokenization
from weaviate.auth import AuthApiKey
from typing import List, Dict, Any

# 조건부 import
if __name__ == "__main__":
    from skill.mindmap.config import Config
else:
    try:
        from .config import Config
    except ImportError:
        from skill.mindmap.config import Config

import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class WeaviateService:
    """A service to interact with Weaviate DB for semantic operations."""

    def __init__(self):
        """Initializes the Weaviate client and ensures schema exists."""
        auth_config = AuthApiKey(api_key=Config.WEAVIATE_API_KEY) if Config.WEAVIATE_API_KEY else None
        
        self.client = weaviate.connect_to_custom(
            http_host=Config.WEAVIATE_URL.replace('http://', '').split(':')[0],
            http_port=int(Config.WEAVIATE_URL.split(':')[-1]),
            http_secure=False,
            grpc_host=Config.WEAVIATE_URL.replace('http://', '').split(':')[0], # Assuming gRPC is on the same host
            grpc_port=50051, # Default gRPC port
            grpc_secure=False,
            auth_credentials=auth_config
        )
        self.class_name = Config.WEAVIATE_CLASS_NAME
        self._ensure_schema()

    def _ensure_schema(self):
        """Creates the 'Segment' class in Weaviate if it doesn't exist."""
        # Temporarily delete the class to ensure the new schema is applied
        if self.client.collections.exists(self.class_name):
            logger.warning(f"Deleting existing class '{self.class_name}' to apply new schema.")
            self.client.collections.delete(self.class_name)

        if not self.client.collections.exists(self.class_name):
            logger.info(f"Schema '{self.class_name}' not found. Creating it...")
            self.client.collections.create(
                name=self.class_name,
                vector_index_config=wvc.config.Configure.VectorIndex.hnsw(),
                properties=[
                    wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
                    wvc.config.Property(name="segment_id", data_type=wvc.config.DataType.TEXT, tokenization=Tokenization.WORD),
                    wvc.config.Property(name="source_document", data_type=wvc.config.DataType.TEXT, tokenization=Tokenization.WORD),
                ]
            )
            logger.info(f"Schema '{self.class_name}' created successfully.")

    def ingest_segments(self, segments: List[Dict[str, Any]], document_name: str):
        """Ingests a list of document segments into Weaviate."""
        segments_collection = self.client.collections.get(self.class_name)
        
        data_objects = [
            wvc.data.DataObject(
                properties={
                    "text": seg["text"],
                    "segment_id": seg["id"],
                    "source_document": document_name,
                }
            )
            for seg in segments
        ]
        
        result = segments_collection.data.insert_many(data_objects)
        
        if result.has_errors:
            logger.error(f"Errors during ingestion: {result.errors}")
        else:
            logger.info(f"Successfully ingested {len(segments)} segments for document '{document_name}'.")

    def find_semantic_clusters(self, document_name: str, num_topics: int = 6, min_cluster_size: int = 3, distance_threshold: float = 0.3) -> List[List[Dict[str, Any]]]:
        """Finds semantic clusters of segments using simple grouping (fallback without vectorizer)."""
        logger.warning("Weaviate vectorizer not configured. Using simple grouping instead of semantic clustering.")
        segments_collection = self.client.collections.get(self.class_name)

        # Fetch all segments for the document
        response = segments_collection.query.fetch_objects(
            filters=wvc.query.Filter.by_property("source_document").equal(document_name),
            limit=10000
        )
        
        all_segments = [obj.properties for obj in response.objects]
        
        # Simple grouping: divide segments into equal-sized clusters
        if not all_segments:
            logger.warning("No segments found for clustering.")
            return []
        
        cluster_size = max(min_cluster_size, len(all_segments) // num_topics)
        clusters = []
        
        for i in range(0, len(all_segments), cluster_size):
            cluster = all_segments[i:i + cluster_size]
            if len(cluster) >= min_cluster_size:
                clusters.append(cluster)
            if len(clusters) >= num_topics:
                break
        
        logger.info(f"Created {len(clusters)} simple clusters (fallback mode).")
        return clusters

    def close(self):
        """Closes the Weaviate client connection."""
        self.client.close()
