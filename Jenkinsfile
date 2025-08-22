pipeline {
    agent any
    
    environment {
        REMOTE_HOST = '127.0.0.1'
        REMOTE_PORT = '2226'
        REMOTE_USER = 'nextits4'
        SSH_CREDENTIALS = 'nextits4'
    }
    
    stages {
        stage('Build and Deploy on Remote Server') {
            steps {
                sshagent([env.SSH_CREDENTIALS]) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p ${REMOTE_PORT} ${REMOTE_USER}@${REMOTE_HOST} '
                                # 변수 설정
                                WORKSPACE_DIR="/home/nextits4/workspace"
                                PROJECT_DIR="$WORKSPACE_DIR/quantas"
                                REPO_URL="https://github.com/hnextits/nextitslm.git"
                                CONDA_PATH="/opt/conda/bin/activate"
                                
                                # 작업 공간 생성
                                echo "=== Creating workspace directory ==="
                                mkdir -p $WORKSPACE_DIR
                                cd $WORKSPACE_DIR
                                
                                # Git repository 처리
                                echo "=== Handling Git repository ==="
                                if [ -d "$PROJECT_DIR" ] && [ -d "$PROJECT_DIR/.git" ]; then
                                    echo "Existing repository found. Pulling latest changes..."
                                    cd $PROJECT_DIR
                                    git stash || true  # 로컬 변경사항 임시 저장
                                    git pull origin main
                                else
                                    echo "No repository found. Cloning..."
                                    rm -rf $PROJECT_DIR
                                    git clone $REPO_URL $PROJECT_DIR
                                    cd $PROJECT_DIR
                                fi
                                
                                # 환경 설정
                                echo "=== Setting up environment ==="
                                if [ -f "$CONDA_PATH" ]; then
                                    source $CONDA_PATH quantas
                                    echo "Conda environment activated"
                                else
                                    echo "Warning: Conda not found. Using system Python"
                                fi
                                
                                # 기존 프로세스 정리
                                echo "=== Cleaning up existing processes ==="
                                pkill -f "python.*main.py" || true
                                pkill -f "npm.*start" || true
                                sleep 3
                                
                                # 백엔드 실행
                                echo "=== Starting backend ==="
                                BACKEND_DIR="$PROJECT_DIR/nextitslm/backend"
                                if [ -d "$BACKEND_DIR" ] && [ -f "$BACKEND_DIR/main.py" ]; then
                                    cd $BACKEND_DIR
                                    nohup python main.py > /tmp/backend.log 2>&1 &
                                    BACKEND_PID=$!
                                    echo "Backend started with PID: $BACKEND_PID"
                                else
                                    echo "ERROR: Backend files not found!"
                                    echo "Directory structure:"
                                    find $PROJECT_DIR -name "*.py" | head -10
                                fi
                                
                                # 프론트엔드 실행
                                echo "=== Starting frontend ==="
                                FRONTEND_DIR="$PROJECT_DIR/nextitslm/frontend"
                                if [ -d "$FRONTEND_DIR" ] && [ -f "$FRONTEND_DIR/package.json" ]; then
                                    cd $FRONTEND_DIR
                                    if command -v npm &> /dev/null; then
                                        [ ! -d "node_modules" ] && npm install
                                        nohup npm start > /tmp/frontend.log 2>&1 &
                                        FRONTEND_PID=$!
                                        echo "Frontend started with PID: $FRONTEND_PID"
                                    else
                                        echo "ERROR: npm not found!"
                                    fi
                                else
                                    echo "ERROR: Frontend files not found!"
                                    echo "Directory structure:"
                                    find $PROJECT_DIR -name "package.json" | head -10
                                fi
                                
                                # 상태 확인
                                echo "=== Final status check ==="
                                sleep 5
                                echo "Running processes:"
                                ps aux | grep -E "(python.*main|npm.*start)" | grep -v grep || echo "No application processes running"
                                
                                echo "Log files:"
                                [ -f /tmp/backend.log ] && echo "Backend log: $(tail -n 3 /tmp/backend.log)"
                                [ -f /tmp/frontend.log ] && echo "Frontend log: $(tail -n 3 /tmp/frontend.log)"
                                
                                echo "=== Deployment completed ==="
                            '
                        '''
                    }
                }
            }
        }
    }
    
    post {
        always {
            echo 'Pipeline completed'
        }
        success {
            echo 'Deployment successful!'
        }
        failure {
            echo 'Deployment failed. Check the logs for details.'
        }
    }
}
