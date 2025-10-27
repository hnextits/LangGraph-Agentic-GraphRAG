#!/bin/bash

# SGLang Server Stop Script

echo "========================================="
echo "Stopping SGLang Servers..."
echo "========================================="

# GPU 0 서버 종료
if [ -f logs/sglang_gpu0.pid ]; then
    GPU0_PID=$(cat logs/sglang_gpu0.pid)
    if ps -p $GPU0_PID > /dev/null; then
        echo "Stopping GPU 0 Server (PID: $GPU0_PID)..."
        kill $GPU0_PID
        echo "GPU 0 Server stopped."
    else
        echo "GPU 0 Server (PID: $GPU0_PID) is not running."
    fi
    rm logs/sglang_gpu0.pid
else
    echo "GPU 0 PID file not found."
fi

# GPU 1 서버 종료
if [ -f logs/sglang_gpu1.pid ]; then
    GPU1_PID=$(cat logs/sglang_gpu1.pid)
    if ps -p $GPU1_PID > /dev/null; then
        echo "Stopping GPU 1 Server (PID: $GPU1_PID)..."
        kill $GPU1_PID
        echo "GPU 1 Server stopped."
    else
        echo "GPU 1 Server (PID: $GPU1_PID) is not running."
    fi
    rm logs/sglang_gpu1.pid
else
    echo "GPU 1 PID file not found."
fi

echo "========================================="
echo "All servers stopped."
echo "========================================="
