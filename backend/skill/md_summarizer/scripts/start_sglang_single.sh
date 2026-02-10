#!/bin/bash

# SGLang Single GPU Server Startup Script
# 단일 GPU로 서버 실행 (테스트용)
# CUDA 경로 설정
export CUDA_HOME=/usr/local/cuda-12.6
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH

MODEL_PATH="Qwen/Qwen3-4B-Instruct-2507"
MEM_FRACTION=0.3
GPU_ID=0
PORT=50000

echo "========================================="
echo "SGLang Single GPU Server Startup"
echo "Model: $MODEL_PATH"
echo "GPU: $GPU_ID"
echo "Port: $PORT"
echo "========================================="

# 로그 디렉토리 생성
mkdir -p logs

# 서버 시작
echo "Starting SGLang Server..."
CUDA_VISIBLE_DEVICES=$GPU_ID python -m sglang.launch_server \
    --model-path $MODEL_PATH \
    --host 0.0.0.0 \
    --port $PORT \
    --mem-fraction-static $MEM_FRACTION \
    --tp 1 \
    --log-level info \
    > logs/sglang_single.log 2>&1 &

SERVER_PID=$!
echo $SERVER_PID > logs/sglang_single.pid

echo "========================================="
echo "Server started successfully!"
echo "Endpoint: http://localhost:$PORT"
echo "PID: $SERVER_PID"
echo "Log: logs/sglang_single.log"
echo "========================================="
echo ""
echo "서버가 초기화되는 동안 30초 정도 기다려주세요..."
echo "상태 확인: curl http://localhost:$PORT/health"
echo "종료: kill $SERVER_PID"
