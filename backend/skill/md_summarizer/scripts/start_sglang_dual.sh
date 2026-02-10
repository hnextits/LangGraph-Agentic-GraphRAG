#!/bin/bash

# SGLang Dual GPU Server Startup Script
# H100 2장을 활용한 병렬 서버 구성

# CUDA 경로 설정
export CUDA_HOME=/usr/local/cuda-12.6
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH

MODEL_PATH="Qwen/Qwen3-4B-Instruct-2507"
MEM_FRACTION=0.15  # 0.5로 증가 (더 많은 입력 토큰 허용)

# 로그 디렉토리 생성
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
mkdir -p "$LOG_DIR"

echo "========================================="
echo "SGLang Dual GPU Server Startup"
echo "Model: $MODEL_PATH"
echo "Log Directory: $LOG_DIR"
echo "========================================="

# GPU 0에서 첫 번째 서버 시작
echo "Starting SGLang Server on GPU 0 (Port 30000)..."
CUDA_VISIBLE_DEVICES=0 python -m sglang.launch_server \
    --model-path $MODEL_PATH \
    --host 0.0.0.0 \
    --port 30000 \
    --mem-fraction-static $MEM_FRACTION \
    --context-length 131072 \
    --max-total-tokens 131072 \
    --tp 1 \
    --log-level info \
    > "$LOG_DIR/sglang_gpu0.log" 2>&1 &

GPU0_PID=$!
echo "GPU 0 Server PID: $GPU0_PID"

# 서버 초기화 대기
sleep 10

# GPU 1에서 두 번째 서버 시작
echo "Starting SGLang Server on GPU 1 (Port 30001)..."
CUDA_VISIBLE_DEVICES=1 python -m sglang.launch_server \
    --model-path $MODEL_PATH \
    --host 0.0.0.0 \
    --port 30001 \
    --mem-fraction-static $MEM_FRACTION \
    --context-length 131072 \
    --max-total-tokens 131072 \
    --tp 1 \
    --log-level info \
    > "$LOG_DIR/sglang_gpu1.log" 2>&1 &

GPU1_PID=$!
echo "GPU 1 Server PID: $GPU1_PID"

# PID 저장
echo $GPU0_PID > "$LOG_DIR/sglang_gpu0.pid"
echo $GPU1_PID > "$LOG_DIR/sglang_gpu1.pid"

echo "========================================="
echo "Both servers started successfully!"
echo "GPU 0: http://localhost:30000 (PID: $GPU0_PID)"
echo "GPU 1: http://localhost:30001 (PID: $GPU1_PID)"
echo "========================================="
echo "Logs:"
echo "  - GPU 0: $LOG_DIR/sglang_gpu0.log"
echo "  - GPU 1: $LOG_DIR/sglang_gpu1.log"
echo "========================================="
echo "To stop servers, run: bash scripts/stop_sglang.sh"
