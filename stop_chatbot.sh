#!/bin/bash

echo "Stopping chatbot services..."

# PID 파일에서 프로세스 ID 읽기
BACKEND_PID_FILE="/home/nextits2/.conda/envs/workbox/gui/chatbot/backend.pid"
FRONTEND_PID_FILE="/home/nextits2/.conda/envs/workbox/gui/chatbot/frontend.pid"

# 백엔드 프로세스 종료
if [ -f "$BACKEND_PID_FILE" ]; then
    BACKEND_PID=$(cat "$BACKEND_PID_FILE")
    if ps -p $BACKEND_PID > /dev/null; then
        echo "Stopping backend server (PID: $BACKEND_PID)..."
        kill -15 $BACKEND_PID
        sleep 2
        # 프로세스가 여전히 실행 중인지 확인
        if ps -p $BACKEND_PID > /dev/null; then
            echo "Backend server still running, forcing termination..."
            kill -9 $BACKEND_PID
        fi
        echo "Backend server stopped."
    else
        echo "Backend server is not running."
    fi
    rm -f "$BACKEND_PID_FILE"
else
    echo "Backend PID file not found. Searching for backend processes..."
    # PID 파일이 없는 경우 프로세스 검색
    BACKEND_PIDS=$(ps aux | grep "python main.py" | grep -v grep | awk '{print $2}')
    if [ -n "$BACKEND_PIDS" ]; then
        echo "Found backend processes: $BACKEND_PIDS"
        for pid in $BACKEND_PIDS; do
            echo "Killing process $pid..."
            kill -15 $pid
            sleep 1
            if ps -p $pid > /dev/null; then
                kill -9 $pid
            fi
        done
        echo "All backend processes stopped."
    else
        echo "No backend processes found."
    fi
fi

# 프론트엔드 프로세스 종료
if [ -f "$FRONTEND_PID_FILE" ]; then
    FRONTEND_PID=$(cat "$FRONTEND_PID_FILE")
    if ps -p $FRONTEND_PID > /dev/null; then
        echo "Stopping frontend server (PID: $FRONTEND_PID)..."
        kill -15 $FRONTEND_PID
        sleep 2
        # 프로세스가 여전히 실행 중인지 확인
        if ps -p $FRONTEND_PID > /dev/null; then
            echo "Frontend server still running, forcing termination..."
            kill -9 $FRONTEND_PID
        fi
        echo "Frontend server stopped."
    else
        echo "Frontend server is not running."
    fi
    rm -f "$FRONTEND_PID_FILE"
else
    echo "Frontend PID file not found. Searching for frontend processes..."
    # PID 파일이 없는 경우 프로세스 검색
    FRONTEND_PIDS=$(ps aux | grep "node" | grep "react-scripts start" | grep -v grep | awk '{print $2}')
    if [ -n "$FRONTEND_PIDS" ]; then
        echo "Found frontend processes: $FRONTEND_PIDS"
        for pid in $FRONTEND_PIDS; do
            echo "Killing process $pid..."
            kill -15 $pid
            sleep 1
            if ps -p $pid > /dev/null; then
                kill -9 $pid
            fi
        done
        echo "All frontend processes stopped."
    else
        echo "No frontend processes found."
    fi
fi

echo "Chatbot services stopped successfully."
