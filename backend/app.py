# 이 파일은 현재 사용되지 않는 Flask 기반 앱입니다.
# main.py가 FastAPI를 사용하는 주 진입점입니다.
pass
from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
from pathlib import Path
import search_test.crawler_pipeline

app = Flask(__name__)
CORS(app)  # 모든 출처에서의 요청을 허용합니다.

# @app.route('/search', methods=['POST'])
# def crawl():
#     data = request.json
#     query = data.get('query')
#     if not query:
#         return jsonify({'error': 'Query is required'}), 400

#     try:
#         # Search top 10 results and return them
#         results = crawler_pipeline.search(query, 10)

#         output_dir = "./nextits_data/Results/3.OCR_results"
#         for result in results:
#             crawler_pipeline.crawling_web(result = result, output_dir=output_dir)
#         return jsonify(results), 200
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @app.route('/v1/summarize', methods=['POST'])
# def summary():
#     """
#     클라이언트로부터 문서 목록을 받아 요약 결과를 반환하는 API 엔드포인트입니다.
#     api.py의 로직을 통합했습니다.
#     """
#     data = request.get_json()
#     if not data or 'documents' not in data:
#         return jsonify({'error': '"documents" 키가 포함된 데이터가 필요합니다.'}), 400

#     documents = data['documents']
    
#     if not documents:
#         summary_text = "요약할 문서가 없습니다."
#     else:
#         # 문서들의 제목과 스니펙을 합쳐서 요약 텍스트를 생성합니다.
#         full_text = "\n\n".join([f"제목: {doc.get('title', '')}\n내용: {doc.get('snippet', '')}" for doc in documents])
#         summary_text = f"{len(documents)}개의 문서가 선택되었습니다. 다음은 해당 문서들의 내용입니다:\n\n{full_text}"
#         # crawler_pipeline의 summarize_markdown_file 함수는 파일을 요약하는 함수이민로 직접 텍스트를 요약하는 기능은 사용하지 않음
#         # summary_text = search_test.crawler_pipeline.summarize_markdown_file(summary_text, ratio=0.1)

#     return jsonify({'summary': summary_text})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
