#!/bin/bash

# 로그 디렉토리 생성
mkdir -p /home/nextits2/.conda/envs/workbox/gui/chatbot/logs

# 현재 시간을 로그 파일명에 포함
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKEND_LOG="/home/nextits2/.conda/envs/workbox/gui/chatbot/logs/backend_${TIMESTAMP}.log"
FRONTEND_LOG="/home/nextits2/.conda/envs/workbox/gui/chatbot/logs/frontend_${TIMESTAMP}.log"

# Conda 환경 활성화
echo "Activating conda environment: search_test"
source /home/nextits2/.conda/etc/profile.d/conda.sh
conda activate search_test

# 백엔드 시작 (백그라운드)
echo "Starting backend server on port 8502..."
cd /home/nextits2/.conda/envs/workbox/gui/chatbot/backend
nohup python main.py > "${BACKEND_LOG}" 2>&1 & 
BACKEND_PID=$!
echo $BACKEND_PID > /home/nextits2/.conda/envs/workbox/gui/chatbot/backend.pid
echo "Backend server started with PID: $BACKEND_PID"
echo "Backend logs: ${BACKEND_LOG}"

# 잠시 대기하여 백엔드가 시작될 시간을 줌
sleep 3

# 프론트엔드 시작 (백그라운드)
echo "Starting frontend server on port 8503..."
cd /home/nextits2/.conda/envs/workbox/gui/chatbot/frontend
nohup npm start > "${FRONTEND_LOG}" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > /home/nextits2/.conda/envs/workbox/gui/chatbot/frontend.pid
echo "Frontend server started with PID: $FRONTEND_PID"
echo "Frontend logs: ${FRONTEND_LOG}"

echo ""
echo "Chatbot services started successfully!"
echo "- Backend running on http://0.0.0.0:8502 (외부 접근 가능)"
echo "- Frontend running on http://0.0.0.0:8503 (외부 접근 가능)"
echo "- API 문서: http://0.0.0.0:8502/docs"
echo ""
echo "외부에서 접근하려면 서버의 실제 IP 주소를 사용하세요."
echo "예: http://[서버IP]:8503"
echo ""
echo "To stop the services, run: ./stop_chatbot.sh"
