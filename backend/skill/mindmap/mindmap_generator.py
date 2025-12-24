import re
import os
import random
import json
import asyncio
import hashlib
import base64
import zlib
import logging
import copy
from datetime import datetime
from enum import Enum, auto
from typing import Dict, Any, List, Union, Optional, Tuple, Set
from termcolor import colored
import aiofiles
from fuzzywuzzy import fuzz
import sglang as sgl
import nest_asyncio
import sys
from pathlib import Path

# 조건부 import: 스크립트 직접 실행 vs 모듈 import
if __name__ == "__main__":
    # 스크립트 직접 실행 시: 절대 import
    from skill.mindmap.config import Config
    from skill.mindmap.weaviate_service import WeaviateService
    from skill.mindmap.segment_processor import SegmentProcessor, DocumentSegment
else:
    # 모듈로 import될 때: 상대 import
    try:
        from .config import Config
        from .weaviate_service import WeaviateService
        from .segment_processor import SegmentProcessor, DocumentSegment
    except ImportError:
        # 상대 import 실패 시 절대 import로 폴백
        from skill.mindmap.config import Config
        from skill.mindmap.weaviate_service import WeaviateService
        from skill.mindmap.segment_processor import SegmentProcessor, DocumentSegment

def get_logger():
    """Mindmap-specific logger with colored output for generation stages."""
    logger = logging.getLogger("mindmap_generator")
    if not logger.handlers:
        handler = logging.StreamHandler()
        
        # Custom formatter that adds colors specific to mindmap generation stages
        def colored_formatter(record):
            message = record.msg
            
            # Color-code specific mindmap generation stages and metrics
            if "Starting mindmap generation" in message:
                message = colored("🚀 " + message, "cyan", attrs=["bold"])
            elif "Detected document type:" in message:
                doc_type = message.split(": ")[1]
                message = f"📄 Document Type: {colored(doc_type, 'yellow', attrs=['bold'])}"
            elif "Extracting main topics" in message:
                message = colored("📌 " + message, "blue")
            elif "Processing topic" in message:
                # Highlight topic name and progress
                parts = message.split("'")
                if len(parts) >= 3:
                    topic_name = parts[1]
                    message = f"🔍 Processing: {colored(topic_name, 'green')} {colored(parts[2], 'white')}"
            elif "Successfully extracted" in message:
                if "topics" in message:
                    message = colored("✅ " + message, "green")
                elif "subtopics" in message:
                    message = colored("➕ " + message, "cyan")
                elif "details" in message:
                    message = colored("📝 " + message, "blue")
            elif "Approaching word limit" in message:
                message = colored("⚠️ " + message, "yellow")
            elif "Error" in message or "Failed" in message:
                message = colored("❌ " + message, "red", attrs=["bold"])
            elif "Completion status:" in message:
                # Highlight progress metrics
                message = message.replace("Completion status:", colored("📊 Progress:", "cyan", attrs=["bold"]))
                metrics = message.split("Progress:")[1]
                parts = metrics.split(",")
                colored_metrics = []
                for part in parts:
                    if ":" in part:
                        label, value = part.split(":")
                        colored_metrics.append(f"{label}:{colored(value, 'yellow')}")
                message = "📊 Progress:" + ",".join(colored_metrics)
            elif "Mindmap generation completed" in message:
                message = colored("🎉 " + message, "green", attrs=["bold"])
                
            # Format timestamp and add any extra attributes
            timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
            log_message = f"{colored(timestamp, 'white')} {message}"
            
            # Add any extra attributes in grey
            if hasattr(record, 'extra') and record.extra:
                extra_str = ' '.join(f"{k}={v}" for k, v in record.extra.items())
                log_message += f" {colored(f'[{extra_str}]', 'grey')}"
                
            return log_message
            
        class MindmapFormatter(logging.Formatter):
            def format(self, record):
                return colored_formatter(record)
                
        handler.setFormatter(MindmapFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

logger = get_logger()

# 환경 감지 및 nest_asyncio 조건부 적용
ENABLE_NEST_ASYNCIO = __name__ == "__main__" or os.environ.get("MINDMAP_ENABLE_NEST_ASYNCIO") == "1"

if ENABLE_NEST_ASYNCIO:
    try:
        current_loop = asyncio.get_event_loop()
        loop_type = str(type(current_loop))
        
        if 'uvloop' in loop_type:
            logger.info("uvloop 환경 감지 - nest_asyncio 스킵")
        else:
            nest_asyncio.apply()
            logger.info("일반 asyncio 환경 - nest_asyncio 적용")
    except Exception as e:
        logger.warning(f"이벤트 루프 감지 실패: {e}")
else:
    logger.info("nest_asyncio 비활성화 - FastAPI/uvicorn 환경 가정")


class DocumentOptimizer:
    """Optimizer using SGLang local model."""
    def __init__(self):
        config = Config()
        logger.info(f"Initializing SGLang with model: {config.SGLANG_MODEL_PATH}")
        logger.info(f"Device: {config.SGLANG_DEVICE}")
        logger.info(f"Memory fraction: {config.SGLANG_MEM_FRACTION}")
        
        # SGLang Engine은 환경변수 CUDA_VISIBLE_DEVICES로 GPU 선택
        import os
        device_id = config.SGLANG_DEVICE.replace('cuda:', '')
        os.environ['CUDA_VISIBLE_DEVICES'] = device_id
        
        self.llm = sgl.Engine(
            model_path=config.SGLANG_MODEL_PATH,
            mem_fraction_static=config.SGLANG_MEM_FRACTION
        )
        logger.info("SGLang engine initialized successfully")

    async def generate_completion(self, prompt: str, max_tokens: int = 5000, request_id: str = None, task: Optional[str] = None) -> Optional[str]:
        try:
            prompt_preview = " ".join(prompt.split()[:40])
            logger.info(
                f"\n{colored('🔄 Generating', 'cyan', attrs=['bold'])}\n"
                f"Task: {colored(task or 'unknown', 'yellow')}\n"
                f"Prompt preview: {colored(prompt_preview + '...', 'white')}"
            )

            # nest_asyncio 덕분에 동기 함수를 직접 호출 가능
            sampling_params = {"temperature": 0.4, "max_new_tokens": max_tokens}
            outputs = self.llm.generate([prompt], sampling_params)
            
            response_text = outputs[0]["text"]
            response_preview = " ".join(response_text.split()[:30])
            logger.info(
                f"\n{colored('✅ Generated', 'green', attrs=['bold'])}\n"
                f"Response preview: {colored(response_preview + '...', 'white')}"
            )
            return response_text
        except Exception as e:
            logger.error(f"Error generating completion: {str(e)}")
            return None
    
class MinimalDatabaseStub:
    """Minimal database stub that provides just enough for the mindmap generator."""
    @staticmethod
    async def get_document_by_id(document_id: str) -> Dict[str, Any]:
        """Stub that returns minimal document info."""
        return {
            "id": document_id,
            "original_file_name": f"document_{document_id}.txt",
            "sanitized_filename": document_id,
            "status": "processing",
            "progress_percentage": 0
        }
        
    @staticmethod
    async def get_optimized_text(document_id: str, request_id: str) -> Optional[str]:
        """In our simplified version, this just returns the raw text content."""
        return MinimalDatabaseStub._stored_text
        
    @staticmethod
    async def update_document_status(*args, **kwargs) -> Dict[str, Any]:
        """Stub that just returns success."""
        return {"status": "success"}
        
    @staticmethod
    async def add_token_usage(*args, **kwargs) -> None:
        """Stub that does nothing."""
        pass

    # Add a way to store the text content
    _stored_text = ""
    
    @classmethod
    def store_text(cls, text: str):
        """Store text content for later retrieval."""
        cls._stored_text = text

async def initialize_db():
    """Minimal DB initialization that just returns our stub."""
    return MinimalDatabaseStub()

class DocumentType(Enum):
    """Enumeration of supported document types."""
    TECHNICAL = auto()
    SCIENTIFIC = auto()
    NARRATIVE = auto()
    BUSINESS = auto()
    ACADEMIC = auto()
    LEGAL = auto()      
    MEDICAL = auto()    
    INSTRUCTIONAL = auto() 
    ANALYTICAL = auto() 
    PROCEDURAL = auto() 
    GENERAL = auto()

    @classmethod
    def from_str(cls, value: str) -> 'DocumentType':
        """Convert string to DocumentType enum."""
        try:
            return cls[value.upper()]
        except KeyError:
            return cls.GENERAL

class NodeShape(Enum):
    """Enumeration of node shapes for the mindmap structure."""
    ROOT = '(())'        # Double circle for root node (📄)
    TOPIC = '(())'       # Double circle for main topics
    SUBTOPIC = '()'      # Single circle for subtopics
    DETAIL = '[]'        # Square brackets for details

    def apply(self, text: str) -> str:
        """Apply the shape to the text."""
        return {
            self.ROOT: f"(({text}))",
            self.TOPIC: f"(({text}))",
            self.SUBTOPIC: f"({text})",
            self.DETAIL: f"[{text}]"
        }[self]

class MindMapGenerationError(Exception):
    """Custom exception for mindmap generation errors."""
    pass

class ContentItem:
    """Class to track content items with their context information."""
    def __init__(self, text: str, path: List[str], node_type: str, importance: str = None):
        self.text = text
        self.path = path
        self.path_str = ' → '.join(path)
        self.node_type = node_type
        self.importance = importance
        
    def __str__(self):
        return f"{self.text} ({self.node_type} at {self.path_str})"

class MindMapGenerator:
    def __init__(self):
        self.optimizer = DocumentOptimizer()
        self.weaviate_service = WeaviateService()
        self.config = {
            'max_summary_length': 1800,
            'max_tokens': 2500,
            'valid_types': [t.name.lower() for t in DocumentType],
            'default_type': DocumentType.GENERAL.name.lower(),
            'max_retries': 3,
            'request_timeout': 30,  # seconds
            'chunk_size': 8192,     # bytes for file operations
            'max_topics': 6,        # NotebookLM-style main topics
            'max_subtopics': 4,     # Concise subtopics per topic
            'max_details': 4,       # Concise details per subtopic
            'similarity_threshold': {
                'topic': 78,
                'subtopic': 74,
                'detail': 68
            },
            'reality_check': {
                'batch_size': 8,    # Number of nodes to verify in parallel
                'min_verified_topics': 4,  # Minimum verified topics needed
                'min_verified_ratio': 0.6  # Minimum ratio of verified content
            }
        }
        self.verification_stats = {
            'total_nodes': 0,
            'verified_nodes': 0,
            'topics': {'total': 0, 'verified': 0},
            'subtopics': {'total': 0, 'verified': 0},
            'details': {'total': 0, 'verified': 0}
        }
        self._emoji_cache = {}
        self.retry_config = {
            'max_retries': 3,
            'base_delay': 1,
            'max_delay': 10,
            'jitter': 0.1,
            'timeout': 30
        }
        self._initialize_prompts()
        self.numbered_pattern = re.compile(r'^\s*\d+\.\s*(.+)$')
        self.parentheses_regex = re.compile(r'(\((?!\()|(?<!\))\))')
        self.control_chars_regex = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')
        self.unescaped_quotes_regex = re.compile(r'(?<!\\)"(?!,|\s*[}\]])')
        self.percentage_regex1 = re.compile(r'(\d+(?:\.\d+)?)\s+(?=percent|of\s|share|margin|CAGR)', re.IGNORECASE)
        self.percentage_regex2 = re.compile(r'\s+percent\b', re.IGNORECASE)
        self.backslash_regex = re.compile(r'\\{2,}')
        self.special_chars_regex = re.compile(r'[^\w\s\[\]\(\)\{\}\'_\-.,`*%\\\u1100-\u11FF\u3130-\u318F\uAC00-\uD7A3]')
        self.paren_replacements = {
            '(': '❨',  # U+2768 MEDIUM LEFT PARENTHESIS ORNAMENT
            ')': '❩',  # U+2769 MEDIUM RIGHT PARENTHESIS ORNAMENT
            # Backup alternatives if needed:
            # '(': '⟮',  # U+27EE MATHEMATICAL LEFT FLATTENED PARENTHESIS
            # ')': '⟯',  # U+27EF MATHEMATICAL RIGHT FLATTENED PARENTHESIS
            # Or:
            # '(': '﹙',  # U+FE59 SMALL LEFT PARENTHESIS
            # ')': '﹚',  # U+FE5A SMALL RIGHT PARENTHESIS
        }
        self._emoji_file = os.path.join(os.path.dirname(__file__), "emoji_cache.json")
        self._load_emoji_cache()
        
    def _load_emoji_cache(self):
        """Load emoji cache from disk if available."""
        try:
            if os.path.exists(self._emoji_file):
                with open(self._emoji_file, 'r', encoding='utf-8') as f:
                    loaded_cache = json.load(f)
                    # Convert tuple string keys back to actual tuples
                    self._emoji_cache = {tuple(eval(k)): v for k, v in loaded_cache.items()}
                    logger.info(f"Loaded {len(self._emoji_cache)} emoji mappings from cache")
            else:
                self._emoji_cache = {}
        except Exception as e:
            logger.warning(f"Failed to load emoji cache: {str(e)}")
            self._emoji_cache = {}

    def _save_emoji_cache(self):
        """Save emoji cache to disk for reuse across runs."""
        try:
            # Convert tuple keys to strings for JSON serialization
            serializable_cache = {str(k): v for k, v in self._emoji_cache.items()}
            with open(self._emoji_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_cache, f)
            logger.info(f"Saved {len(self._emoji_cache)} emoji mappings to cache")
        except Exception as e:
            logger.warning(f"Failed to save emoji cache: {str(e)}")
                
    async def _retry_with_exponential_backoff(self, func, *args, **kwargs):
        """Enhanced retry mechanism with jitter and circuit breaker."""
        retries = 0
        max_retries = self.retry_config['max_retries']
        base_delay = self.retry_config['base_delay']
        max_delay = self.retry_config['max_delay']
        
        while retries < max_retries:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                retries += 1
                if retries >= max_retries:
                    raise
                    
                delay = min(base_delay * (2 ** (retries - 1)), max_delay)
                actual_delay = random.uniform(0, delay)
                
                logger.warning(f"Attempt {retries}/{max_retries} failed: {str(e)}. "
                            f"Retrying in {actual_delay:.2f}s")
                
                await asyncio.sleep(actual_delay)

    def _validate_parsed_response(self, parsed: Any, expected_type: str) -> Union[List[Any], Dict[str, Any]]:
        """Validate and normalize parsed JSON response."""
        if expected_type == "array":
            if isinstance(parsed, list):
                return parsed
            elif isinstance(parsed, dict):
                # Try to extract array from common fields
                for key in ['items', 'topics', 'elements', 'data']:
                    if isinstance(parsed.get(key), list):
                        return parsed[key]
                logger.debug("No array found in dictionary fields")
                return []
            else:
                logger.debug(f"Unexpected type for array response: {type(parsed)}")
                return []
        
        return parsed if isinstance(parsed, dict) else {}

    def _clean_detail_response(self, response: str) -> List[Dict[str, str]]:
        """Clean and validate detail responses."""
        try:
            # Remove markdown code blocks if present
            if '```' in response:
                matches = re.findall(r'```(?:json)?(.*?)```', response, re.DOTALL)
                if matches:
                    response = matches[0].strip()
                    
            # Basic cleanup
            response = response.strip()
            
            try:
                parsed = json.loads(response)
            except json.JSONDecodeError:
                # Try cleaning quotes and parse again
                response = response.replace("'", '"')
                try:
                    parsed = json.loads(response)
                except json.JSONDecodeError:
                    return []
                    
            # Handle both array and single object responses
            if isinstance(parsed, dict):
                parsed = [parsed]
                
            # Validate each detail
            valid_details = []
            seen_texts = set()
            
            for item in parsed:
                try:
                    text = str(item.get('text', '')).strip()
                    importance = str(item.get('importance', 'medium')).lower()
                    
                    # Skip empty text or duplicates
                    if not text or text in seen_texts:
                        continue
                        
                    if importance not in ['high', 'medium', 'low']:
                        importance = 'medium'
                        
                    seen_texts.add(text)
                    valid_details.append({
                        'text': text,
                        'importance': importance
                    })
                    
                except Exception as e:
                    logger.debug(f"Error processing detail item: {str(e)}")
                    continue
                    
            return valid_details
            
        except Exception as e:
            logger.error(f"Error in detail cleaning: {str(e)}")
            return []

    def _clean_json_response(self, response: str) -> str:
        """Enhanced JSON response cleaning with advanced recovery and validation."""
        if not response or not isinstance(response, str):
            logger.warning("Empty or invalid response type received")
            return "[]"  # Return empty array as safe default
            
        try:
            # First try to find complete JSON structure
            def find_json_structure(text: str) -> Optional[str]:
                # Look for array pattern
                array_match = re.search(r'\[[\s\S]*?\](?=\s*$|\s*[,}\]])', text)
                if array_match:
                    return array_match.group(0)
                    
                # Look for object pattern
                object_match = re.search(r'\{[\s\S]*?\}(?=\s*$|\s*[,\]}])', text)
                if object_match:
                    return object_match.group(0)
                
                return None

            # Handle markdown code blocks first
            if '```' in response:
                code_blocks = re.findall(r'```(?:json)?([\s\S]*?)```', response)
                if code_blocks:
                    for block in code_blocks:
                        if json_struct := find_json_structure(block):
                            response = json_struct
                            break
            else:
                if json_struct := find_json_structure(response):
                    response = json_struct

            # Advanced character cleaning
            def clean_characters(self, text: str) -> str:
                # Remove control characters while preserving valid whitespace
                text = self.control_chars_regex.sub('', text)
                
                # Normalize quotes and apostrophes
                text = text.replace('“', '"').replace('”', '"')  # Smart double quotes to straight double quotes
                text = text.replace('’', "'").replace('‘', "'")  # Smart single quotes to straight single quotes
                text = text.replace("'", '"')  # Convert single quotes to double quotes
                
                # Normalize whitespace
                text = ' '.join(text.split())
                
                # Escape unescaped quotes within strings
                text = self.unescaped_quotes_regex.sub('\\"', text)
                
                return text

            response = clean_characters(response)

            # Fix common JSON syntax issues
            def fix_json_syntax(text: str) -> str:
                # Fix trailing/multiple commas
                text = re.sub(r',\s*([\]}])', r'\1', text)  # Remove trailing commas
                text = re.sub(r',\s*,', ',', text)  # Remove multiple commas
                
                # Fix missing quotes around keys
                text = re.sub(r'(\{|\,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', text)
                
                # Ensure proper array/object closure
                brackets_stack = []
                for char in text:
                    if char in '[{':
                        brackets_stack.append(char)
                    elif char in ']}':
                        if not brackets_stack:
                            continue  # Skip unmatched closing brackets
                        if (char == ']' and brackets_stack[-1] == '[') or (char == '}' and brackets_stack[-1] == '{'):
                            brackets_stack.pop()
                        
                # Close any unclosed brackets
                while brackets_stack:
                    text += ']' if brackets_stack.pop() == '[' else '}'
                
                return text

            response = fix_json_syntax(response)

            # Validate and normalize structure
            def normalize_structure(text: str) -> str:
                try:
                    # Try parsing to validate
                    parsed = json.loads(text)
                    
                    # Ensure we have an array
                    if isinstance(parsed, dict):
                        # Convert single object to array
                        return json.dumps([parsed])
                    elif isinstance(parsed, list):
                        return json.dumps(parsed)
                    else:
                        return json.dumps([str(parsed)])
                        
                except json.JSONDecodeError:
                    # If still invalid, attempt emergency recovery
                    if text.strip().startswith('{'):
                        return f"[{text.strip()}]"  # Wrap object in array
                    elif not text.strip().startswith('['):
                        return f"[{text.strip()}]"  # Wrap content in array
                    return text
            
            response = normalize_structure(response)

            # Final validation
            try:
                json.loads(response)  # Verify we have valid JSON
                return response
            except json.JSONDecodeError as e:
                logger.warning(f"Final JSON validation failed: {str(e)}")
                # If all cleaning failed, return empty array
                return "[]"

        except Exception as e:
            logger.error(f"Error during JSON response cleaning: {str(e)}")
            return "[]"

    def _parse_llm_response(self, response: str, expected_type: str = "array") -> Union[List[Any], Dict[str, Any]]:
        """Parse and validate LLM response."""
        if not response or not isinstance(response, str):
            logger.warning("Empty or invalid response type received")
            return [] if expected_type == "array" else {}

        try:
            # Extract JSON from markdown code blocks if present
            if '```' in response:
                matches = re.findall(r'```(?:json)?(.*?)```', response, re.DOTALL)
                if matches:
                    response = matches[0].strip()

            # Basic cleanup
            response = response.strip()
            
            # Try to extract first valid JSON object/array
            if expected_type == "object":
                # Find first { ... } pattern
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response)
                if json_match:
                    response = json_match.group(0)
            
            try:
                parsed = json.loads(response)
                return self._validate_parsed_response(parsed, expected_type)
            except json.JSONDecodeError:
                # Try cleaning quotes and parse again
                response = response.replace("'", '"')
                try:
                    parsed = json.loads(response)
                    return self._validate_parsed_response(parsed, expected_type)
                except json.JSONDecodeError:
                    # If we still can't parse, try emergency extraction for arrays
                    if expected_type == "array":
                        items = re.findall(r'"([^"]+)"', response)
                        if items:
                            return items

                        # Try line-by-line extraction
                        lines = response.strip().split('\n')
                        items = [line.strip().strip(',"\'[]{}') for line in lines 
                                if line.strip() and not line.strip().startswith(('```', '{', '}'))]
                        if items:
                            return items
                    else:
                        # For objects, try to extract first JSON object
                        json_match = re.search(r'\{[^{}]*"name"[^{}]*"summary"[^{}]*\}', response)
                        if json_match:
                            try:
                                return json.loads(json_match.group(0))
                            except:
                                pass

                    return [] if expected_type == "array" else {}

        except Exception as e:
            logger.error(f"Unexpected error in JSON parsing: {str(e)}")
            return [] if expected_type == "array" else {}

    def _get_importance_marker(self, importance: str) -> str:
        """Get the appropriate diamond marker based on importance level."""
        markers = {
            'high': '♦️',    # Red diamond for high importance
            'medium': '🔸',  # Orange diamond for medium importance
            'low': '🔹'      # Blue diamond for low importance
        }
        return markers.get(importance.lower(), '🔹')

    async def _save_emoji_cache_async(self):
        """Asynchronous version of save_emoji_cache to avoid blocking."""
        try:
            # Convert to a non-blocking call
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._save_emoji_cache)
        except Exception as e:
            logger.warning(f"Failed to save emoji cache asynchronously: {str(e)}")
            
    async def _select_emoji(self, text: str, node_type: str = 'topic') -> str:
        """Emoji selection disabled for NotebookLM-style output; return empty string."""
        return ""
        # If not in cache, generate emoji
        try:
            prompt = f"""Select the single most appropriate emoji to represent this {node_type}: "{text}"

            Requirements:
            1. Return ONLY the emoji character - no explanations or other text
            2. Choose an emoji that best represents the concept semantically
            3. For abstract concepts, use metaphorical or symbolic emojis
            4. Default options if unsure:
            - Topics: 📄 (document)
            - Subtopics: 📌 (pin)
            - Details: 🔹 (bullet point)
            5. Be creative but clear - the emoji should intuitively represent the concept

            Examples:
            - "Market Growth" → 📈
            - "Customer Service" → 👥
            - "Financial Report" → 💰
            - "Product Development" → ⚙️
            - "Global Expansion" → 🌐
            - "Research and Development" → 🔬
            - "Digital Transformation" → 💻
            - "Supply Chain" → 🔄
            - "Healthcare Solutions" → 🏥
            - "Security Measures" → 🔒

            Return ONLY the emoji character without any explanation."""
            
            response = await self._retry_generate_completion(
                prompt,
                max_tokens=20,
                request_id='',
                task="selecting_emoji"
            )
            
            # Clean the response to get just the emoji
            emoji = response.strip()
            
            # If no emoji was returned or response is too long, use defaults
            if not emoji or len(emoji) > 4:  # Most emojis are 2 chars, some are 4
                defaults = {
                    'topic': '📄',
                    'subtopic': '📌',
                    'detail': '🔹'
                }
                emoji = defaults.get(node_type, '📄')
                
            # Add to in-memory cache
            self._emoji_cache[cache_key] = emoji
            
            # Save cache to disk periodically (every 10 new emojis)
            if len(self._emoji_cache) % 10 == 0:
                await asyncio.create_task(self._save_emoji_cache_async())
                
            return emoji
            
        except Exception as e:
            logger.warning(f"Error selecting emoji: {str(e)}")
            return '📄' if node_type == 'topic' else '📌' if node_type == 'subtopic' else '🔹'

    def _initialize_prompts(self) -> None:
        """Initialize type-specific prompts from a configuration file or define them inline."""
        self.type_specific_prompts = {
            DocumentType.TECHNICAL: {
                'topics': """Analyze this technical document focusing on core system components and relationships.
                
    First, identify the major architectural or technical components that form complete, independent units of functionality.
    Each component should be:
    - A distinct technical system, module, or process
    - Independent enough to be understood on its own
    - Critical to the overall system functionality
    - Connected to at least one other component

    Avoid topics that are:
    - Too granular (implementation details)
    - Too broad (entire system categories)
    - Isolated features without system impact
    - Pure documentation elements

    Think about:
    1. What are the core building blocks?
    2. How do these pieces fit together?
    3. What dependencies exist between components?
    4. What are the key technical boundaries?

    Format: Return a JSON array of component names that represent the highest-level technical building blocks.""",

                'subtopics': """For the technical component '{topic}', identify its essential sub-components and interfaces.

    Each subtopic should:
    - Represent a crucial aspect of this component
    - Have clear technical responsibilities
    - Interface with other parts of the system
    - Contribute to the component's core purpose

    Consider:
    1. What interfaces does this component expose?
    2. What are its internal subsystems?
    3. How does it process data or handle requests?
    4. What services does it provide to other components?
    5. What technical standards or protocols does it implement?

    Format: Return a JSON array of technical subtopic names that form this component's architecture.""",

                'details': """For the technical subtopic '{subtopic}', identify specific implementation aspects and requirements.

    Focus on:
    1. Key algorithms or methods
    2. Data structures and formats
    3. Protocol specifications
    4. Performance characteristics
    5. Error handling approaches
    6. Security considerations
    7. Dependencies and requirements

    Include concrete technical details that are:
    - Implementation-specific
    - Measurable or testable
    - Critical for understanding
    - Relevant to integration

    Format: Return a JSON array of technical specifications and implementation details."""
            },

            DocumentType.SCIENTIFIC: {
                'topics': """Analyze this scientific document focusing on major research components and methodological frameworks.

    Identify main scientific themes that:
    - Represent complete experimental or theoretical units
    - Follow scientific method principles
    - Support the research objectives
    - Build on established scientific concepts

    Consider:
    1. What are the primary research questions?
    2. What methodological approaches are used?
    3. What theoretical frameworks are applied?
    4. What experimental designs are implemented?
    5. How do different research components interact?

    Avoid topics that are:
    - Too specific (individual measurements)
    - Too broad (entire fields of study)
    - Purely descriptive without scientific merit
    - Administrative or non-research elements

    Format: Return a JSON array of primary scientific themes or research components.""",

                'subtopics': """For the scientific theme '{topic}', identify key methodological elements and experimental components.

    Each subtopic should:
    - Represent a distinct experimental or analytical approach
    - Contribute to scientific rigor
    - Support reproducibility
    - Connect to research objectives

    Consider:
    1. What specific methods were employed?
    2. What variables were measured?
    3. What controls were implemented?
    4. What analytical techniques were used?
    5. How were data validated?

    Format: Return a JSON array of scientific subtopics that detail the research methodology.""",

                'details': """For the scientific subtopic '{subtopic}', extract specific experimental parameters and results.

    Focus on:
    1. Measurement specifications
    2. Statistical analyses
    3. Data collection procedures
    4. Validation methods
    5. Error margins
    6. Equipment specifications
    7. Environmental conditions

    Include details that are:
    - Quantifiable
    - Reproducible
    - Statistically relevant
    - Methodologically important

    Format: Return a JSON array of specific scientific parameters and findings."""
            },
            
            DocumentType.NARRATIVE: {
            'topics': """Analyze this narrative document focusing on storytelling elements and plot development.

    Identify major narrative components that:
    - Represent complete story arcs or plot elements
    - Form essential narrative structures
    - Establish key story developments
    - Connect to the overall narrative flow

    Consider:
    1. What are the primary plot points?
    2. What character arcs are developed?
    3. What themes are explored?
    4. What settings are established?
    5. How do different narrative elements interweave?

    Avoid topics that are:
    - Too specific (individual scenes)
    - Too broad (entire genres)
    - Purely stylistic elements
    - Non-narrative content

    Format: Return a JSON array of primary narrative themes or story elements.""",

            'subtopics': """For the narrative theme '{topic}', identify key story elements and developments.

    Each subtopic should:
    - Represent a distinct narrative aspect
    - Support story progression
    - Connect to character development
    - Contribute to theme exploration

    Consider:
    1. What specific plot developments occur?
    2. What character interactions take place?
    3. What conflicts are presented?
    4. What thematic elements are developed?
    5. What setting details are important?

    Format: Return a JSON array of narrative subtopics that detail story components.""",

            'details': """For the narrative subtopic '{subtopic}', extract specific story details and elements.

    Focus on:
    1. Scene descriptions
    2. Character motivations
    3. Dialogue highlights
    4. Setting details
    5. Symbolic elements
    6. Emotional moments
    7. Plot connections

    Include details that are:
    - Story-advancing
    - Character-developing
    - Theme-supporting
    - Atmosphere-building

    Format: Return a JSON array of specific narrative details and elements."""
        },
        
            DocumentType.BUSINESS: {
            'topics': """Analyze this business document focusing on strategic initiatives and market opportunities.

    Identify major business components that:
    - Represent complete business strategies
    - Form essential market approaches
    - Establish key business objectives
    - Connect to organizational goals

    Consider:
    1. What are the primary business objectives?
    2. What market opportunities are targeted?
    3. What strategic initiatives are proposed?
    4. What organizational capabilities are required?
    5. How do different business elements align?

    Avoid topics that are:
    - Too specific (individual tactics)
    - Too broad (entire industries)
    - Administrative elements
    - Non-strategic content

    Format: Return a JSON array of primary business themes or strategic elements.""",

            'subtopics': """For the business theme '{topic}', identify key strategic elements and approaches.

    Each subtopic should:
    - Represent a distinct business aspect
    - Support strategic objectives
    - Connect to market opportunities
    - Contribute to business growth

    Consider:
    1. What specific strategies are proposed?
    2. What market segments are targeted?
    3. What resources are required?
    4. What competitive advantages exist?
    5. What implementation steps are needed?

    Format: Return a JSON array of business subtopics that detail strategic components.""",

            'details': """For the business subtopic '{subtopic}', extract specific strategic details and requirements.

    Focus on:
    1. Market metrics
    2. Financial projections
    3. Resource requirements
    4. Implementation timelines
    5. Success metrics
    6. Risk factors
    7. Growth opportunities

    Include details that are:
    - Measurable
    - Action-oriented
    - Resource-specific
    - Market-focused

    Format: Return a JSON array of specific business details and requirements."""
        },            

            DocumentType.ANALYTICAL: {
                'topics': """Analyze this analytical document focusing on key insights and data patterns.

    Identify major analytical themes that:
    - Represent complete analytical frameworks
    - Reveal significant patterns or trends
    - Support evidence-based conclusions
    - Connect different aspects of analysis

    Consider:
    1. What are the primary analytical questions?
    2. What major patterns emerge from the data?
    3. What key metrics drive the analysis?
    4. How do different analytical components relate?
    5. What are the main areas of investigation?

    Avoid topics that are:
    - Too granular (individual data points)
    - Too broad (entire analytical fields)
    - Purely descriptive without analytical value
    - Administrative or non-analytical elements

    Format: Return a JSON array of primary analytical themes or frameworks.""",

                'subtopics': """For the analytical theme '{topic}', identify key metrics and analytical approaches.

    Each subtopic should:
    - Represent a distinct analytical method or metric
    - Contribute to understanding patterns
    - Support data-driven insights
    - Connect to analytical objectives

    Consider:
    1. What specific analyses were performed?
    2. What metrics were calculated?
    3. What statistical approaches were used?
    4. What patterns were investigated?
    5. How were conclusions validated?

    Format: Return a JSON array of analytical subtopics that detail the investigation methods.""",

                'details': """For the analytical subtopic '{subtopic}', extract specific findings and supporting evidence.

    Focus on:
    1. Statistical results
    2. Trend analyses
    3. Correlation findings
    4. Significance measures
    5. Confidence intervals
    6. Data quality metrics
    7. Validation results

    Include details that are:
    - Quantifiable
    - Statistically significant
    - Evidence-based
    - Methodologically sound

    Format: Return a JSON array of specific analytical findings and metrics."""
            },
            DocumentType.LEGAL: {
                'topics': """Analyze this legal document focusing on key legal principles and frameworks.

    Identify major legal components that:
    - Represent complete legal concepts or arguments
    - Form foundational legal principles
    - Establish key rights, obligations, or requirements
    - Connect to relevant legal frameworks

    Consider:
    1. What are the primary legal issues or questions?
    2. What statutory frameworks apply?
    3. What precedential cases are relevant?
    4. What legal rights and obligations are established?
    5. How do different legal concepts interact?

    Avoid topics that are:
    - Too specific (individual clauses)
    - Too broad (entire bodies of law)
    - Administrative or non-legal elements
    - Purely formatting sections

    Format: Return a JSON array of primary legal themes or frameworks.""",

                'subtopics': """For the legal theme '{topic}', identify key legal elements and requirements.

    Each subtopic should:
    - Represent a distinct legal requirement or concept
    - Support legal compliance or enforcement
    - Connect to statutory or case law
    - Contribute to legal understanding

    Consider:
    1. What specific obligations arise?
    2. What rights are established?
    3. What procedures are required?
    4. What legal tests or standards apply?
    5. What exceptions or limitations exist?

    Format: Return a JSON array of legal subtopics that detail requirements and obligations.""",

                'details': """For the legal subtopic '{subtopic}', extract specific legal provisions and requirements.

    Focus on:
    1. Specific statutory references
    2. Case law citations
    3. Compliance requirements
    4. Procedural steps
    5. Legal deadlines
    6. Jurisdictional requirements
    7. Enforcement mechanisms

    Include details that are:
    - Legally binding
    - Procedurally important
    - Compliance-critical
    - Precedent-based

    Format: Return a JSON array of specific legal provisions and requirements."""
            },
            DocumentType.MEDICAL: {
                'topics': """Analyze this medical document focusing on key clinical concepts and patient care aspects.

    Identify major medical components that:
    - Represent complete clinical concepts
    - Form essential diagnostic or treatment frameworks
    - Establish key medical protocols
    - Connect to standard medical practices

    Consider:
    1. What are the primary medical conditions or issues?
    2. What treatment approaches are discussed?
    3. What diagnostic frameworks apply?
    4. What clinical outcomes are measured?
    5. How do different medical aspects interact?

    Avoid topics that are:
    - Too specific (individual symptoms)
    - Too broad (entire medical fields)
    - Administrative elements
    - Non-clinical content

    Format: Return a JSON array of primary medical themes or clinical concepts.""",

                'subtopics': """For the medical theme '{topic}', identify key clinical elements and protocols.

    Each subtopic should:
    - Represent a distinct clinical aspect
    - Support patient care decisions
    - Connect to medical evidence
    - Contribute to treatment planning

    Consider:
    1. What specific treatments are indicated?
    2. What diagnostic criteria apply?
    3. What monitoring is required?
    4. What contraindications exist?
    5. What patient factors are relevant?

    Format: Return a JSON array of medical subtopics that detail clinical approaches.""",

                'details': """For the medical subtopic '{subtopic}', extract specific clinical guidelines and parameters.

    Focus on:
    1. Dosage specifications
    2. Treatment protocols
    3. Monitoring requirements
    4. Clinical indicators
    5. Risk factors
    6. Side effects
    7. Follow-up procedures

    Include details that are:
    - Clinically relevant
    - Evidence-based
    - Treatment-specific
    - Patient-focused

    Format: Return a JSON array of specific medical parameters and guidelines."""
            },

            DocumentType.INSTRUCTIONAL: {
                'topics': """Analyze this instructional document focusing on key learning objectives and educational frameworks.

    Identify major instructional components that:
    - Represent complete learning units
    - Form coherent educational modules
    - Establish key competencies
    - Connect to learning outcomes

    Consider:
    1. What are the primary learning objectives?
    2. What skill sets are being developed?
    3. What knowledge areas are covered?
    4. What pedagogical approaches are used?
    5. How do different learning components build on each other?

    Avoid topics that are:
    - Too specific (individual facts)
    - Too broad (entire subjects)
    - Administrative elements
    - Non-educational content

    Format: Return a JSON array of primary instructional themes or learning modules.""",

                'subtopics': """For the instructional theme '{topic}', identify key learning elements and approaches.

    Each subtopic should:
    - Represent a distinct learning component
    - Support skill development
    - Connect to learning objectives
    - Contribute to competency building

    Consider:
    1. What specific skills are taught?
    2. What concepts are introduced?
    3. What practice activities are included?
    4. What assessment methods are used?
    5. What prerequisites are needed?

    Format: Return a JSON array of instructional subtopics that detail learning components.""",

                'details': """For the instructional subtopic '{subtopic}', extract specific learning activities and resources.

    Focus on:
    1. Practice exercises
    2. Examples and illustrations
    3. Assessment criteria
    4. Learning resources
    5. Key definitions
    6. Common mistakes
    7. Success indicators

    Include details that are:
    - Skill-building
    - Practice-oriented
    - Assessment-ready
    - Learning-focused

    Format: Return a JSON array of specific instructional elements and activities."""
            },

            DocumentType.ACADEMIC: {
                'topics': """Analyze this academic document focusing on scholarly arguments and theoretical frameworks.

    Identify major academic components that:
    - Represent complete theoretical concepts
    - Form scholarly arguments
    - Establish key academic positions
    - Connect to existing literature

    Consider:
    1. What are the primary theoretical frameworks?
    2. What scholarly debates are addressed?
    3. What research questions are explored?
    4. What methodological approaches are used?
    5. How do different theoretical elements interact?

    Avoid topics that are:
    - Too specific (individual citations)
    - Too broad (entire fields)
    - Administrative elements
    - Non-scholarly content

    Format: Return a JSON array of primary academic themes or theoretical frameworks.""",

                'subtopics': """For the academic theme '{topic}', identify key theoretical elements and arguments.

    Each subtopic should:
    - Represent a distinct theoretical aspect
    - Support scholarly analysis
    - Connect to literature
    - Contribute to academic discourse

    Consider:
    1. What specific arguments are made?
    2. What evidence is presented?
    3. What theoretical models apply?
    4. What counterarguments exist?
    5. What methodological approaches are used?

    Format: Return a JSON array of academic subtopics that detail theoretical components.""",

                'details': """For the academic subtopic '{subtopic}', extract specific scholarly evidence and arguments.

    Focus on:
    1. Research findings
    2. Theoretical implications
    3. Methodological details
    4. Literature connections
    5. Critical analyses
    6. Supporting evidence
    7. Scholarly debates

    Include details that are:
    - Theoretically relevant
    - Evidence-based
    - Methodologically sound
    - Literature-connected

    Format: Return a JSON array of specific academic elements and arguments."""
            },

            DocumentType.PROCEDURAL: {
                'topics': """Analyze this procedural document focusing on systematic processes and workflows.

    Identify major procedural components that:
    - Represent complete process units
    - Form coherent workflow stages
    - Establish key procedures
    - Connect to overall process flow

    Consider:
    1. What are the primary process phases?
    2. What workflow sequences exist?
    3. What critical paths are defined?
    4. What decision points occur?
    5. How do different process elements connect?

    Avoid topics that are:
    - Too specific (individual actions)
    - Too broad (entire systems)
    - Administrative elements
    - Non-procedural content

    Format: Return a JSON array of primary procedural themes or process phases.""",

                'subtopics': """For the procedural theme '{topic}', identify key process elements and requirements.

    Each subtopic should:
    - Represent a distinct process step
    - Support workflow progression
    - Connect to other steps
    - Contribute to process completion

    Consider:
    1. What specific steps are required?
    2. What inputs are needed?
    3. What outputs are produced?
    4. What conditions apply?
    5. What validations occur?

    Format: Return a JSON array of procedural subtopics that detail process steps.""",

                'details': """For the procedural subtopic '{subtopic}', extract specific step requirements and checks.

    Focus on:
    1. Step-by-step instructions
    2. Input requirements
    3. Quality checks
    4. Decision criteria
    5. Exception handling
    6. Success criteria
    7. Completion indicators

    Include details that are:
    - Action-oriented
    - Sequence-specific
    - Quality-focused
    - Process-critical

    Format: Return a JSON array of specific procedural steps and requirements."""
            },
                
            DocumentType.GENERAL: {
            'topics': """Analyze this document focusing on main conceptual themes and relationships.

    Identify major themes that:
    - Represent complete, independent ideas
    - Form logical groupings of related concepts
    - Support the document's main purpose
    - Connect to other important themes

    Consider:
    1. What are the fundamental ideas being presented?
    2. How do these ideas relate to each other?
    3. What are the key areas of focus?
    4. How is the information structured?

    Avoid topics that are:
    - Too specific (individual examples)
    - Too broad (entire subject areas)
    - Isolated facts without context
    - Purely formatting elements

    Format: Return a JSON array of primary themes or concept areas.""",

                'subtopics': """For the theme '{topic}', identify key supporting concepts and related ideas.

    Each subtopic should:
    - Represent a distinct aspect of the main theme
    - Provide meaningful context
    - Support understanding
    - Connect to the overall narrative

    Consider:
    1. What are the main points about this theme?
    2. What examples illustrate it?
    3. What evidence supports it?
    4. How does it develop through the document?

    Format: Return a JSON array of subtopics that develop this theme.""",

                'details': """For the subtopic '{subtopic}', extract specific supporting information and examples.

    Focus on:
    1. Concrete examples
    2. Supporting evidence
    3. Key definitions
    4. Important relationships
    5. Specific applications
    6. Notable implications
    7. Clarifying points

    Include details that:
    - Illustrate the concept
    - Provide evidence
    - Aid understanding
    - Connect to larger themes

    Format: Return a JSON array of specific supporting details and examples."""
            }
        }
        # Add default prompts for any missing document types
        for doc_type in DocumentType:
            if doc_type not in self.type_specific_prompts:
                self.type_specific_prompts[doc_type] = self.type_specific_prompts[DocumentType.GENERAL]

    async def detect_document_type(self, content: str, request_id: str) -> DocumentType:
        """Use LLM to detect document type with sophisticated analysis."""
        summary_content = content[:self.config['max_summary_length']]
        prompt = f"""You are analyzing a document to determine its primary type and structure. This document requires the most appropriate conceptual organization strategy.

    Key characteristics of each document type:

    TECHNICAL
    - Contains system specifications, API documentation, or implementation details
    - Focuses on HOW things work and technical implementation
    - Uses technical terminology, code examples, or system diagrams
    - Structured around components, modules, or technical processes
    Example indicators: API endpoints, code blocks, system requirements, technical specifications

    SCIENTIFIC
    - Presents research findings, experimental data, or scientific theories
    - Follows scientific method with hypotheses, methods, results
    - Contains statistical analysis or experimental procedures
    - References prior research or scientific literature
    Example indicators: methodology sections, statistical results, citations, experimental procedures

    NARRATIVE
    - Tells a story or presents events in sequence
    - Has character development or plot progression
    - Uses descriptive language and scene-setting
    - Organized chronologically or by story elements
    Example indicators: character descriptions, plot developments, narrative flow, dialogue

    BUSINESS
    - Focuses on business operations, strategy, or market analysis
    - Contains financial data or business metrics
    - Addresses organizational or market challenges
    - Includes business recommendations or action items
    Example indicators: market analysis, financial projections, strategic plans, ROI calculations

    ACADEMIC
    - Centers on scholarly research and theoretical frameworks
    - Engages with academic literature and existing theories
    - Develops theoretical arguments or conceptual models
    - Contributes to academic discourse in a field
    Example indicators: literature reviews, theoretical frameworks, scholarly arguments, academic citations

    LEGAL
    - Focuses on laws, regulations, or legal requirements
    - Contains legal terminology and formal language
    - References statutes, cases, or legal precedents
    - Addresses rights, obligations, or compliance
    Example indicators: legal citations, compliance requirements, jurisdictional references, statutory language

    MEDICAL
    - Centers on clinical care, diagnoses, or treatments
    - Uses medical terminology and protocols
    - Addresses patient care or health outcomes
    - Follows clinical guidelines or standards
    Example indicators: diagnostic criteria, treatment protocols, clinical outcomes, medical terminology

    INSTRUCTIONAL
    - Focuses on teaching or skill development
    - Contains learning objectives and outcomes
    - Includes exercises or practice activities
    - Structured for progressive learning
    Example indicators: learning objectives, practice exercises, assessment criteria, skill development

    ANALYTICAL
    - Presents data analysis or systematic examination
    - Contains trends, patterns, or correlations
    - Uses analytical frameworks or methodologies
    - Focuses on drawing conclusions from data
    Example indicators: data trends, analytical methods, pattern analysis, statistical insights

    PROCEDURAL
    - Provides step-by-step instructions or processes
    - Focuses on HOW to accomplish specific tasks
    - Contains clear sequential steps or workflows
    - Emphasizes proper order and procedures
    Example indicators: numbered steps, workflow diagrams, sequential instructions

    GENERAL
    - Contains broad or mixed content types
    - No strong alignment with other categories
    - Covers multiple topics or approaches
    - Uses general language and structure
    Example indicators: mixed content types, general descriptions, broad overviews, diverse topics

    Key Differentiators:

    1. TECHNICAL vs PROCEDURAL:
    - Technical focuses on system components and how they work
    - Procedural focuses on steps to accomplish tasks

    2. SCIENTIFIC vs ACADEMIC:
    - Scientific focuses on experimental methods and results
    - Academic focuses on theoretical frameworks and scholarly discourse

    3. ANALYTICAL vs SCIENTIFIC:
    - Analytical focuses on data patterns and insights
    - Scientific focuses on experimental validation of hypotheses

    4. INSTRUCTIONAL vs PROCEDURAL:
    - Instructional focuses on learning and skill development
    - Procedural focuses on task completion steps

    5. MEDICAL vs SCIENTIFIC:
    - Medical focuses on clinical care and treatment
    - Scientific focuses on research methodology

    Return ONLY the category name that best matches the document's structure and purpose.

    Document excerpt:
    {summary_content}"""
        try:
            response = await self._retry_generate_completion(
                prompt,
                max_tokens=50,
                request_id=request_id,
                task="detecting_document_type"
            )
            return DocumentType.from_str(response.strip().lower())
        except Exception as e:
            logger.error(f"Error detecting document type: {str(e)}", extra={"request_id": request_id})
            return DocumentType.GENERAL

    @staticmethod
    def _create_node(name: str, importance: str = 'high', emoji: str = "") -> Dict[str, Any]:
        """Create a node dictionary with the given parameters.
        
        Args:
            name (str): The name/text content of the node
            importance (str): The importance level ('high', 'medium', 'low')
            emoji (str): The emoji to represent this node
            
        Returns:
            Dict[str, Any]: Node dictionary with all necessary attributes
        """
        return {
            'name': name,
            'importance': importance.lower(),
            'emoji': emoji,
            'subtopics': [],  # Initialize empty lists for children
            'details': []
        }
        
    def _escape_text(self, text: str) -> str:
        """Replace parentheses with Unicode alternatives and handle other special characters."""
        # Replace regular parentheses in content text with Unicode alternatives
        for original, replacement in self.paren_replacements.items():
            text = text.replace(original, replacement)
            
        # Handle percentages
        text = self.percentage_regex1.sub(r'\1%', text)
        text = self.percentage_regex2.sub('%', text)
        
        # Replace special characters while preserving needed symbols
        text = self.special_chars_regex.sub('', text)
        
        # Clean up multiple backslashes
        text = self.backslash_regex.sub(r'\\', text)
        
        return text

    def _format_node_line(self, node: Dict[str, Any], indent_level: int) -> str:
        """Format a single node in Mermaid syntax."""
        indent = '    ' * indent_level
        
        # For root node, always return just the document emoji
        if indent_level == 1:
            return f"{indent}((Document Overview))"
        
        # Get the node text and escape it
        if 'text' in node:
            # For detail nodes
            importance = node.get('importance', 'low')
            marker = {'high': '♦️', 'medium': '🔸', 'low': '🔹'}[importance]
            text = self._escape_text(node['text'])
            
            # Add citations for details too
            citations = node.get('citations') or []
            if citations:
                citation_list = citations[:2]  # Show only first 2 for details
                citation_text = f" [{', '.join(citation_list)}]"
            else:
                citation_text = ""
            
            return f"{indent}[{marker} {text}{citation_text}]"
        else:
            # For topic and subtopic nodes
            node_name = self._escape_text(node['name'])
            
            # Format citations (limit to 3 for readability)
            citations = node.get('citations') or []
            if citations:
                citation_list = citations[:3]  # Show only first 3
                if len(citations) > 3:
                    citation_text = f" [{', '.join(citation_list)}+{len(citations)-3}]"
                else:
                    citation_text = f" [{', '.join(citation_list)}]"
            else:
                citation_text = ""
            
            # For main topics (level 2)
            if indent_level == 2:
                return f"{indent}(({node_name}{citation_text}))"
            
            # For subtopics (level 3)
            return f"{indent}({node_name}{citation_text})"

    def _add_node_to_mindmap(self, node: Dict[str, Any], mindmap_lines: List[str], indent_level: int) -> None:
        """Recursively add a node and its children to the mindmap."""
        # Add the current node
        node_line = self._format_node_line(node, indent_level)
        mindmap_lines.append(node_line)
        
        # Add all subtopics first
        for subtopic in node.get('subtopics', []):
            self._add_node_to_mindmap(subtopic, mindmap_lines, indent_level + 1)
            
            # Then add details under each subtopic
            for detail in subtopic.get('details', []):
                detail_line = self._format_node_line({
                    'text': detail['text'],
                    'name': detail['text'],
                    'importance': detail['importance'],
                    'citations': detail.get('citations', [])
                }, indent_level + 2)
                mindmap_lines.append(detail_line)

    async def _batch_redundancy_check(self, items, content_type='topic', context_prefix='', batch_size=10):
        """Perform early batch redundancy checks to avoid wasting LLM calls.
        
        Args:
            items: List of items to check (topics or subtopics)
            content_type: Type of content ('topic' or 'subtopic')
            context_prefix: Optional context prefix for subtopics (e.g. parent topic name)
            batch_size: Maximum batch size for parallel processing
            
        Returns:
            List of non-redundant items
        """
        if not items or len(items) <= 1:
            return items
            
        # Process in batches for efficient parallel checking
        start_count = len(items)
        logger.info(f"Starting early redundancy check for {len(items)} {content_type}s...")
        
        # Track items to keep (non-redundant)
        unique_items = []
        seen_names = {}
        
        # First, use simple fuzzy matching to catch obvious duplicates
        for item in items:
            item_name = item['name']
            if not await self.is_similar_to_existing(item_name, seen_names, content_type):
                unique_items.append(item)
                seen_names[item_name] = item
        
        # If we still have lots of items, use more aggressive LLM-based similarity
        if len(unique_items) > 3 and len(unique_items) > len(items) * 0.8:  # Only if enough items and not much reduction yet
            try:
                # Create pairs for comparison
                pairs_to_check = []
                for i in range(len(unique_items)-1):
                    for j in range(i+1, len(unique_items)):
                        pairs_to_check.append((i, j))
                
                # Process in batches with semaphore for rate limiting
                redundant_indices = set()
                semaphore = asyncio.Semaphore(3)  # Limit concurrent LLM calls
                
                async def check_pair(i, j):
                    if i in redundant_indices or j in redundant_indices:
                        return None
                        
                    async with semaphore:
                        try:
                            context1 = context2 = content_type
                            if context_prefix:
                                context1 = context2 = f"{content_type} of {context_prefix}"
                                
                            is_redundant = await self.check_similarity_llm(
                                unique_items[i]['name'],
                                unique_items[j]['name'],
                                context1,
                                context2
                            )
                            
                            if is_redundant:
                                # Keep item with more detailed information
                                i_detail = len(unique_items[i].get('name', ''))
                                j_detail = len(unique_items[j].get('name', ''))
                                return (j, i) if i_detail > j_detail else (i, j)
                        except Exception as e:
                            logger.warning(f"Early redundancy check failed: {str(e)}")
                            
                    return None
                    
                # Process batches to maintain parallelism
                for batch_idx in range(0, len(pairs_to_check), batch_size):
                    batch = pairs_to_check[batch_idx:batch_idx + batch_size]
                    results = await asyncio.gather(*(check_pair(i, j) for i, j in batch))
                    
                    # Process results
                    for result in results:
                        if result:
                            redundant_idx, keep_idx = result
                            if redundant_idx not in redundant_indices:
                                redundant_indices.add(redundant_idx)
                                logger.info(f"Found redundant {content_type}: '{unique_items[redundant_idx]['name']}' similar to '{unique_items[keep_idx]['name']}'")
                
                # Filter out redundant items
                unique_items = [item for i, item in enumerate(unique_items) if i not in redundant_indices]
            except Exception as e:
                logger.error(f"Error in aggressive redundancy check: {str(e)}")
        
        reduction = start_count - len(unique_items)
        if reduction > 0:
            logger.info(f"Early redundancy check removed {reduction} redundant {content_type}s ({reduction/start_count*100:.1f}%)")
        
        return unique_items

    async def is_similar_to_existing(self, name: str, existing_names: Union[dict, set], content_type: str = 'topic') -> bool:
        """Check if name is similar to any existing names using stricter fuzzy matching thresholds.
        
        Args:
            name: Text to check for similarity
            existing_names: Dictionary or set of existing names to compare against
            content_type: Type of content being compared ('topic', 'subtopic', or 'detail')
            
        Returns:
            bool: True if similar content exists, False otherwise
        """
        # Lower thresholds to catch more duplicates
        base_threshold = {
            'topic': 75,      # Lower from 85 to catch more duplicates
            'subtopic': 70,   # Lower from 80 to catch more duplicates
            'detail': 65      # Lower from 75 to catch more duplicates
        }[content_type]
        
        # Get threshold for this content type
        threshold = base_threshold
        
        # Adjust threshold based on text length - be more lenient with longer texts
        if len(name) < 10:
            threshold = min(threshold + 10, 95)  # Stricter for very short texts
        elif len(name) > 100:
            threshold = max(threshold - 15, 55)  # More lenient for long texts
        
        # Make adjustments for content types to catch more duplicates
        if content_type == 'subtopic':
            threshold = max(threshold - 10, 60)  # Lower threshold to catch more duplicates
        elif content_type == 'detail':
            threshold = max(threshold - 10, 55)  # Lower threshold to catch more duplicates
        
        # Clean and normalize input text
        name = re.sub(r'\s+', ' ', name.lower().strip())
        name = re.sub(r'[^\w\s]', '', name)
        
        # Special handling for numbered items
        numbered_pattern = self.numbered_pattern
        name_without_number = numbered_pattern.sub(r'\1', name)
        
        # Handle both dict and set inputs
        existing_items = existing_names.keys() if isinstance(existing_names, dict) else existing_names
        
        for existing_name in existing_items:
            # Skip if lengths are vastly different
            existing_clean = re.sub(r'\s+', ' ', str(existing_name).lower().strip())
            existing_clean = re.sub(r'[^\w\s]', '', existing_clean)
            
            if abs(len(name) - len(existing_clean)) > len(name) * 0.7:  # Increased from 0.5
                continue
            
            # Calculate multiple similarity metrics
            basic_ratio = fuzz.ratio(name, existing_clean)
            partial_ratio = fuzz.partial_ratio(name, existing_clean)
            token_sort_ratio = fuzz.token_sort_ratio(name, existing_clean)
            token_set_ratio = fuzz.token_set_ratio(name, existing_clean)
            
            # For numbered items, compare without numbers
            existing_without_number = numbered_pattern.sub(r'\1', existing_clean)
            if name_without_number != name or existing_without_number != existing_clean:
                number_ratio = fuzz.ratio(name_without_number, existing_without_number)
                basic_ratio = max(basic_ratio, number_ratio)
            
            # Weight ratios differently based on content type - higher weights to catch more duplicates
            if content_type == 'topic':
                final_ratio = max(
                    basic_ratio,
                    token_sort_ratio * 1.1,  # Increased weight
                    token_set_ratio * 1.0    # Increased weight
                )
            elif content_type == 'subtopic':
                final_ratio = max(
                    basic_ratio,
                    partial_ratio * 1.0,     # Increased weight
                    token_sort_ratio * 0.95, # Increased weight
                    token_set_ratio * 0.9    # Increased weight
                )
            else:  # details
                final_ratio = max(
                    basic_ratio * 0.95,
                    partial_ratio * 0.9,
                    token_sort_ratio * 0.85,
                    token_set_ratio * 0.8
                )
            
            # Increase ratio for shorter texts to catch more duplicates
            if len(name) < 30:
                final_ratio *= 1.1  # Boost ratio for short texts
            
            # Check against adjusted threshold
            if final_ratio > threshold:
                logger.debug(
                    f"Found similar {content_type}:\n"
                    f"New: '{name}'\n"
                    f"Existing: '{existing_clean}'\n"
                    f"Ratio: {final_ratio:.2f} (threshold: {threshold})"
                )
                return True
        
        return False

    async def check_similarity_llm(self, text1: str, text2: str, context1: str, context2: str) -> bool:
        """LLM-based similarity check between two text elements with stricter criteria."""
        prompt = f"""Compare these two text elements and determine if they express similar core information, making one redundant in the mindmap.

        Text 1 (from {context1}):
        "{text1}"

        Text 2 (from {context2}):
        "{text2}"

        A text is REDUNDANT if ANY of these apply:
        1. It conveys the same primary information or main point as the other text
        2. It covers the same concept from a similar angle or perspective
        3. The semantic meaning overlaps significantly with the other text
        4. A reader would find having both entries repetitive or confusing
        5. One could be safely removed without losing important information

        A text is DISTINCT ONLY if ALL of these apply:
        1. It focuses on a clearly different aspect or perspective
        2. It provides substantial unique information not present in the other
        3. It serves a fundamentally different purpose in context
        4. Both entries together provide significantly more value than either alone
        5. The conceptual overlap is minimal

        When in doubt, mark as REDUNDANT to create a cleaner, more focused mindmap.

        Respond with EXACTLY one of these:
        REDUNDANT (overlapping information about X)
        DISTINCT (different aspect: X)

        where X is a very brief explanation."""

        try:
            response = await self._retry_generate_completion(
                prompt,
                max_tokens=50,
                request_id='similarity_check',
                task="checking_content_similarity"
            )
            
            # Consider anything not explicitly marked as DISTINCT to be REDUNDANT
            result = not response.strip().upper().startswith("DISTINCT")
            
            logger.info(
                f"\n{colored('🔍 Content comparison:', 'cyan')}\n"
                f"Text 1: {colored(text1[:100] + '...', 'yellow')}\n"
                f"Text 2: {colored(text2[:100] + '...', 'yellow')}\n"
                f"Result: {colored('REDUNDANT' if result else 'DISTINCT', 'green')}\n"
                f"LLM Response: {colored(response.strip(), 'white')}"
            )
            return result
        except Exception as e:
            logger.error(f"Error in LLM similarity check: {str(e)}")
            # Default to considering items similar if the check fails
            return True

    async def _process_content_batch(self, content_items: List[ContentItem]) -> Set[int]:
        """Process a batch of content items to identify redundant content with parallel processing.
        
        Args:
            content_items: List of ContentItem objects to process
            
        Returns:
            Set of indices identifying redundant items that should be removed
        """
        redundant_indices = set()
        comparison_tasks = []
        comparison_counter = 0
        
        # Create cache of preprocessed texts to avoid recomputing
        processed_texts = {}
        for idx, item in enumerate(content_items):
            # Normalize text for comparison
            text = re.sub(r'\s+', ' ', item.text.lower().strip())
            text = re.sub(r'[^\w\s]', '', text)
            processed_texts[idx] = text
        
        # Limit concurrent API calls
        semaphore = asyncio.Semaphore(10)  # Adjust based on API limits
        
        # Prepare all comparison tasks first
        for i in range(len(content_items)):
            item1 = content_items[i]
            text1 = processed_texts[i]
            
            for j in range(i + 1, len(content_items)):
                item2 = content_items[j]
                text2 = processed_texts[j]
                
                # Quick exact text match check - avoid API call
                if text1 == text2:
                    # Log this immediately since we're not using the API
                    comparison_counter += 1
                    logger.info(f"\nMaking comparison {comparison_counter}... (exact match found)")
                    
                    # Add to candidates for removal with perfect confidence
                    confidence = 1.0
                    
                    # Determine which to keep based on importance and path
                    item1_importance = self._get_importance_value(item1.importance)
                    item2_importance = self._get_importance_value(item2.importance)
                    
                    if ((item2_importance > item1_importance) or
                        (item2_importance == item1_importance and 
                        len(item2.path) < len(item1.path))):
                        redundant_indices.add(i)
                        logger.info(
                            f"\n{colored('🔄 Removing redundant content:', 'yellow')}\n"
                            f"Keeping: {colored(item2.text[:100] + '...', 'green')}\n"
                            f"Removing: {colored(item1.text[:100] + '...', 'red')}\n"
                            f"Confidence: {colored(f'{confidence:.2f}', 'cyan')}"
                        )
                        break  # Stop processing this item if we're removing it
                    else:
                        redundant_indices.add(j)
                        logger.info(
                            f"\n{colored('🔄 Removing redundant content:', 'yellow')}\n"
                            f"Keeping: {colored(item1.text[:100] + '...', 'green')}\n"
                            f"Removing: {colored(item2.text[:100] + '...', 'red')}\n"
                            f"Confidence: {colored(f'{confidence:.2f}', 'cyan')}"
                        )
                    continue
                
                # Skip if lengths are very different
                len_ratio = min(len(text1), len(text2)) / max(len(text1), len(text2))
                if len_ratio < 0.5:  # Texts differ in length by more than 50%
                    continue
                
                # Skip if one item is already marked for removal
                if i in redundant_indices or j in redundant_indices:
                    continue
                    
                # Add to parallel comparison tasks
                async def check_similarity_with_context(idx1, idx2):
                    """Run similarity check with semaphore and return context for logging"""
                    nonlocal comparison_counter
                    
                    # Atomically increment comparison counter
                    comparison_id = comparison_counter = comparison_counter + 1
                    
                    # Log start of comparison
                    logger.info(f"\nMaking comparison {comparison_id}...")
                    
                    # Run the LLM comparison with rate limiting
                    async with semaphore:
                        try:
                            is_redundant = await self.check_similarity_llm(
                                content_items[idx1].text, 
                                content_items[idx2].text,
                                content_items[idx1].path_str, 
                                content_items[idx2].path_str
                            )
                            
                            # Calculate confidence if redundant
                            confidence = 0.0
                            if is_redundant:
                                # Calculate fuzzy string similarity metrics
                                fuzz_ratio = fuzz.ratio(processed_texts[idx1], processed_texts[idx2]) / 100.0
                                token_sort_ratio = fuzz.token_sort_ratio(processed_texts[idx1], processed_texts[idx2]) / 100.0
                                token_set_ratio = fuzz.token_set_ratio(processed_texts[idx1], processed_texts[idx2]) / 100.0
                                
                                # Combine metrics for overall confidence
                                confidence = (fuzz_ratio * 0.4 + 
                                            token_sort_ratio * 0.3 + 
                                            token_set_ratio * 0.3)
                            
                            return {
                                'comparison_id': comparison_id,
                                'is_redundant': is_redundant,
                                'confidence': confidence,
                                'idx1': idx1,
                                'idx2': idx2,
                                'success': True
                            }
                        except Exception as e:
                            logger.error(f"Error in comparison {comparison_id}: {str(e)}")
                            return {
                                'comparison_id': comparison_id,
                                'success': False,
                                'error': str(e),
                                'idx1': idx1,
                                'idx2': idx2
                            }
                
                # Add task to our list
                comparison_tasks.append(check_similarity_with_context(i, j))
        
        # Run all comparison tasks in parallel
        if comparison_tasks:
            logger.info(f"Starting {len(comparison_tasks)} parallel similarity comparisons")
            results = await asyncio.gather(*comparison_tasks)
            
            # Process results
            # First, collect all redundancies with confidence scores
            redundancy_candidates = []
            for result in results:
                if not result['success']:
                    continue
                    
                if result['is_redundant'] and result['confidence'] > 0.8:  # High confidence threshold
                    redundancy_candidates.append(result)
            
            # Sort by confidence (highest first)
            redundancy_candidates.sort(key=lambda x: x['confidence'], reverse=True)
            
            # Process each redundancy candidate
            for result in redundancy_candidates:
                i, j = result['idx1'], result['idx2']
                
                # Skip if either item is already marked for removal
                if i in redundant_indices or j in redundant_indices:
                    continue
                    
                # Determine which to keep based on importance and path
                item1 = content_items[i]
                item2 = content_items[j]
                item1_importance = self._get_importance_value(item1.importance)
                item2_importance = self._get_importance_value(item2.importance)
                
                if ((item2_importance > item1_importance) or
                    (item2_importance == item1_importance and 
                    len(item2.path) < len(item1.path))):
                    redundant_indices.add(i)
                    confidence_val = result["confidence"]
                    logger.info(
                        f"\n{colored('🔄 Removing redundant content:', 'yellow')}\n"
                        f"Keeping: {colored(item2.text[:100] + '...', 'green')}\n"
                        f"Removing: {colored(item1.text[:100] + '...', 'red')}\n"
                        f"Confidence: {colored(f'{confidence_val:.2f}', 'cyan')}"
                    )
                else:
                    redundant_indices.add(j)
                    confidence_val = result["confidence"]
                    logger.info(
                        f"\n{colored('🔄 Removing redundant content:', 'yellow')}\n"
                        f"Keeping: {colored(item1.text[:100] + '...', 'green')}\n"
                        f"Removing: {colored(item2.text[:100] + '...', 'red')}\n"
                        f"Confidence: {colored(f'{confidence_val:.2f}', 'cyan')}"
                    )
        
        logger.info(f"\nBatch processing complete. Made {comparison_counter} comparisons.")
        return redundant_indices                

    def _get_importance_value(self, importance: str) -> int:
        """Convert importance string to numeric value for comparison."""
        return {'high': 3, 'medium': 2, 'low': 1}.get(importance.lower(), 0)

    def _extract_content_for_filtering(self, node: Dict[str, Any], current_path: List[str]) -> None:
        """Extract all content items with their full paths for filtering."""
        if not node:
            return

        # Process current node (including root node)
        if 'name' in node:
            current_node_path = current_path + ([node['name']] if node['name'] else [])
            
            # Add the node itself unless it's the root "Document Mindmap" node
            if len(current_path) > 0 or (node['name'] and node['name'] != 'Document Mindmap'):
                # Determine node type based on path depth
                node_type = 'root' if len(current_path) == 0 else 'topic' if len(current_path) == 1 else 'subtopic'
                
                content_item = ContentItem(
                    text=node['name'],
                    path=current_node_path,
                    node_type=node_type,
                    importance=node.get('importance', 'medium')
                )
                
                # Only add if path is non-empty
                if current_node_path:
                    path_tuple = tuple(current_node_path)
                    self.all_content.append(content_item)
                    self.content_by_path[path_tuple] = content_item

            # Process details at current level
            for detail in node.get('details', []):
                if isinstance(detail, dict) and 'text' in detail:
                    # Only add details if we have a valid parent path
                    if current_node_path:
                        detail_path = current_node_path + ['detail']
                        detail_item = ContentItem(
                            text=detail['text'],
                            path=detail_path,
                            node_type='detail',
                            importance=detail.get('importance', 'medium')
                        )
                        detail_path_tuple = tuple(detail_path)
                        self.all_content.append(detail_item)
                        self.content_by_path[detail_path_tuple] = detail_item

            # Process subtopics
            for subtopic in node.get('subtopics', []):
                self._extract_content_for_filtering(subtopic, current_node_path)
        else:
            # If no name but has subtopics, process them with current path
            for subtopic in node.get('subtopics', []):
                self._extract_content_for_filtering(subtopic, current_path)

    async def final_pass_filter_for_duplicative_content(self, mindmap_data: Dict[str, Any], batch_size: int = 50) -> Dict[str, Any]:
        """Enhanced filter for duplicative content with more aggressive detection and safer rebuilding."""
        USE_VERBOSE = True  # Toggle for verbose logging
        
        def vlog(message: str, color: str = 'white', bold: bool = False):
            """Helper for verbose logging"""
            if USE_VERBOSE:
                attrs = ['bold'] if bold else []
                logger.info(colored(message, color, attrs=attrs))
                
        vlog("\n" + "="*80, 'cyan', True)
        vlog("🔍 STARTING ENHANCED DUPLICATE CONTENT FILTER PASS", 'cyan', True)
        vlog("="*80 + "\n", 'cyan', True)
        
        # Debug input structure
        vlog("\n📥 INPUT MINDMAP STRUCTURE:", 'blue', True)
        vlog(f"Mindmap keys: {list(mindmap_data.keys())}")
        if 'central_theme' in mindmap_data:
            central_theme = mindmap_data['central_theme']
            vlog(f"Central theme keys: {list(central_theme.keys())}")
            vlog(f"Number of initial topics: {len(central_theme.get('subtopics', []))}")
            topics = central_theme.get('subtopics', [])
            vlog("\nInitial topic names:")
            for i, topic in enumerate(topics, 1):
                vlog(f"{i}. {topic.get('name', 'UNNAMED')} ({len(topic.get('subtopics', []))} subtopics)")
        else:
            vlog("WARNING: No 'central_theme' found in mindmap!", 'red', True)
            return mindmap_data  # Return original if no central theme
        
        # Initialize instance variables for content tracking
        vlog("\n🔄 Initializing content tracking...", 'yellow')
        self.all_content = []
        self.content_by_path = {}
        
        # Extract all content items for filtering
        vlog("\n📋 Starting content extraction from central theme...", 'blue', True)
        try:
            # Fixed extraction method - should properly extract all content
            self._extract_content_for_filtering(mindmap_data.get('central_theme', {}), [])
            
            # Verify extraction worked
            vlog(f"✅ Successfully extracted {len(self.all_content)} total content items:", 'green')
            content_types = {}
            for item in self.all_content:
                content_types[item.node_type] = content_types.get(item.node_type, 0) + 1
            for node_type, count in content_types.items():
                vlog(f"  - {node_type}: {count} items", 'green')
        except Exception as e:
            vlog(f"❌ Error during content extraction: {str(e)}", 'red', True)
            return mindmap_data  # Return original data on error
        
        # Check if we have any content to filter
        initial_count = len(self.all_content)
        if initial_count == 0:
            vlog("❌ No content extracted - mindmap appears empty", 'red', True)
            return mindmap_data  # Return original data
        
        # Process content in batches for memory efficiency
        vlog("\n🔄 Processing content in batches...", 'yellow', True)
        content_batches = [
            self.all_content[i:i+batch_size] 
            for i in range(0, len(self.all_content), batch_size)
        ]
        
        all_to_remove = set()
        
        for batch_idx, batch in enumerate(content_batches):
            vlog(f"Processing batch {batch_idx+1}/{len(content_batches)} ({len(batch)} items)...", 'yellow')
            batch_to_remove = await self._process_content_batch(batch)
            
            # Adjust indices to global positions
            global_indices = {batch_idx * batch_size + i for i in batch_to_remove}
            all_to_remove.update(global_indices)
            
            vlog(f"Batch {batch_idx+1} complete: identified {len(batch_to_remove)} redundant items", 'green')
        
        # Get indices of items to keep
        keep_indices = set(range(len(self.all_content))) - all_to_remove
        
        # Convert to set of paths to keep
        vlog("\n🔄 Converting to paths for rebuild...", 'blue')
        keep_paths = {tuple(self.all_content[i].path) for i in keep_indices}
        vlog(f"Keeping {len(keep_paths)} unique paths", 'blue')
        
        # Safety check - add at least one path if none remain
        if not keep_paths and len(self.all_content) > 0:
            vlog("⚠️ No paths remained after filtering! Adding at least one path", 'yellow', True)
            first_item = self.all_content[0]
            keep_paths.add(tuple(first_item.path))
        
        # Rebuild the mindmap with only the paths to keep
        vlog("\n🏗️ Rebuilding mindmap...", 'yellow', True)
        
        def rebuild_mindmap(node: Dict[str, Any], current_path: List[str]) -> Optional[Dict[str, Any]]:
            """Recursively rebuild mindmap keeping only non-redundant content."""
            # Add special case for root node
            if not node:
                return None
                
            # For root node, always keep it and process its subtopics
            if not current_path:
                result = copy.deepcopy(node)
                result['subtopics'] = []
                
                # Process main topics
                for topic in node.get('subtopics', []):
                    if topic.get('name'):
                        topic_path = [topic['name']]
                        rebuilt_topic = rebuild_mindmap(topic, topic_path)
                        if rebuilt_topic:
                            result['subtopics'].append(rebuilt_topic)
                
                # Always return root node even if no subtopics remain
                return result
                    
            # For non-root nodes, check if current path should be kept
            path_tuple = tuple(current_path)
            if path_tuple not in keep_paths:
                return None
                
            result = copy.deepcopy(node)
            result['subtopics'] = []
            
            # Process subtopics
            for subtopic in node.get('subtopics', []):
                if subtopic.get('name'):
                    subtopic_path = current_path + [subtopic['name']]
                    rebuilt_subtopic = rebuild_mindmap(subtopic, subtopic_path)
                    if rebuilt_subtopic:
                        result['subtopics'].append(rebuilt_subtopic)
            
            # Filter details
            if 'details' in result:
                filtered_details = []
                for detail in result['details']:
                    if isinstance(detail, dict) and 'text' in detail:
                        detail_path = current_path + ['detail']
                        if tuple(detail_path) in keep_paths:
                            filtered_details.append(detail)
                result['details'] = filtered_details
            
            # Only return node if it has content
            if result['subtopics'] or result.get('details'):
                return result
            return None
        
        # Rebuild mindmap without redundant content
        filtered_data = rebuild_mindmap(mindmap_data.get('central_theme', {}), [])
        
        # Safety check - add the original data's central theme if rebuild failed completely
        if not filtered_data:
            vlog("❌ Filtering removed all content - using original mindmap", 'red', True)
            return mindmap_data
            
        # Another safety check - ensure we have subtopics
        if not filtered_data.get('subtopics'):
            vlog("❌ Filtering removed all subtopics - using original mindmap", 'red', True) 
            return mindmap_data
        
        # Put the central theme back into a complete mindmap structure
        result_mindmap = {'central_theme': filtered_data}
        
        # Calculate and log statistics
        removed_count = initial_count - len(keep_indices)
        reduction_percentage = (removed_count / initial_count * 100) if initial_count > 0 else 0
        
        vlog(
            f"\n{colored('✅ Duplicate content filtering complete', 'green', attrs=['bold'])}\n"
            f"Original items: {colored(str(initial_count), 'yellow')}\n"
            f"Filtered items: {colored(str(len(keep_indices)), 'yellow')}\n"
            f"Removed {colored(str(removed_count), 'red')} duplicate items "
            f"({colored(f'{reduction_percentage:.1f}%', 'red')} reduction)"
        )
        
        return result_mindmap

    async def generate_mindmap(self, document_content: str, request_id: str, max_topics: int = 8) -> str:
        """Generate NotebookLM-style mindmap using segment-based topic discovery.
        
        Args:
            document_content (str): The document content to analyze
            request_id (str): Unique identifier for request tracking
            max_topics (int): Maximum number of topics to generate (default: 8)
            
        Returns:
            str: Complete Mermaid mindmap syntax with citations
            
        Raises:
            MindMapGenerationError: If mindmap generation fails
        """
        try:
            logger.info(f"Starting NotebookLM-style mindmap generation (max_topics={max_topics})...", extra={"request_id": request_id})
            
            # Step 1: Segment the document and ingest into Weaviate
            document_name = f"doc_{request_id}"  # Use a unique name for the document
            segment_processor = SegmentProcessor()
            segment_processor.process(document_content)
            segments_for_ingestion = [
                {"id": seg.segment_id, "text": seg.text} 
                for seg in segment_processor.get_all_segments()
            ]
            self.weaviate_service.ingest_segments(segments_for_ingestion, document_name)

            # Step 2: Find semantic clusters using Weaviate (use max_topics parameter)
            clusters = self.weaviate_service.find_semantic_clusters(document_name, num_topics=max_topics)

            if not clusters:
                logger.warning("No semantic clusters found. Falling back to full-document extraction.")
                main_topics = await self._extract_main_topics(document_content, type_prompts['topics'], request_id)
            else:
                logger.info(f"Found {len(clusters)} semantic topic clusters.")
                # Step 3: Generate main topics from clusters
                # Note: _generate_topics_from_clusters needs to be adapted to handle the new cluster format
                main_topics = await self._generate_topics_from_clusters(
                    clusters, 
                    request_id
                )
            
            logger.info("Starting mindmap generation process...", extra={"request_id": request_id})
            
            # Initialize content caching and call counts for logging
            self._content_cache = {}
            self._unique_concepts = {'topics': set(), 'subtopics': set(), 'details': set()}
            self._llm_calls = {
                'topics': 0,
                'subtopics': 0,
                'details': 0,
                'total_topics': 0,
                'processed_topics': 0,
                'total_subtopics': 0,
                'processed_subtopics': 0,
                'total_details': 0
            }
            
            # Set strict LLM call limits with increased bounds
            max_llm_calls = {
                'topics': 30,      # 더 많은 토픽 생성
                'subtopics': 50,   # 더 많은 서브토픽 생성
                'details': 80      # 더 많은 디테일 생성 (3단계 구조 보장)
            }

            # Set minimum content requirements with better distribution
            min_requirements = {
                'topics': 4,       # Minimum topics to process
                'subtopics_per_topic': 2,  # Minimum subtopics per topic
                'details_per_subtopic': 3   # Minimum details per subtopic
            }
            
            # Initialize completion tracking
            completion_stats = {
                'processed_topics': 0,
                'total_topics': 0,
                'processed_subtopics': 0,
                'total_subtopics': 0,
                'total_details': 0
            }
            
            # Calculate document word count and set limit 
            doc_words = len(document_content.split())
            word_limit = min(doc_words * 0.9, 8000)  # Cap at 8000 words
            current_word_count = 0
            
            logger.info(f"Document size: {doc_words} words. Generation limit: {word_limit:,} words", extra={"request_id": request_id})

            # Helper function to check if we have enough content with stricter enforcement
            def has_sufficient_content():
                if completion_stats['processed_topics'] < min_requirements['topics']:
                    return False
                if completion_stats['total_topics'] > 0:
                    avg_subtopics_per_topic = (completion_stats['processed_subtopics'] / 
                                            completion_stats['processed_topics'])
                    if avg_subtopics_per_topic < min_requirements['subtopics_per_topic']:
                        return False
                # Process at least 75% of available topics before considering early stop
                if completion_stats['total_topics'] > 0:
                    topics_processed_ratio = completion_stats['processed_topics'] / completion_stats['total_topics']
                    if topics_processed_ratio < 0.75:
                        return False
                return True
                                        
            # Step 4: Generate topics from clusters using LLM
            logger.info("Generating topics from segment clusters...")
            main_topics = await self._generate_topics_from_clusters(
                clusters,
                request_id
            )
            
            if not main_topics:
                raise MindMapGenerationError("No topics could be generated from clusters")
            
            completion_stats['total_topics'] = len(main_topics)
            logger.info(f"Generated {len(main_topics)} topics from clusters")

            # Process topics with completion tracking
            processed_topics = {}
            # NEW: Track already processed topics for redundancy checking
            processed_topic_names = {}
            
            for topic_idx, topic in enumerate(main_topics, 1):
                # Don't stop early if we haven't processed minimum topics
                should_continue = (topic_idx <= min_requirements['topics'] or 
                                not has_sufficient_content() or
                                completion_stats['processed_topics'] < len(main_topics) * 0.75)
                                
                if not should_continue:
                    logger.info(f"Stopping after processing {topic_idx} topics - sufficient content gathered")
                    break
        
                topic_name = topic['name']
                
                # NEW: Check if this topic is redundant with already processed topics
                is_redundant = False
                for processed_name in processed_topic_names:
                    if await self.is_similar_to_existing(topic_name, {processed_name: True}, 'topic'):
                        logger.info(f"Skipping redundant topic: '{topic_name}' (similar to '{processed_name}')")
                        is_redundant = True
                        break
                        
                if is_redundant:
                    continue
                    
                # Track this topic for future redundancy checks
                processed_topic_names[topic_name] = True
                
                # Enhanced word limit check with buffer
                if current_word_count > word_limit * 0.95:  # Increased from 0.9 to ensure more completion
                    logger.info(f"Approaching word limit at {current_word_count}/{word_limit:.0f} words")
                    break

                logger.info(f"Processing topic {topic_idx}/{len(main_topics)}: '{topic_name}' "
                        f"(Words: {current_word_count}/{word_limit:.0f})",
                        extra={"request_id": request_id})
                
                # Track unique concepts with validation
                if topic_name not in self._unique_concepts['topics']:
                    self._unique_concepts['topics'].add(topic_name)
                    completion_stats['processed_topics'] += 1

                try:
                    # Generate subtopics from topic's segments
                    topic_segments = segment_processor.get_segments_for_cluster({
                        'segment_ids': topic.get('citations', [])  # citations는 이미 segment_ids 리스트
                    })
                    
                    logger.info(f"[DEBUG] Topic '{topic_name}' has {len(topic.get('citations', []))} citations, got {len(topic_segments)} segments")
                    
                    if self._llm_calls['subtopics'] < max_llm_calls['subtopics']:
                        subtopics = await self._extract_subtopics_from_segments(
                            topic, topic_segments, request_id
                        )
                        logger.info(f"[DEBUG] Extracted {len(subtopics)} subtopics for '{topic_name}'")
                        
                        # Perform early redundancy check on subtopics
                        subtopics = await self._batch_redundancy_check(
                            subtopics, 'subtopic', context_prefix=topic_name
                        )
                        
                        self._llm_calls['subtopics'] += 1
                    else:
                        logger.info("Reached subtopic LLM call limit")
                        break
                            
                    topic['subtopics'] = []
                    
                    logger.info(f"[DEBUG] After redundancy check: {len(subtopics)} subtopics remain for '{topic_name}'")
                    
                    if subtopics:
                        completion_stats['total_subtopics'] += len(subtopics)
                        processed_subtopics = {}
                        
                        # NEW: Track already processed subtopics for redundancy checking
                        processed_subtopic_names = {}
                        
                        # Process each subtopic with completion tracking
                        for subtopic_idx, subtopic in enumerate(subtopics, 1):
                            if self._llm_calls['details'] >= max_llm_calls['details']:
                                logger.info("Reached maximum LLM calls for detail extraction")
                                break
                                
                            subtopic_name = subtopic['name']
                            
                            # NEW: Check redundancy with already processed subtopics
                            is_redundant = False
                            for processed_name in processed_subtopic_names:
                                if await self.is_similar_to_existing(subtopic_name, {processed_name: True}, 'subtopic'):
                                    logger.info(f"Skipping redundant subtopic: '{subtopic_name}' (similar to '{processed_name}')")
                                    is_redundant = True
                                    break
                                    
                            if is_redundant:
                                continue
                                
                            # Track this subtopic for future redundancy checks
                            processed_subtopic_names[subtopic_name] = True
                            
                            # Track word count for subtopics
                            subtopic_words = len(subtopic_name.split())
                            if current_word_count + subtopic_words > word_limit * 0.95:
                                logger.info("Approaching word limit during subtopic processing")
                                break
                                
                            current_word_count += subtopic_words
                            
                            # Track unique subtopics
                            self._unique_concepts['subtopics'].add(subtopic_name)
                            completion_stats['processed_subtopics'] += 1

                            try:
                                # Extract details from subtopic's segments
                                subtopic_segments = segment_processor.get_segments_for_cluster({
                                    'segment_ids': subtopic.get('citations', [])  # citations는 이미 segment_ids 리스트
                                })
                                
                                if self._llm_calls['details'] < max_llm_calls['details']:
                                    details = await self._extract_details_from_segments(
                                        subtopic, subtopic_segments, request_id
                                    )
                                    self._llm_calls['details'] += 1
                                    logger.info(f"✅ Generated {len(details)} details for subtopic '{subtopic_name}'")
                                else:
                                    details = []
                                    logger.warning(f"⚠️ Skipped details for '{subtopic_name}' - reached LLM call limit")
                                
                                subtopic['details'] = []
                                
                                if details:
                                    completion_stats['total_details'] += len(details)
                                    
                                    # Process details with completion tracking
                                    seen_details = {}
                                    unique_details = []
                                    
                                    for detail in details:
                                        detail_words = len(detail['text'].split())
                                        
                                        if current_word_count + detail_words > word_limit * 0.98:
                                            logger.info("Approaching word limit during detail processing")
                                            break
                                            
                                        if not await self.is_similar_to_existing(detail['text'], seen_details, 'detail'):
                                            current_word_count += detail_words
                                            seen_details[detail['text']] = True
                                            unique_details.append(detail)
                                            self._unique_concepts['details'].add(detail['text'])
                                    
                                    subtopic['details'] = unique_details
                                
                                processed_subtopics[subtopic_name] = subtopic
                                
                            except Exception as e:
                                logger.error(f"Error processing details for subtopic '{subtopic_name}': {str(e)}")
                                processed_subtopics[subtopic_name] = subtopic
                                continue
                        
                        topic['subtopics'] = list(processed_subtopics.values())
                        logger.info(f"[DEBUG] Final: Topic '{topic_name}' has {len(topic['subtopics'])} subtopics")
                    else:
                        logger.warning(f"[DEBUG] No subtopics for '{topic_name}' after processing")
                    
                    processed_topics[topic_name] = topic
                        
                except Exception as e:
                    logger.error(f"Error processing topic '{topic_name}': {str(e)}")
                    processed_topics[topic_name] = topic
                    continue
                
                # Log completion status
                logger.info(
                    f"Completion status: "
                    f"Topics: {completion_stats['processed_topics']}/{completion_stats['total_topics']}, "
                    f"Subtopics: {completion_stats['processed_subtopics']}/{completion_stats['total_subtopics']}, "
                    f"Details: {completion_stats['total_details']}"
                )
            
            if not processed_topics:
                raise MindMapGenerationError("No topics could be processed")
            
            # Enhanced final statistics logging
            final_stats = {
                'words_generated': current_word_count,
                'word_limit': word_limit,
                'completion_percentage': (current_word_count/word_limit)*100,
                'topics_processed': completion_stats['processed_topics'],
                'total_topics': completion_stats['total_topics'],
                'unique_topics': len(self._unique_concepts['topics']),
                'unique_subtopics': len(self._unique_concepts['subtopics']),
                'unique_details': len(self._unique_concepts['details']),
                'llm_calls': self._llm_calls,
                'early_stopping': has_sufficient_content()
            }
            
            logger.info(
                f"Mindmap generation completed:"
                f"\n- Words generated: {final_stats['words_generated']}/{final_stats['word_limit']:.0f} "
                f"({final_stats['completion_percentage']:.1f}%)"
                f"\n- Topics processed: {final_stats['topics_processed']}/{final_stats['total_topics']}"
                f"\n- Unique topics: {final_stats['unique_topics']}"
                f"\n- Unique subtopics: {final_stats['unique_subtopics']}"
                f"\n- Unique details: {final_stats['unique_details']}"
                f"\n- LLM calls: topics={self._llm_calls['topics']}, "
                f"subtopics={self._llm_calls.get('subtopics', 0)}, "
                f"details={self._llm_calls.get('details', 0)}"
                f"\n- Early stopping: {final_stats['early_stopping']}",
                extra={"request_id": request_id}
            )
            
            logger.info("Starting initial mindmap generation...")
            concepts = {
                'central_theme': self._create_node('Document Mindmap', 'high')
            }
            concepts['central_theme']['subtopics'] = list(processed_topics.values())
                
            logger.info("Starting duplicate content filtering...")
            try:
                # Explicitly await the filtering
                filtered_concepts = await self.final_pass_filter_for_duplicative_content(
                    concepts,
                    batch_size=25
                )
                
                if not filtered_concepts:
                    logger.warning("Filtering removed all content, using original mindmap")
                    filtered_concepts = concepts
                    
                # NEW: Perform reality check against original document
                logger.info("Starting reality check to filter confabulations...")
                verified_concepts = await self.verify_mindmap_against_source(
                    filtered_concepts, 
                    document_content
                )
                
                if not verified_concepts or not verified_concepts.get('central_theme', {}).get('subtopics'):
                    logger.warning("Reality check removed all content, using filtered mindmap with warning")
                    verified_concepts = filtered_concepts
                
                logger.info("Successfully verified against source document, generating final mindmap...")
                # Store concepts for interactive HTML generation
                self._last_concepts = verified_concepts
                return self._generate_mermaid_mindmap(verified_concepts)
                
            except Exception as e:
                logger.error(f"Error during content filtering or verification: {str(e)}")
                logger.warning("Using unfiltered mindmap due to filtering/verification error")
                
                return self._generate_mermaid_mindmap(concepts)

        except Exception as e:
            logger.error(f"Error in mindmap generation: {str(e)}", extra={"request_id": request_id})
            raise MindMapGenerationError(f"Failed to generate mindmap: {str(e)}")

    async def _generate_topics_from_clusters(
        self, 
        clusters: List[List[Dict[str, Any]]], 
        request_id: str
    ) -> List[Dict[str, Any]]:
        """Generate topics from semantic segment clusters provided by Weaviate.

        Args:
            clusters: List of topic clusters, where each cluster is a list of segment dictionaries.
            request_id: Request tracking ID.

        Returns:
            List of topic dictionaries with names, summaries, and citations.
        """
        topics = []
        
        for cluster_idx, cluster in enumerate(clusters):
            # Extract texts and segment IDs from the cluster
            segment_texts = [seg['text'] for seg in cluster[:3]]  # Use top 3 segments for prompt
            combined_text = "\n\n".join(segment_texts)
            all_segment_ids = [seg['segment_id'] for seg in cluster]

            # Generate topic name and summary from cluster
            # The prompt can be simplified as we no longer have pre-computed keywords
            prompt = f"""다음 텍스트 세그먼트들의 핵심 주제를 나타내는 간결한 토픽 제목을 만드세요.

텍스트:
{combined_text[:1500]}

JSON 형식으로 반환:
- "name": 3-5단어의 핵심 토픽 제목 (원문 언어 사용)
- "summary": 토픽을 설명하는 한 문장 요약 (최대 10단어)

예시: {{"name": "가상 아바타와 세계관", "summary": "멤버와 연결된 아바타 æ와 가상 세계관 FLAT"}}

JSON 객체만 반환하세요."""

            try:
                response = await self.optimizer.generate_completion(
                    prompt,
                    max_tokens=200,
                    request_id=request_id,
                    task=f"generate_topic_cluster_{cluster_idx}"
                )
                
                topic_data = self._parse_llm_response(response, "object")
                
                if topic_data and 'name' in topic_data:
                    # Add segment citations (limit to top 5)
                    topic = {
                        'name': topic_data.get('name', f"Topic {cluster_idx + 1}"),
                        'summary': topic_data.get('summary', ''),
                        'notes': '',
                        'citations': all_segment_ids[:5],  # Use segment IDs from cluster
                        'emoji': '',  # No emoji for NotebookLM style
                        'importance': 'high',
                        'subtopics': [],
                        'details': []
                    }
                    topics.append(topic)
                    logger.info(f"Generated topic: {topic['name']} (from {len(all_segment_ids)} segments)")
                    
            except Exception as e:
                logger.error(f"Error generating topic from cluster {cluster_idx}: {e}")
                continue
        
        return topics

    async def _extract_subtopics_from_segments(
        self,
        topic: Dict[str, Any],
        segments: List[DocumentSegment],
        request_id: str
    ) -> List[Dict[str, Any]]:
        """Extract subtopics from topic's segments with citations.
        
        Args:
            topic: Parent topic dictionary
            segments: List of segments for this topic
            request_id: Request tracking ID
            
        Returns:
            List of subtopic dictionaries with citations
        """
        if not segments:
            return []
            
        # Combine segment texts
        segment_texts = [seg.text for seg in segments[:5]]  # Use up to 5 segments
        combined_text = "\n\n".join(segment_texts)
        
        prompt = f"""토픽 "{topic['name']}"에 대해 2-4개의 서브토픽을 찾으세요.

텍스트:
{combined_text[:1500]}

JSON 배열 형식으로 반환:
- "name": 3-5단어 (원문 언어 사용)
- "summary": 짧은 문장 (최대 8단어)
- "segment_ids": {[seg.segment_id for seg in segments[:5]]}에서 선택

예시:
[
  {{"name": "군사적 영향", "summary": "군대에 미치는 효과", "segment_ids": ["seg_001"]}},
  {{"name": "사회적 혼란", "summary": "시민 소요 위험", "segment_ids": ["seg_002"]}},
  {{"name": "경제적 파급", "summary": "재정 손실 발생", "segment_ids": ["seg_003"]}}
]

JSON 배열만 반환하세요."""

        try:
            response = await self.optimizer.generate_completion(
                prompt,
                max_tokens=300,
                request_id=request_id,
                task=f"extract_subtopics_{topic['name']}"
            )
            
            subtopics_data = self._parse_llm_response(response, "array")
            subtopics = []
            
            for st_data in subtopics_data:
                if isinstance(st_data, dict) and 'name' in st_data:
                    subtopic = {
                        'name': st_data.get('name', ''),
                        'summary': st_data.get('summary', ''),
                        'citations': st_data.get('segment_ids', []),
                        'emoji': '',
                        'importance': 'medium',
                        'details': []
                    }
                    subtopics.append(subtopic)
                    
            logger.info(f"Extracted {len(subtopics)} subtopics for '{topic['name']}'")
            return subtopics
            
        except Exception as e:
            logger.error(f"Error extracting subtopics for {topic['name']}: {e}")
            return []

    async def _extract_details_from_segments(
        self,
        subtopic: Dict[str, Any],
        segments: List[DocumentSegment],
        request_id: str
    ) -> List[Dict[str, Any]]:
        """Extract details from subtopic's segments with citations.
        
        Args:
            subtopic: Parent subtopic dictionary
            segments: List of segments for this subtopic
            request_id: Request tracking ID
            
        Returns:
            List of detail dictionaries with citations
        """
        if not segments:
            return []
            
        # Combine segment texts
        segment_texts = [seg.text for seg in segments[:3]]  # Use up to 3 segments
        combined_text = "\n\n".join(segment_texts)
        
        prompt = f"""서브토픽 "{subtopic['name']}"에 대해 2-4개의 핵심 세부사항을 추출하세요.

서브토픽 요약: {subtopic.get('summary', '')}

텍스트 세그먼트:
{combined_text[:1500]}

JSON 배열 형식으로 반환 (각 객체는):
- "text": 간결한 한 문장 (10-15단어, 원문 언어 사용)
- "importance": "high", "medium", "low" 중 하나
- "segment_ids": {[seg.segment_id for seg in segments]}에서 선택한 배열

예시:
[
  {{"text": "Black Mamba는 51일 만에 1억 뷰 달성", "importance": "high", "segment_ids": ["seg_002"]}},
  {{"text": "데뷔곡은 독특한 가상세계 컨셉 선보임", "importance": "medium", "segment_ids": ["seg_004"]}},
  {{"text": "SM 엔터테인먼트의 신인 걸그룹", "importance": "medium", "segment_ids": ["seg_001"]}}
]

JSON 배열만 반환하세요. 텍스트는 매우 간결하게."""

        try:
            response = await self.optimizer.generate_completion(
                prompt,
                max_tokens=300,
                request_id=request_id,
                task=f"extract_details_{subtopic['name']}"
            )
            
            details_data = self._parse_llm_response(response, "array")
            details = []
            
            for detail_data in details_data:
                if isinstance(detail_data, dict) and 'text' in detail_data:
                    detail = {
                        'text': detail_data.get('text', ''),
                        'importance': detail_data.get('importance', 'medium').lower(),
                        'citations': detail_data.get('segment_ids', [])
                    }
                    details.append(detail)
                    
            logger.info(f"Extracted {len(details)} details for '{subtopic['name']}'")
            return details
            
        except Exception as e:
            logger.error(f"Error extracting details for {subtopic['name']}: {e}")
            return []

    async def _extract_main_topics(self, content: str, topics_prompt: str, request_id: str) -> List[Dict[str, Any]]:
        """Extract main topics using LLM with more aggressive deduplication and content preservation.
        
        Args:
            content (str): The document content to analyze
            topics_prompt (str): The prompt template for topic extraction
            request_id (str): Unique identifier for the request
            
        Returns:
            List[Dict[str, Any]]: List of extracted topics with their metadata
            
        Raises:
            MindMapGenerationError: If topic extraction fails
        """
        MAX_TOPICS = 8  # Increased from 6 to ensure complete coverage
        MIN_TOPICS = 4  # Minimum topics to process
        MAX_CONCURRENT_TASKS = 50  # Limit concurrent LLM calls
        
        async def extract_from_chunk(chunk: str) -> List[Dict[str, Any]]:
            """Extract topics from a single content chunk."""
            consolidated_prompt = f"""You are an expert at identifying unique, distinct main topics within content.
                        
            {topics_prompt}

            Additional requirements:
            1. Each topic must be truly distinct from others - avoid overlapping concepts
            2. Combine similar themes into single, well-defined topics
            3. Ensure topics are specific enough to be meaningful but general enough to support subtopics
            4. Aim for 4-8 most significant topics that capture the key distinct areas
            5. Focus on conceptual separation - each topic should represent a unique aspect or dimension
            6. Avoid topics that are too similar or could be subtopics of each other
            7. Prioritize broader topics that can encompass multiple subtopics
            8. Eliminate redundancy - each topic should cover a distinct area with no overlap

            IMPORTANT: 
            1. DO NOT include specific statistics, percentages, or numerical data unless explicitly stated in the source text
            2. DO NOT refer to modern studies, surveys, or analyses that aren't mentioned in the document
            3. DO NOT make up correlation coefficients, growth rates, or other numerical relationships
            4. Keep your content strictly based on what's in the document, not general knowledge about the topic
            5. Use general descriptions rather than specific numbers if the document doesn't provide exact figures

            Current content chunk:
            {chunk}

            IMPORTANT: Respond with ONLY a JSON array of strings representing the main distinct topics.
            Example format: ["First Distinct Topic", "Second Distinct Topic"]"""

            try:
                response = await self.optimizer.generate_completion(
                    consolidated_prompt,
                    max_tokens=1000,
                    request_id=request_id,
                    task="extracting_main_topics"
                )
                
                logger.debug(f"Raw topics response for chunk: {response}", 
                            extra={"request_id": request_id})
                
                parsed_response = self._parse_llm_response(response, "array")
                
                chunk_topics = []
                seen_names = set()
                
                for topic_name in parsed_response:
                    if isinstance(topic_name, str) and topic_name.strip():
                        cleaned_name = re.sub(r'[`*_#]', '', topic_name)
                        cleaned_name = ' '.join(cleaned_name.split())
                        
                        if cleaned_name and cleaned_name not in seen_names:
                            seen_names.add(cleaned_name)
                            # Select appropriate emoji for topic
                            emoji = await self._select_emoji(cleaned_name, 'topic')
                            chunk_topics.append({
                                'name': cleaned_name,
                                'emoji': emoji,
                                'processed': False,  # Track processing status
                                'importance': 'high',  # Main topics are always high importance
                                'subtopics': [],
                                'details': []
                            })
                
                return chunk_topics
                
            except Exception as e:
                logger.error(f"Error extracting topics from chunk: {str(e)}", 
                            extra={"request_id": request_id})
                return []

        try:
            # Create content chunks with overlap to ensure context preservation
            chunk_size = min(8000, len(content) // 3) if len(content) > 6000 else 4000
            overlap = 250  # Characters of overlap between chunks
            
            # Create overlapping chunks
            content_chunks = []
            start = 0
            while start < len(content):
                end = min(start + chunk_size, len(content))
                # Extend to nearest sentence end if possible
                if end < len(content):
                    next_period = content.find('.', end)
                    if next_period != -1 and next_period - end < 200:  # Don't extend too far
                        end = next_period + 1
                chunk = content[start:end]
                content_chunks.append(chunk)
                start = end - overlap if end < len(content) else end

            # Initialize concurrent processing controls
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
            topics_with_metrics = {}  # Track topic frequency and importance
            unique_topics_seen = set()
            max_chunks_to_process = 5  # Increased from 3

            async def process_chunk(chunk: str, chunk_idx: int) -> List[Dict[str, Any]]:
                """Process a single chunk with semaphore control."""
                if chunk_idx >= max_chunks_to_process:
                    return []
                    
                if len(unique_topics_seen) >= MAX_TOPICS * 1.5:
                    return []
                    
                async with semaphore:
                    return await self._retry_with_exponential_backoff(
                        lambda: extract_from_chunk(chunk)
                    )

            # Process chunks concurrently
            chunk_results = await asyncio.gather(
                *(process_chunk(chunk, idx) for idx, chunk in enumerate(content_chunks))
            )

            # Process results with more aggressive deduplication
            all_topics = []
            for chunk_topics in chunk_results:
                # Track topic frequency and merge similar topics
                for topic in chunk_topics:
                    topic_key = topic['name'].lower()
                    
                    # Check for similar existing topics with stricter criteria
                    similar_found = False
                    for existing_key in list(topics_with_metrics.keys()):
                        if await self.is_similar_to_existing(topic_key, {existing_key: True}, 'topic'):
                            topics_with_metrics[existing_key]['frequency'] += 1
                            similar_found = True
                            break
                    
                    if not similar_found:
                        topics_with_metrics[topic_key] = {
                            'topic': topic,
                            'frequency': 1,
                            'first_appearance': len(all_topics)
                        }
                
                # Only add unique topics
                for topic in chunk_topics:
                    if topic['name'] not in unique_topics_seen:
                        unique_topics_seen.add(topic['name'])
                        all_topics.append(topic)
                        
                        if len(unique_topics_seen) >= MAX_TOPICS * 1.5:
                            break

                # Early stopping checks
                if len(unique_topics_seen) >= MIN_TOPICS:
                    topic_frequencies = [metrics['frequency'] for metrics in topics_with_metrics.values()]
                    if len(topic_frequencies) >= MIN_TOPICS:
                        avg_frequency = sum(topic_frequencies) / len(topic_frequencies)
                        if avg_frequency >= 1.5:  # Topics appear in multiple chunks
                            break

            if not all_topics:
                error_msg = "No valid topics extracted from document"
                logger.error(error_msg, extra={"request_id": request_id})
                raise MindMapGenerationError(error_msg)

            # Add consolidation step when we have too many potential topics
            if len(all_topics) > MIN_TOPICS * 1.5:
                consolidation_prompt = f"""You are merging and consolidating similar topics from a document.

                Here are the current potential topics extracted:
                {json.dumps([topic['name'] for topic in all_topics], indent=2)}

                Requirements:
                1. Identify topics that cover the same or similar concepts
                2. Merge overlapping topics into a single, well-defined topic
                3. Choose the most representative, precise, and concise name for each topic
                4. Ensure each final topic is clearly distinct from others
                5. Aim for exactly {MIN_TOPICS}-{MAX_TOPICS} distinct topics that cover the key areas
                6. Completely eliminate redundancy - each topic should represent a unique conceptual area
                7. Broader topics are preferred over narrower ones if they can encompass the same content
                8. Choose clear, concise topic names that accurately represent the content

                Return ONLY a JSON array of consolidated topic names.
                Example: ["First Consolidated Topic", "Second Consolidated Topic"]"""

                try:
                    response = await self._retry_generate_completion(
                        consolidation_prompt,
                        max_tokens=1000,
                        request_id=request_id,
                        task="consolidating_topics"
                    )
                    
                    consolidated_names = self._parse_llm_response(response, "array")
                    
                    if consolidated_names and len(consolidated_names) >= MIN_TOPICS:
                        # Create new topics from consolidated names
                        consolidated_topics = []
                        seen_names = set()
                        
                        for name in consolidated_names:
                            if isinstance(name, str) and name.strip():
                                cleaned_name = re.sub(r'[`*_#]', '', name)
                                cleaned_name = ' '.join(cleaned_name.split())
                                
                                if cleaned_name and cleaned_name not in seen_names:
                                    emoji = await self._select_emoji(cleaned_name, 'topic')
                                    consolidated_topics.append({
                                        'name': cleaned_name,
                                        'emoji': emoji,
                                        'processed': False,
                                        'importance': 'high',
                                        'subtopics': [],
                                        'details': []
                                    })
                                    seen_names.add(cleaned_name)
                        
                        if len(consolidated_topics) >= MIN_TOPICS:
                            all_topics = consolidated_topics
                            logger.info(f"Successfully consolidated topics from {len(unique_topics_seen)} to {len(consolidated_topics)}")
                except Exception as e:
                    logger.warning(f"Topic consolidation failed: {str(e)}", extra={"request_id": request_id})

            # Sort and select final topics with stricter deduplication
            sorted_topics = sorted(
                topics_with_metrics.values(),
                key=lambda x: (-x['frequency'], x['first_appearance'])
            )

            final_topics = []
            seen_final = set()
            
            # Select final topics with more aggressive deduplication
            for topic_data in sorted_topics:
                topic = topic_data['topic']
                if len(final_topics) >= MAX_TOPICS:
                    break
                    
                if topic['name'] not in seen_final:
                    similar_exists = False
                    for existing_topic in final_topics:
                        if await self.is_similar_to_existing(topic['name'], {existing_topic['name']: True}, 'topic'):
                            similar_exists = True
                            break
                    
                    if not similar_exists:
                        seen_final.add(topic['name'])
                        final_topics.append(topic)

            # Add additional topics if needed 
            if len(final_topics) < MIN_TOPICS:
                for topic in all_topics:
                    if len(final_topics) >= MIN_TOPICS:
                        break
                        
                    if topic['name'] not in seen_final:
                        similar_exists = False
                        for existing_topic in final_topics:
                            if await self.is_similar_to_existing(topic['name'], {existing_topic['name']: True}, 'topic'):
                                similar_exists = True
                                break
                        
                        if not similar_exists:
                            seen_final.add(topic['name'])
                            final_topics.append(topic)

            # Final LLM-based deduplication when we have enough topics
            if len(final_topics) > MIN_TOPICS:
                for i in range(len(final_topics)-1, 0, -1):
                    if len(final_topics) <= MIN_TOPICS:
                        break
                        
                    for j in range(i-1, -1, -1):
                        try:
                            is_duplicate = await self.check_similarity_llm(
                                final_topics[i]['name'], 
                                final_topics[j]['name'],
                                "main topic", 
                                "main topic"
                            )
                            
                            if is_duplicate and len(final_topics) > MIN_TOPICS:
                                logger.info(f"LLM detected duplicate topics: '{final_topics[i]['name']}' and '{final_topics[j]['name']}'")
                                del final_topics[i]
                                break
                        except Exception as e:
                            logger.warning(f"LLM duplicate check failed: {str(e)}")
                            continue

            logger.info(
                f"Successfully extracted {len(final_topics)} main topics "
                f"(min: {MIN_TOPICS}, max: {MAX_TOPICS})",
                extra={"request_id": request_id}
            )

            return final_topics

        except Exception as e:
            error_msg = f"Failed to extract main topics: {str(e)}"
            logger.error(error_msg, extra={"request_id": request_id})
            raise MindMapGenerationError(error_msg)

    async def _extract_subtopics(self, topic: Dict[str, Any], content: str, subtopics_prompt_template: str, request_id: str) -> List[Dict[str, Any]]:
        """Extract subtopics using LLM with more aggressive deduplication and content preservation."""
        MAX_SUBTOPICS = self.config['max_subtopics']
        MAX_CONCURRENT_TASKS = 50  # Limit concurrent LLM calls
        
        content_hash = hashlib.md5(content.encode()).hexdigest()
        cache_key = f"subtopics_{topic['name']}_{content_hash}_{request_id}"
        
        if not hasattr(self, '_subtopics_cache'):
            self._subtopics_cache = {}
            
        if not hasattr(self, '_processed_chunks_by_topic'):
            self._processed_chunks_by_topic = {}
        
        if topic['name'] not in self._processed_chunks_by_topic:
            self._processed_chunks_by_topic[topic['name']] = set()

        async def extract_from_chunk(chunk: str) -> List[Dict[str, Any]]:
            chunk_hash = hashlib.md5(chunk.encode()).hexdigest()
            if chunk_hash in self._processed_chunks_by_topic[topic['name']]:
                return []
                
            self._processed_chunks_by_topic[topic['name']].add(chunk_hash)
                
            enhanced_prompt = f"""You are an expert at identifying distinct, relevant subtopics that support a main topic.

            Topic: {topic['name']}

            {subtopics_prompt_template.format(topic=topic['name'])}

            Additional requirements:
            1. Each subtopic must provide unique value and perspective with NO conceptual overlap
            2. Include both high-level and specific subtopics that are clearly distinct
            3. Ensure strong connection to main topic without repeating the topic itself
            4. Focus on distinct aspects or dimensions that don't overlap with each other
            5. Include 4-6 important subtopics that cover different facets of the topic
            6. Balance breadth and depth of coverage with zero redundancy
            7. Choose clear, concise subtopic names that accurately represent the content
            8. Eliminate subtopics that could be merged without significant information loss

            IMPORTANT: 
            1. DO NOT include specific statistics, percentages, or numerical data unless explicitly stated in the source text
            2. DO NOT refer to modern studies, surveys, or analyses that aren't mentioned in the document
            3. DO NOT make up correlation coefficients, growth rates, or other numerical relationships
            4. Keep your content strictly based on what's in the document, not general knowledge about the topic
            5. Use general descriptions rather than specific numbers if the document doesn't provide exact figures

            Content chunk:
            {chunk}

            IMPORTANT: Return ONLY a JSON array of strings representing distinct subtopics.
            Example: ["First Distinct Subtopic", "Second Distinct Subtopic"]"""

            try:
                response = await self.optimizer.generate_completion(
                    enhanced_prompt,
                    max_tokens=1000,
                    request_id=request_id,
                    task=f"extracting_subtopics_{topic['name']}"
                )
                
                logger.debug(f"Raw subtopics response for {topic['name']}: {response}", 
                            extra={"request_id": request_id})
                
                parsed_response = self._parse_llm_response(response, "array")
                
                chunk_subtopics = []
                seen_names = {}
                
                for subtopic_name in parsed_response:
                    if isinstance(subtopic_name, str) and subtopic_name.strip():
                        cleaned_name = re.sub(r'[`*_#]', '', subtopic_name)
                        cleaned_name = ' '.join(cleaned_name.split())
                        
                        if cleaned_name and not await self.is_similar_to_existing(cleaned_name, seen_names, 'subtopic'):
                            emoji = await self._select_emoji(cleaned_name, 'subtopic')
                            node = self._create_node(
                                name=cleaned_name,
                                emoji=emoji
                            )
                            chunk_subtopics.append(node)
                            seen_names[cleaned_name] = node
                
                return chunk_subtopics
                
            except Exception as e:
                logger.error(f"Error extracting subtopics from chunk for {topic['name']}: {str(e)}", 
                            extra={"request_id": request_id})
                return []

        try:
            if cache_key in self._subtopics_cache:
                return self._subtopics_cache[cache_key]
                
            chunk_size = min(8000, len(content) // 3) if len(content) > 6000 else 4000
            content_chunks = [content[i:i + chunk_size] 
                            for i in range(0, len(content), chunk_size)]
            
            # Initialize concurrent processing controls
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
            seen_names = {}
            all_subtopics = []
            
            async def process_chunk(chunk: str) -> List[Dict[str, Any]]:
                """Process a single chunk with semaphore control."""
                async with semaphore:
                    return await self._retry_with_exponential_backoff(
                        lambda: extract_from_chunk(chunk)
                    )

            # Process chunks concurrently
            chunk_results = await asyncio.gather(
                *(process_chunk(chunk) for chunk in content_chunks)
            )

            # Process results with more aggressive deduplication
            for chunk_subtopics in chunk_results:
                for subtopic in chunk_subtopics:
                    if not await self.is_similar_to_existing(subtopic['name'], seen_names, 'subtopic'):
                        seen_names[subtopic['name']] = subtopic
                        all_subtopics.append(subtopic)

            if not all_subtopics:
                logger.warning(f"No subtopics found for topic {topic['name']}", 
                            extra={"request_id": request_id})
                return []

            # Always perform consolidation to reduce duplicative content
            consolidation_prompt = f"""You are consolidating subtopics for the main topic: {topic['name']}

            Current subtopics:
            {json.dumps([st['name'] for st in all_subtopics], indent=2)}

            Requirements:
            1. Aggressively merge subtopics that cover similar information or concepts
            2. Eliminate any conceptual redundancy between subtopics
            3. Choose the clearest and most representative name for each consolidated subtopic
            4. Each final subtopic must address a unique aspect of the main topic
            5. Select 3-5 truly distinct subtopics that together fully cover the topic
            6. Ensure zero information repetition between subtopics
            7. Prioritize broader subtopics that can encompass multiple narrower ones
            8. Choose clear, concise subtopic names that accurately represent the content

            Return ONLY a JSON array of consolidated subtopic names.
            Example: ["First Consolidated Subtopic", "Second Consolidated Subtopic"]"""

            try:
                consolidation_response = await self._retry_generate_completion(
                    consolidation_prompt,
                    max_tokens=1000,
                    request_id=request_id,
                    task=f"consolidate_subtopics_{topic['name']}"
                )
                
                consolidated_names = self._parse_llm_response(consolidation_response, "array")
                
                if consolidated_names:
                    seen_names = {}
                    consolidated_subtopics = []
                    
                    for name in consolidated_names:
                        if isinstance(name, str) and name.strip():
                            cleaned_name = re.sub(r'[`*_#]', '', name)
                            cleaned_name = ' '.join(cleaned_name.split())
                            
                            if cleaned_name and not await self.is_similar_to_existing(cleaned_name, seen_names, 'subtopic'):
                                emoji = await self._select_emoji(cleaned_name, 'subtopic')
                                node = self._create_node(
                                    name=cleaned_name,
                                    emoji=emoji
                                )
                                consolidated_subtopics.append(node)
                                seen_names[cleaned_name] = node
                    
                    if consolidated_subtopics:
                        all_subtopics = consolidated_subtopics
                        logger.info(f"Successfully consolidated subtopics for {topic['name']} from {len(all_subtopics)} to {len(consolidated_subtopics)}")
                        
            except Exception as e:
                logger.warning(f"Subtopic consolidation failed for {topic['name']}: {str(e)}", 
                            extra={"request_id": request_id})
                # If consolidation fails, do a simple deduplication pass
                seen = set()
                deduplicated_subtopics = []
                for subtopic in all_subtopics:
                    if subtopic['name'] not in seen:
                        seen.add(subtopic['name'])
                        deduplicated_subtopics.append(subtopic)
                all_subtopics = sorted(deduplicated_subtopics, 
                                    key=lambda x: len(x['name']), 
                                    reverse=True)[:MAX_SUBTOPICS]
            
            # Final LLM-based deduplication when we have enough subtopics
            if len(all_subtopics) > 3:  # Only if we have enough to potentially remove some
                for i in range(len(all_subtopics)-1, 0, -1):
                    if len(all_subtopics) <= 3:  # Ensure we keep at least 3 subtopics
                        break
                        
                    for j in range(i-1, -1, -1):
                        try:
                            is_duplicate = await self.check_similarity_llm(
                                all_subtopics[i]['name'], 
                                all_subtopics[j]['name'],
                                f"subtopic of {topic['name']}", 
                                f"subtopic of {topic['name']}"
                            )
                            
                            if is_duplicate:
                                logger.info(f"LLM detected duplicate subtopics: '{all_subtopics[i]['name']}' and '{all_subtopics[j]['name']}'")
                                del all_subtopics[i]
                                break
                        except Exception as e:
                            logger.warning(f"LLM duplicate check failed: {str(e)}")
                            continue
            
            final_subtopics = all_subtopics[:MAX_SUBTOPICS]
            self._subtopics_cache[cache_key] = final_subtopics
            
            logger.info(f"Successfully extracted {len(final_subtopics)} subtopics for {topic['name']}", 
                        extra={"request_id": request_id})
            return final_subtopics
            
        except Exception as e:
            logger.error(f"Failed to extract subtopics for topic {topic['name']}: {str(e)}", 
                        extra={"request_id": request_id})
            return []

    def _validate_detail(self, detail: Dict[str, Any]) -> bool:
        """Validate a single detail entry with more flexible constraints."""
        try:
            # Basic structure validation
            if not isinstance(detail, dict):
                logger.debug(f"Detail not a dict: {type(detail)}")
                return False
                
            # Required fields check
            if not all(k in detail for k in ['text', 'importance']):
                logger.debug(f"Missing required fields. Found keys: {detail.keys()}")
                return False
                
            # Text validation
            if not isinstance(detail['text'], str) or not detail['text'].strip():
                logger.debug("Invalid or empty text field")
                return False
                
            # Importance validation with case insensitivity
            valid_importance = ['high', 'medium', 'low']
            if detail['importance'].lower() not in valid_importance:
                logger.debug(f"Invalid importance: {detail['importance']}")
                return False
                
            # More generous length limit
            if len(detail['text']) > 500:  # Increased from 200
                logger.debug(f"Text too long: {len(detail['text'])} chars")
                return False
                
            return True
            
        except Exception as e:
            logger.debug(f"Validation error: {str(e)}")
            return False

    async def _extract_details(self, subtopic: Dict[str, Any], content: str, details_prompt_template: str, request_id: str) -> List[Dict[str, Any]]:
        """Extract details for a subtopic with more aggressive deduplication and content preservation."""
        MINIMUM_VALID_DETAILS = 5  # Early stopping threshold
        MAX_DETAILS = self.config['max_details']
        MAX_CONCURRENT_TASKS = 50  # Limit concurrent LLM calls
        
        # Create cache key
        content_hash = hashlib.md5(content.encode()).hexdigest()
        cache_key = f"details_{subtopic['name']}_{content_hash}_{request_id}"
        
        if not hasattr(self, '_details_cache'):
            self._details_cache = {}
        
        if not hasattr(self, '_processed_chunks_by_subtopic'):
            self._processed_chunks_by_subtopic = {}
        
        if subtopic['name'] not in self._processed_chunks_by_subtopic:
            self._processed_chunks_by_subtopic[subtopic['name']] = set()

        if not hasattr(self, '_current_details'):
            self._current_details = []

        async def extract_from_chunk(chunk: str) -> List[Dict[str, Any]]:
            chunk_hash = hashlib.md5(chunk.encode()).hexdigest()
            if chunk_hash in self._processed_chunks_by_subtopic[subtopic['name']]:
                return []
                
            self._processed_chunks_by_subtopic[subtopic['name']].add(chunk_hash)
                
            enhanced_prompt = f"""You are an expert at identifying distinct, important details that support a specific subtopic.

            Subtopic: {subtopic['name']}

            {details_prompt_template.format(subtopic=subtopic['name'])}

            Additional requirements:
            1. Each detail MUST provide 3-5 sentences of specific, substantive information
            2. Include CONCRETE EXAMPLES, numbers, dates, or direct references from the text
            3. EXTRACT actual quotes or paraphrase specific passages from the source document
            4. Make each detail UNIQUELY VALUABLE - it should contain information not found in other details
            5. Focus on DEPTH rather than breadth - explore fewer ideas more thoroughly
            6. Include specific evidence, reasoning, or context that supports the subtopic
            7. Balance factual information with analytical insights
            8. Avoid generic statements that could apply to many documents

            Content chunk:
            {chunk}

            IMPORTANT: Return ONLY a JSON array where each object has:
            - "text": The detail text (3-5 sentences with specific examples and evidence)
            - "importance": "high", "medium", or "low" based on significance
            """

            try:
                response = await self.optimizer.generate_completion(
                    enhanced_prompt,
                    max_tokens=1000,
                    request_id=request_id,
                    task=f"extracting_details_{subtopic['name']}"
                )
                
                raw_details = self._clean_detail_response(response)
                chunk_details = []
                seen_texts = {}
                
                for detail in raw_details:
                    if self._validate_detail(detail) and not await self.is_similar_to_existing(detail['text'], seen_texts, 'detail'):
                        seen_texts[detail['text']] = True
                        
                        # Ensure importance is valid
                        detail['importance'] = detail['importance'].lower()
                        if detail['importance'] not in ['high', 'medium', 'low']:
                            detail['importance'] = 'medium'
                        
                        # Add to results
                        chunk_details.append({
                            'text': detail['text'],
                            'importance': detail['importance']
                        })
                        self._current_details.append(detail)
                        
                        if len(self._current_details) >= MINIMUM_VALID_DETAILS:
                            logger.info(f"Reached minimum required details ({MINIMUM_VALID_DETAILS}) during chunk processing")
                            return chunk_details
                
                return chunk_details
                    
            except Exception as e:
                logger.error(f"Error extracting details from chunk for {subtopic['name']}: {str(e)}", 
                            extra={"request_id": request_id})
                return chunk_details if 'chunk_details' in locals() else []

        try:
            if cache_key in self._details_cache:
                return self._details_cache[cache_key]

            self._current_details = []
            chunk_size = min(8000, len(content) // 3) if len(content) > 6000 else 4000
            content_chunks = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]
            
            # Initialize concurrent processing controls
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
            seen_texts = {}
            all_details = []
            early_stop = asyncio.Event()

            async def process_chunk(chunk: str) -> List[Dict[str, Any]]:
                """Process a single chunk with semaphore control."""
                if early_stop.is_set():
                    return []
                    
                async with semaphore:
                    chunk_details = await self._retry_with_exponential_backoff(
                        lambda: extract_from_chunk(chunk)
                    )
                    
                    # Check if we've reached minimum details
                    if len(self._current_details) >= MINIMUM_VALID_DETAILS:
                        early_stop.set()
                    
                    return chunk_details

            # Process chunks concurrently
            chunk_results = await asyncio.gather(
                *(process_chunk(chunk) for chunk in content_chunks)
            )

            # Process results with more aggressive deduplication
            for chunk_details in chunk_results:
                for detail in chunk_details:
                    if not await self.is_similar_to_existing(detail['text'], seen_texts, 'detail'):
                        seen_texts[detail['text']] = True
                        all_details.append(detail)

                        if len(all_details) >= MINIMUM_VALID_DETAILS:
                            break

                if len(all_details) >= MINIMUM_VALID_DETAILS:
                    logger.info(f"Reached minimum required details ({MINIMUM_VALID_DETAILS})")
                    break

            # Always perform consolidation to reduce duplicative content
            consolidation_prompt = f"""You are consolidating details for the subtopic: {subtopic['name']}

            Current details:
            {json.dumps([d['text'] for d in all_details], indent=2)}

            Requirements:
            1. Aggressively merge details that convey similar information or concepts
            2. Eliminate all redundancy and repetitive information 
            3. Choose the most clear, concise, and informative phrasing for each detail
            4. Each final detail must provide unique information not covered by others
            5. Select 3-5 truly distinct details that together fully support the subtopic
            6. Ensure that even similar-sounding details have completely different content
            7. Choose clear, concise detail text that accurately represents the information
            8. Mark each detail with appropriate importance (high/medium/low)

            Return ONLY a JSON array of consolidated details with text and importance.
            Example:
            [
                {{"text": "First distinct detail", "importance": "high"}},
                {{"text": "Second distinct detail", "importance": "medium"}}
            ]"""

            try:
                consolidation_response = await self._retry_generate_completion(
                    consolidation_prompt,
                    max_tokens=1000,
                    request_id=request_id,
                    task=f"consolidate_details_{subtopic['name']}"
                )
                
                consolidated_raw = self._clean_detail_response(consolidation_response)
                
                if consolidated_raw:
                    seen_texts = {}
                    consolidated_details = []
                    
                    for detail in consolidated_raw:
                        if self._validate_detail(detail) and not await self.is_similar_to_existing(detail['text'], seen_texts, 'detail'):
                            seen_texts[detail['text']] = True
                            detail['importance'] = detail['importance'].lower()
                            if detail['importance'] not in ['high', 'medium', 'low']:
                                detail['importance'] = 'medium'
                            consolidated_details.append(detail)
                            
                    if consolidated_details:
                        all_details = consolidated_details
                        logger.info(f"Successfully consolidated details for {subtopic['name']} from {len(all_details)} to {len(consolidated_details)}")
                    
            except Exception as e:
                logger.warning(f"Detail consolidation failed for {subtopic['name']}: {str(e)}", 
                            extra={"request_id": request_id})
                # If consolidation fails, do a simple deduplication pass
                seen = set()
                deduplicated_details = []
                for detail in all_details:
                    if detail['text'] not in seen:
                        seen.add(detail['text'])
                        deduplicated_details.append(detail)
                all_details = deduplicated_details
                if len(self._current_details) >= MINIMUM_VALID_DETAILS:
                    logger.info(f"Using {len(self._current_details)} previously collected valid details")
                    all_details = self._current_details
                else:
                    importance_order = {"high": 0, "medium": 1, "low": 2}
                    all_details = sorted(
                        all_details,
                        key=lambda x: (importance_order.get(x["importance"].lower(), 3), -len(x["text"]))
                    )[:MAX_DETAILS]

            # Final LLM-based deduplication when we have enough details
            if len(all_details) > 3:  # Only if we have enough to potentially remove some
                details_to_remove = set()
                for i in range(len(all_details)-1):
                    if i in details_to_remove:
                        continue
                        
                    if len(all_details) - len(details_to_remove) <= 3:  # Ensure we keep at least 3 details
                        break
                        
                    for j in range(i+1, len(all_details)):
                        if j in details_to_remove:
                            continue
                        
                        try:
                            is_duplicate = await self.check_similarity_llm(
                                all_details[i]['text'], 
                                all_details[j]['text'],
                                f"detail of {subtopic['name']}", 
                                f"detail of {subtopic['name']}"
                            )
                            
                            if is_duplicate:
                                logger.info("LLM detected duplicate details")
                                
                                # Determine which to keep based on importance
                                importance_i = {"high": 3, "medium": 2, "low": 1}[all_details[i]['importance']]
                                importance_j = {"high": 3, "medium": 2, "low": 1}[all_details[j]['importance']]
                                
                                if importance_i >= importance_j:
                                    details_to_remove.add(j)
                                else:
                                    details_to_remove.add(i)
                                    break  # Break inner loop if we're removing i
                        except Exception as e:
                            logger.warning(f"LLM duplicate check failed: {str(e)}")
                            continue
                            
                # Apply removals
                all_details = [d for i, d in enumerate(all_details) if i not in details_to_remove]
            
            # Sort details by importance first, then by length (longer details typically have more substance)
            importance_order = {"high": 0, "medium": 1, "low": 2}
            final_details = sorted(
                all_details, 
                key=lambda x: (importance_order.get(x["importance"].lower(), 3), -len(x["text"]))
            )[:MAX_DETAILS]            
            self._details_cache[cache_key] = final_details
            
            logger.info(f"Successfully extracted {len(final_details)} details for {subtopic['name']}", 
                            extra={"request_id": request_id})
            return final_details
                
        except Exception as e:
            logger.error(f"Failed to extract details for subtopic {subtopic['name']}: {str(e)}", 
                        extra={"request_id": request_id})
            if hasattr(self, '_current_details') and len(self._current_details) > 0:
                logger.info(f"Returning {len(self._current_details)} collected details despite error")
                return self._current_details[:MAX_DETAILS]
            return []
            
    async def _retry_generate_completion(self, prompt: str, max_tokens: int, request_id: str, task: str) -> str:
        """Retry the LLM completion in case of failures with exponential backoff."""
        retries = 0
        base_delay = 1  # Start with 1 second delay
        
        while retries < self.config['max_retries']:
            try:
                response = await self.optimizer.generate_completion(
                    prompt,
                    max_tokens=max_tokens,
                    request_id=request_id,
                    task=task
                )
                return response
            except Exception as e:
                retries += 1
                if retries >= self.config['max_retries']:
                    logger.error(f"Exceeded maximum retries for {task}", extra={"request_id": request_id})
                    raise
                
                delay = min(base_delay * (2 ** (retries - 1)), 10)  # Cap at 10 seconds
                logger.warning(f"Retrying {task} ({retries}/{self.config['max_retries']}) after {delay}s: {str(e)}", extra={"request_id": request_id})
                await asyncio.sleep(delay)

    async def verify_mindmap_against_source(self, mindmap_data: Dict[str, Any], original_document: str) -> Dict[str, Any]:
        """Verify all mindmap nodes against the original document with lenient criteria and improved error handling."""
        try:
            logger.info("\n" + "="*80)
            logger.info(colored("🔍 STARTING REALITY CHECK TO IDENTIFY POTENTIAL CONFABULATIONS", "cyan", attrs=["bold"]))
            logger.info("="*80 + "\n")
            
            # Split document into chunks to handle context window limitations
            chunk_size = 8000  # Adjust based on model context window
            overlap = 250  # Characters of overlap between chunks
            
            # Create overlapping chunks
            doc_chunks = []
            start = 0
            while start < len(original_document):
                end = min(start + chunk_size, len(original_document))
                # Extend to nearest sentence end if possible
                if end < len(original_document):
                    next_period = original_document.find('.', end)
                    if next_period != -1 and next_period - end < 200:  # Don't extend too far
                        end = next_period + 1
                chunk = original_document[start:end]
                doc_chunks.append(chunk)
                start = end - overlap if end < len(original_document) else end
            
            logger.info(f"Split document into {len(doc_chunks)} chunks for verification")
            
            # Extract all nodes from mindmap for verification
            all_nodes = []
            
            def extract_nodes(node, path=None):
                """Recursively extract all nodes with their paths."""
                if path is None:
                    path = []
                
                if not node:
                    return
                    
                current_path = path.copy()
                
                # Add current node if it has a name
                if 'name' in node and node['name']:
                    node_type = 'root' if not path else 'topic' if len(path) == 1 else 'subtopic'
                    all_nodes.append({
                        'text': node['name'],
                        'path': current_path,
                        'type': node_type,
                        'verified': False,
                        'node_ref': node,  # Store reference to original node
                        'node_id': id(node),  # Store unique object ID as backup
                        'structural_importance': 'high' if node_type in ['root', 'topic'] else 'medium'
                    })
                    current_path = current_path + [node['name']]
                
                # Add details
                for detail in node.get('details', []):
                    if isinstance(detail, dict) and 'text' in detail:
                        all_nodes.append({
                            'text': detail['text'],
                            'path': current_path,
                            'type': 'detail',
                            'verified': False,
                            'node_ref': detail,  # Store reference to original node
                            'node_id': id(detail),  # Store unique object ID as backup
                            'structural_importance': 'low',
                            'importance': detail.get('importance', 'medium')
                        })
                
                # Process subtopics
                for subtopic in node.get('subtopics', []):
                    extract_nodes(subtopic, current_path)
            
            # Start extraction from central theme
            extract_nodes(mindmap_data.get('central_theme', {}))
            logger.info(f"Extracted {len(all_nodes)} nodes for verification")
            
            # Create verification batches to limit concurrent API calls
            batch_size = 5  # Number of nodes to verify in parallel
            node_batches = [all_nodes[i:i+batch_size] for i in range(0, len(all_nodes), batch_size)]
            
            # Track verification statistics
            verification_stats = {
                'total': len(all_nodes),
                'verified': 0,
                'not_verified': 0,
                'by_type': {
                    'topic': {'total': 0, 'verified': 0},
                    'subtopic': {'total': 0, 'verified': 0},
                    'detail': {'total': 0, 'verified': 0}
                }
            }
            
            for node_type in ['topic', 'subtopic', 'detail']:
                verification_stats['by_type'][node_type]['total'] = len([n for n in all_nodes if n.get('type') == node_type])
            
            # Function to verify a single node against a document chunk
            async def verify_node_in_chunk(node, chunk):
                """Verify if a node's content is actually present in or can be logically derived from a document chunk."""
                if not node or not chunk:
                    return False
                    
                # Check if node has required keys
                required_keys = ['type', 'text']
                if not all(key in node for key in required_keys):
                    logger.warning(f"Node missing required keys: {node}")
                    return True  # Consider verified if we can't properly check it
                    
                # Special handling for root node
                if node['type'] == 'root':
                    return True  # Always consider root node verified
                    
                node_text = node['text']
                node_type = node['type']
                path_str = ' → '.join(node['path']) if node['path'] else 'root'
                
                prompt = f"""You are an expert fact-checker verifying if information in a mindmap can be reasonably derived from the original document.

            Task: Determine if this {node_type} is supported by the document text or could be reasonably inferred from it.

            {node_type.title()}: "{node_text}"
            Path: {path_str}

            Document chunk:
            ```
            {chunk}
            ```

            VERIFICATION GUIDELINES:
            1. The {node_type} can be EXPLICITLY mentioned OR reasonably inferred from the document, even through logical deduction
            2. Logical synthesis, interpretation, and summarization of concepts in the document are STRONGLY encouraged
            3. Content that represents a reasonable conclusion or implication from the document should be VERIFIED
            4. Content that groups, categorizes, or abstracts ideas from the document should be VERIFIED
            5. High-level insights that connect multiple concepts from the document should be VERIFIED
            6. Only mark as unsupported if it contains specific claims that DIRECTLY CONTRADICT the document
            7. GIVE THE BENEFIT OF THE DOUBT - if the content could plausibly be derived from the document, verify it
            8. When uncertain, LEAN TOWARDS VERIFICATION rather than rejection - mindmaps are meant to be interpretive, not literal
            9. For details specifically, allow for more interpretive latitude - they represent insights derived from the document
            10. Consider historical and domain context that would be natural to include in an analysis

            Answer ONLY with one of these formats:
            - "YES: [brief explanation of how it's supported or can be derived]" 
            - "NO: [brief explanation of why it contains information that directly contradicts the document]"

            IMPORTANT: Remember to be GENEROUS in your interpretation. If there's any reasonable way the content could be derived from the document, even through multiple logical steps, mark it as verified. Only reject content that introduces completely new facts not derivable from the document or directly contradicts it."""

                try:
                    response = await self._retry_generate_completion(
                        prompt,
                        max_tokens=150,
                        request_id='verify_node',
                        task="verifying_against_source"
                    )
                    
                    # Parse the response to get verification result
                    response = response.strip().upper()
                    is_verified = response.startswith("YES")
                    
                    # Log detailed verification result for debugging
                    logger.debug(
                        f"\n{colored('Verification result for', 'blue')}: {colored(node_text[:50] + '...', 'yellow')}\n"
                        f"Result: {colored('VERIFIED' if is_verified else 'NOT VERIFIED', 'green' if is_verified else 'red')}\n"
                        f"Response: {response[:100]}"
                    )
                    
                    return is_verified
                    
                except Exception as e:
                    logger.error(f"Error verifying node: {str(e)}")
                    # Be more lenient on errors - consider verified
                    return True
            
            # Process each node batch
            for batch_idx, batch in enumerate(node_batches):
                logger.info(f"Verifying batch {batch_idx+1}/{len(node_batches)} ({len(batch)} nodes)")
                
                # For each node, try to verify against any document chunk
                for node in batch:
                    if node.get('verified', False):
                        continue  # Skip if already verified
                        
                    node_verified = False
                    
                    # Try to verify against each chunk
                    for chunk_idx, chunk in enumerate(doc_chunks):
                        if await verify_node_in_chunk(node, chunk):
                            node['verified'] = True
                            node_verified = True
                            verification_stats['verified'] += 1
                            node_type = node.get('type', 'unknown')
                            if node_type in verification_stats['by_type']:
                                verification_stats['by_type'][node_type]['verified'] += 1
                            logger.info(
                                f"{colored('✅ VERIFIED', 'green', attrs=['bold'])}: "
                                f"{node.get('type', 'NODE').upper()} '{node.get('text', '')[:50]}...' "
                                f"(Found in chunk {chunk_idx+1})"
                            )
                            break
                    
                    if not node_verified:
                        verification_stats['not_verified'] += 1
                        logger.info(
                            f"{colored('❓ NOT VERIFIED', 'yellow', attrs=['bold'])}: "
                            f"{node.get('type', 'NODE').upper()} '{node.get('text', '')[:50]}...' "
                            f"(Not found in any chunk)"
                        )
            
            # Calculate verification percentages
            verification_percentage = (verification_stats['verified'] / verification_stats['total'] * 100) if verification_stats['total'] > 0 else 0
            for node_type in ['topic', 'subtopic', 'detail']:
                type_stats = verification_stats['by_type'][node_type]
                type_stats['percentage'] = (type_stats['verified'] / type_stats['total'] * 100) if type_stats['total'] > 0 else 0
            
            # Log verification statistics
            logger.info("\n" + "="*80)
            logger.info(colored("🔍 REALITY CHECK RESULTS", "cyan", attrs=['bold']))
            logger.info(f"Total nodes checked: {verification_stats['total']}")
            logger.info(f"Verified: {verification_stats['verified']} ({verification_percentage:.1f}%)")
            logger.info(f"Not verified: {verification_stats['not_verified']} ({100-verification_percentage:.1f}%)")
            logger.info("\nBreakdown by node type:")
            for node_type in ['topic', 'subtopic', 'detail']:
                type_stats = verification_stats['by_type'][node_type]
                logger.info(f"  {node_type.title()}s: {type_stats['verified']}/{type_stats['total']} verified ({type_stats['percentage']:.1f}%)")
            logger.info("="*80 + "\n")
            
            # Check if we need to preserve structure despite verification results
            min_topics_required = 3
            min_verification_ratio = 0.4  # Lower threshold - only filter if less than 40% verified
            
            # Count verified topics
            verified_topics = len([n for n in all_nodes if n.get('type') == 'topic' and n.get('verified', False)])
            
            # If verification removed too much content, we need to preserve structure
            if verified_topics < min_topics_required or verification_percentage < min_verification_ratio * 100:
                logger.warning(f"Verification would remove too much content (only {verified_topics} topics verified). Using preservation mode.")
                
                # Mark important structural nodes as verified to preserve mindmap structure
                for node in all_nodes:
                    # Always keep root and topic nodes
                    if node.get('type') in ['root', 'topic']:
                        node['verified'] = True
                    # Keep subtopics with a high enough importance
                    elif node.get('type') == 'subtopic' and not node.get('verified', False):
                        # Keep subtopics if they have verified details or are needed for structure
                        has_verified_details = any(
                            n.get('verified', False) and n.get('type') == 'detail' and n.get('path') == node.get('path', []) + [node.get('text', '')]
                            for n in all_nodes
                        )
                        if has_verified_details:
                            node['verified'] = True
                
                # Recalculate statistics
                verification_stats['verified'] = len([n for n in all_nodes if n.get('verified', False)])
                verification_stats['not_verified'] = len(all_nodes) - verification_stats['verified']
                verification_percentage = (verification_stats['verified'] / verification_stats['total'] * 100) if verification_stats['total'] > 0 else 0
                
                logger.info("\n" + "="*80)
                logger.info(colored("🔄 UPDATED REALITY CHECK WITH STRUCTURE PRESERVATION", "yellow", attrs=['bold']))
                logger.info(f"Verified after preservation: {verification_stats['verified']} ({verification_percentage:.1f}%)")
                logger.info(f"Not verified after preservation: {verification_stats['not_verified']} ({100-verification_percentage:.1f}%)")
                logger.info("="*80 + "\n")
            
            # Rebuild mindmap with preserving structure
            def rebuild_mindmap(node):
                """Recursively rebuild mindmap keeping only verified nodes."""
                if not node:
                    return None
                    
                result = copy.deepcopy(node)
                result['subtopics'] = []
                
                # Process subtopics and keep only verified ones
                verified_subtopics = []
                for subtopic in node.get('subtopics', []):
                    if not subtopic.get('name'):
                        continue
                        
                    # Check if this subtopic is verified by comparing with stored nodes
                    subtopic_verified = False
                    subtopic_id = id(subtopic)
                    
                    for n in all_nodes:
                        # First try to match by direct object reference
                        if n.get('node_ref') is subtopic and n.get('verified', False):
                            subtopic_verified = True
                            break
                        # Fallback to matching by object ID if reference comparison fails
                        elif n.get('node_id') == subtopic_id and n.get('verified', False):
                            subtopic_verified = True
                            break
                        # Last resort: match by name and path
                        elif (n.get('type') in ['topic', 'subtopic'] and 
                            n.get('text') == subtopic.get('name') and 
                            n.get('verified', False)):
                            subtopic_verified = True
                            break
                    
                    if subtopic_verified:
                        rebuilt_subtopic = rebuild_mindmap(subtopic)
                        if rebuilt_subtopic:
                            verified_subtopics.append(rebuilt_subtopic)
                
                result['subtopics'] = verified_subtopics
                
                # Filter details to keep only verified ones
                if 'details' in result:
                    verified_details = []
                    for detail in result.get('details', []):
                        if not isinstance(detail, dict) or 'text' not in detail:
                            continue
                            
                        # Check if this detail is verified
                        detail_verified = False
                        detail_id = id(detail)
                        
                        for n in all_nodes:
                            # First try to match by direct object reference
                            if n.get('node_ref') is detail and n.get('verified', False):
                                detail_verified = True
                                break
                            # Fallback to matching by object ID
                            elif n.get('node_id') == detail_id and n.get('verified', False):
                                detail_verified = True
                                break
                            # Last resort: match by text content
                            elif n.get('type') == 'detail' and n.get('text') == detail.get('text') and n.get('verified', False):
                                detail_verified = True
                                break
                        
                        if detail_verified:
                            verified_details.append(detail)
                    
                    result['details'] = verified_details
                
                # Only return node if it has content
                if result.get('subtopics') or result.get('details'):
                    return result
                return None
            
            # Rebuild mindmap with only verified content
            verified_mindmap = {
                'central_theme': rebuild_mindmap(mindmap_data.get('central_theme', {}))
            }
            
            # Final safety check - if we have no content after verification, use original
            if not verified_mindmap.get('central_theme') or not verified_mindmap.get('central_theme', {}).get('subtopics'):
                logger.warning("After verification, no valid content remains - using original mindmap with warning")
                return mindmap_data
            
            # Calculate how much content was preserved
            original_count = len(all_nodes)
            verified_count = len([n for n in all_nodes if n.get('verified', False)])
            preservation_rate = (verified_count / original_count * 100) if original_count > 0 else 0
            
            logger.info(
                f"\n{colored('✅ REALITY CHECK COMPLETE', 'green', attrs=['bold'])}\n"
                f"Preserved {verified_count}/{original_count} nodes ({preservation_rate:.1f}%)"
            )
            
            return verified_mindmap
        
        except Exception as e:
            # Better error handling with detailed logging
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Error during verification: {str(e)}\n{error_details}")
            # Return the original mindmap in case of any errors
            return mindmap_data

    def _generate_mermaid_mindmap(self, concepts: Dict[str, Any]) -> str:
        """Generate complete Mermaid mindmap syntax from concepts.
        
        Args:
            concepts (Dict[str, Any]): The complete mindmap concept hierarchy
            
        Returns:
            str: Complete Mermaid mindmap syntax
        """
        mindmap_lines = ["mindmap"]
        
        # Start with root node - ignore any name/text for root, just use document emoji
        self._add_node_to_mindmap({'name': ''}, mindmap_lines, indent_level=1)
        
        # Add all main topics under root
        for topic in concepts.get('central_theme', {}).get('subtopics', []):
            self._add_node_to_mindmap(topic, mindmap_lines, indent_level=2)
        
        return "\n".join(mindmap_lines)

    def _convert_mindmap_to_markdown(self, mermaid_syntax: str) -> str:
        """Convert Mermaid mindmap syntax to properly formatted Markdown outline.
        
        Args:
            mermaid_syntax (str): The Mermaid mindmap syntax string
            
        Returns:
            str: Properly formatted Markdown outline with full depth hierarchy
        """
        markdown_lines = []
        
        # Split into lines and process each (skip the 'mindmap' header)
        lines = mermaid_syntax.split('\n')[1:]
        
        for line in lines:
            # Skip empty lines
            if not line.strip():
                continue
                
            # Count indentation level (number of 4-space blocks)
            indent_level = len(re.match(r'^\s*', line).group()) // 4
            
            # Extract the content between node shapes
            content = line.strip()
            
            # Handle different node types based on indent level
            if indent_level == 1:  # Root node (Document title)
                # Extract content between (( and )) or just the text
                node_text = re.search(r'\(\((.*?)\)\)', content)
                if node_text:
                    root_title = node_text.group(1).strip()
                    # Remove emoji if present
                    root_title = re.sub(r'📄\s*', '', root_title)
                    if root_title and root_title != 'Document Mindmap':
                        markdown_lines.append(f"# {root_title}")
                        markdown_lines.append("")
                
            elif indent_level == 2:  # Main topics
                # Extract content between (( and ))
                node_text = re.search(r'\(\((.*?)\)\)', content)
                if node_text:
                    if markdown_lines:  # Add extra newline between main topics
                        markdown_lines.append("")
                    current_topic = node_text.group(1).strip()
                    markdown_lines.append(f"## {current_topic}")
                    markdown_lines.append("")
                    
            elif indent_level == 3:  # Subtopics
                # Extract content between ( and )
                node_text = re.search(r'\((.*?)\)', content)
                if node_text:
                    current_subtopic = node_text.group(1).strip()
                    markdown_lines.append(f"### {current_subtopic}")
                    markdown_lines.append("")
                    
            elif indent_level == 4:  # Details
                # Extract content between [ and ]
                node_text = re.search(r'\[(.*?)\]', content)
                if node_text:
                    detail_text = node_text.group(1).strip()
                    markdown_lines.append(f"♦️ {detail_text}")
                    markdown_lines.append("")
                    
            elif indent_level == 5:  # Sub-details
                # Extract content between [ and ]
                node_text = re.search(r'\[(.*?)\]', content)
                if node_text:
                    subdetail_text = node_text.group(1).strip()
                    markdown_lines.append(f"🔸 {subdetail_text}")
                    markdown_lines.append("")
        
        # Join lines with proper spacing
        markdown_text = "\n".join(markdown_lines)
        
        # Clean up any lingering Mermaid syntax artifacts
        markdown_text = re.sub(r'\\\(', '(', markdown_text)
        markdown_text = re.sub(r'\\\)', ')', markdown_text)
        markdown_text = re.sub(r'\\(?=[()])', '', markdown_text)
        
        # Clean up multiple consecutive blank lines
        markdown_text = re.sub(r'\n{3,}', '\n\n', markdown_text)
        
        return markdown_text.strip()
    
def generate_mermaid_html(mermaid_code):
    # Remove leading/trailing triple backticks if present
    mermaid_code = mermaid_code.strip()
    if mermaid_code.startswith('```') and mermaid_code.endswith('```'):
        mermaid_code = mermaid_code[3:-3].strip()
    # Create the data object to be encoded
    data = {
        "code": mermaid_code,
        "mermaid": {"theme": "default"}
    }
    json_string = json.dumps(data)
    compressed_data = zlib.compress(json_string.encode('utf-8'), level=9)
    base64_string = base64.urlsafe_b64encode(compressed_data).decode('utf-8').rstrip('=')
    edit_url = f'https://mermaid.live/edit#pako:{base64_string}'
    # Now generate the HTML template
    html_template = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Mermaid Mindmap</title>
  <!-- Tailwind CSS -->
  <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
  <!-- Mermaid JS -->
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11.4.0/dist/mermaid.min.js"></script>
  <style>
    body {{
      margin: 0;
      padding: 0;
    }}
    #mermaid {{
      width: 100%;
      height: calc(100vh - 64px); /* Adjust height considering header */
      overflow: auto;
    }}
  </style>
