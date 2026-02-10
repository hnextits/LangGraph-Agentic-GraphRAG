#!/bin/bash

# SGLang 임베딩 서버 시작 스크립트
# Qwen3-Embedding-4B 모델을 포트 30001에서 서빙

export CUDA_VISIBLE_DEVICES=1

python -m sglang.launch_server \
    --model-path Qwen/Qwen3-Embedding-4B \
    --port 30001 \
    --host 127.0.0.1 \
    --mem-fraction-static 0.3 \
    --disable-cuda-graph \
    --trust-remote-code