</head>
<body class="bg-gray-100">
  <div class="flex items-center justify-between p-4 bg-white shadow">
    <h1 class="text-xl font-bold">Mermaid Mindmap</h1>
    <a href="{edit_url}" target="_blank" id="editButton" class="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600">Edit in Mermaid Live Editor</a>
  </div>
  <div id="mermaid" class="p-4">
    <pre class="mermaid">
{mermaid_code}
    </pre>
  </div>
  <script>
    mermaid.initialize({{
      startOnLoad: true,
      securityLevel: 'loose',
      theme: 'default',
      mindmap: {{
        useMaxWidth: true
      }},
      themeConfig: {{
        controlBar: true
      }}
    }});
  </script>
</body>
</html>'''
    return html_template

async def generate_document_mindmap(document_id: str, request_id: str) -> Tuple[str, str]:
    """Generate both Mermaid mindmap and Markdown outline for a document.
    
    Args:
        document_id (str): The ID of the document to process
        request_id (str): Unique identifier for request tracking
        
    Returns:
        Tuple[str, str]: (mindmap_file_path, markdown_file_path)
    """
    try:
        generator = MindMapGenerator()
        db = await initialize_db()
        document = await db.get_document_by_id(document_id)
        if not document:
            logger.error(f"Document not found: {document_id}", extra={"request_id": request_id})
            return "", ""

        # Define file paths for both formats
        mindmap_file_path = f"generated_mindmaps/{document['sanitized_filename']}_mermaid_mindmap__sglang.txt"
        mindmap_html_file_path = f"generated_mindmaps/{document['sanitized_filename']}_mindmap__sglang.html"
        markdown_file_path = f"generated_mindmaps/{document['sanitized_filename']}_mindmap_outline__sglang.md"
        
        # Check if both files already exist
        if os.path.exists(mindmap_file_path) and os.path.exists(markdown_file_path):
            logger.info(f"Both mindmap and markdown already exist for document {document_id}. Reusing existing files.", extra={"request_id": request_id})
            return mindmap_file_path, markdown_file_path

        optimized_text = await db.get_optimized_text(document_id, request_id)
        if not optimized_text:
            logger.error(f"Optimized text not found for document: {document_id}", extra={"request_id": request_id})
            return "", ""

        # Generate mindmap
        mermaid_syntax = await generator.generate_mindmap(optimized_text, request_id)
        
        # Convert to HTML
        mermaid_html = generate_mermaid_html(mermaid_syntax)
        
        # Convert to markdown
        markdown_outline = generator._convert_mindmap_to_markdown(mermaid_syntax)

        # Save all 3 formats
        os.makedirs(os.path.dirname(mindmap_file_path), exist_ok=True)
        
        async with aiofiles.open(mindmap_file_path, 'w', encoding='utf-8') as f:
            await f.write(mermaid_syntax)
            
        async with aiofiles.open(mindmap_html_file_path, 'w', encoding='utf-8') as f:
            await f.write(mermaid_html)
            
        async with aiofiles.open(markdown_file_path, 'w', encoding='utf-8') as f:
            await f.write(markdown_outline)

        logger.info(f"Mindmap and associated html/markdown generated successfully for document {document_id}", extra={"request_id": request_id})
        return mindmap_file_path, mindmap_html_file_path, markdown_file_path
        
    except Exception as e:
        logger.error(f"Error generating mindmap and associated html/markdown for document {document_id}: {str(e)}", extra={"request_id": request_id})
        return "", ""

def generate_interactive_html(concepts: Dict[str, Any]) -> str:
    """Generate interactive NotebookLM-style HTML visualization."""
    logger = get_logger()
    
    # 디버깅: concepts 구조 확인
    logger.info(f"Concepts keys: {list(concepts.keys()) if concepts else 'None'}")
    if concepts and 'central_theme' in concepts:
        central_theme = concepts.get('central_theme', {})
        logger.info(f"Central theme keys: {list(central_theme.keys())}")
        subtopics = central_theme.get('subtopics', [])
        logger.info(f"Number of topics: {len(subtopics)}")
        if subtopics:
            logger.info(f"First topic keys: {list(subtopics[0].keys())}")
            if 'subtopics' in subtopics[0]:
                logger.info(f"First topic has {len(subtopics[0]['subtopics'])} subtopics")
                if subtopics[0]['subtopics']:
                    logger.info(f"First subtopic keys: {list(subtopics[0]['subtopics'][0].keys())}")
    
    # Extract topics data
    topics_data = []
    for topic in concepts.get('central_theme', {}).get('subtopics', []):
        topic_dict = {
            'name': topic.get('name', ''),
            'summary': topic.get('summary', ''),
            'citations': ', '.join(topic.get('citations', [])[:3]),
            'subtopics': []
        }
        
        for subtopic in topic.get('subtopics', []):
            subtopic_dict = {
                'name': subtopic.get('name', ''),
                'citations': ', '.join(subtopic.get('citations', [])[:2]),
                'details': []
            }
            
            for detail in subtopic.get('details', []):
                detail_dict = {
                    'text': detail.get('text', ''),
                    'importance': detail.get('importance', 'medium'),
                    'citations': ', '.join(detail.get('citations', [])[:2])
                }
                subtopic_dict['details'].append(detail_dict)
            
            topic_dict['subtopics'].append(subtopic_dict)
        
        topics_data.append(topic_dict)
    
    # Read template
    template_path = Path(__file__).parent / 'visualize_mindmap.html'
    with open(template_path, 'r', encoding='utf-8') as f:
        html_template = f.read()
    
    # Insert data
    data_json = json.dumps({'topics': topics_data}, ensure_ascii=False, indent=2)
    html = html_template.replace('MINDMAP_DATA_PLACEHOLDER', data_json)
    
    return html

async def process_text_file(filepath: str, max_topics: int = 8):
    """Process a single text file and generate mindmap outputs."""
    logger = get_logger()
    try:
        # Read the input file
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        # Store content in our stub database
        MinimalDatabaseStub.store_text(content)
        # Generate a unique document ID based on content hash
        content_hash = hashlib.md5(content.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = os.path.splitext(os.path.basename(filepath))[0]
        document_id = f"{base_filename}_{content_hash}_{timestamp}"
        # Initialize the mindmap generator
        generator = MindMapGenerator()
        # Generate the mindmap with concepts (max_topics 전달)
        mindmap = await generator.generate_mindmap(content, request_id=document_id, max_topics=max_topics)
        
        # Get concepts for interactive HTML (need to store during generation)
        concepts = getattr(generator, '_last_concepts', None)
        
        # Generate HTML outputs
        html = generate_mermaid_html(mindmap)
        interactive_html = generate_interactive_html(concepts) if concepts else html
        
        # Generate markdown outline
        markdown_outline = generator._convert_mindmap_to_markdown(mindmap)
        
        # Output directory: nextits_data/Results/8.mindmap
        output_dir = Path(__file__).parent.parent.parent / "nextits_data" / "Results" / "8.mindmap"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save outputs with simple names based on input file
        output_files = {
            # str(output_dir / f"{base_filename}_mindmap.txt"): mindmap,
            str(output_dir / f"{base_filename}_mindmap.html"): interactive_html,
            str(output_dir / f"{base_filename}_mindmap_outline.md"): markdown_outline
        }
        # Save all outputs
        for filename, content in output_files.items():
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
                logger.info(f"Saved {filename}")
        
        logger.info("Mindmap generation completed successfully!")
        return output_files
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        raise
    
async def main():
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description='Generate mindmap from document')
    parser.add_argument('input_file', help='Input document file path')
    parser.add_argument('--request-id', help='Request ID for tracking')
    parser.add_argument('--max-topics', type=int, default=8, help='Maximum topics')
    parser.add_argument('--output-json', action='store_true', help='Output as JSON')
    
    args = parser.parse_args()
    input_file = args.input_file
    
    try:
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        # JSON 출력 모드 (API 호출용)
        if args.output_json:
            # 로그를 완전히 억제
            logging.disable(logging.CRITICAL)
            
            # SGLang 로그도 억제
            os.environ['SGLANG_LOG_LEVEL'] = 'ERROR'
            
            # 일반 모드로 실행 (파일 저장, max_topics 전달)
            output_files = await process_text_file(input_file, max_topics=args.max_topics)
            
            # 파일 경로만 JSON으로 반환
            result = {
                "status": "success",
                "output_files": output_files,
                "message": "Mindmap generated successfully"
            }
            
            # JSON만 stdout으로 출력 (다른 출력 없이)
            sys.stdout.write(json.dumps(result, ensure_ascii=False))
            sys.stdout.write('\n')
            sys.stdout.flush()
        else:
            # 일반 모드 (파일 출력, max_topics 전달)
            logger.info(f"Generating mindmap for {input_file} (max_topics={args.max_topics})")
            output_files = await process_text_file(input_file, max_topics=args.max_topics)
            
            # Print summary
            print("\nMindmap Generation Complete!")
            print("Generated files:")
            for filename in output_files:
                print(f"- {filename}")
            
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        logger.error(error_msg)
        
        # JSON 출력 모드에서는 에러도 JSON으로 반환
        if args.output_json:
            result = {
                "status": "error",
                "error": str(e),
                "message": error_msg
            }
            sys.stdout.write(json.dumps(result, ensure_ascii=False))
            sys.stdout.write('\n')
            sys.stdout.flush()
            sys.exit(1)
        else:
            raise

# === API 호환 래퍼 함수 ===
async def generate_mindmap_for_api(
    document_content: str,
    request_id: str = None,
    max_topics: int = 8
) -> Dict[str, Any]:
    """
    API 호환을 위한 래퍼 함수
    
    Args:
        document_content: 문서 내용
        request_id: 요청 ID (선택)
        max_topics: 최대 주제 수 (default: 8)
    
    Returns:
        {
            "mermaid": str,      # Mermaid 문법
            "markdown": str,     # Markdown 아웃라인
            "html": str,         # HTML 뷰어
            "interactive_html": str,  # 인터랙티브 HTML
            "concepts": List     # 추출된 개념들
        }
    """
    logger = get_logger()
    
    try:
        # 임시 데이터베이스에 저장
        MinimalDatabaseStub.store_text(document_content)
        
        # 생성기 초기화
        generator = MindMapGenerator()
        
        # 마인드맵 생성 (max_topics 파라미터 전달)
        mermaid_result = await generator.generate_mindmap(
            document_content,
            request_id=request_id or "api_request",
            max_topics=max_topics
        )
        
        # 개념 추출 (마지막 생성 결과에서)
        concepts = getattr(generator, '_last_concepts', None)
        
        # HTML 생성
        html = generate_mermaid_html(mermaid_result)
        interactive_html = generate_interactive_html(concepts) if concepts else html
        
        # Markdown 변환
        markdown = generator._convert_mindmap_to_markdown(mermaid_result)
        
        return {
            "mermaid": mermaid_result,
            "markdown": markdown,
            "html": html,
            "interactive_html": interactive_html,
            "concepts": concepts or []
        }
        
    except Exception as e:
        logger.error(f"API 마인드맵 생성 실패: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
