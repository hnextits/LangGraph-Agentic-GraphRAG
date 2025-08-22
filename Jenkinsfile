pipeline {
    agent any

    stages {
        stage('Copy Files') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            # 파일 복사
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 "mkdir -p /home/nextits4/workspace/quantas && rm -rf /home/nextits4/workspace/quantas/*"
                            scp -o StrictHostKeyChecking=no -P 2226 -r ./* nextits4@127.0.0.1:/home/nextits4/workspace/quantas/
                        '''
                    }
                }
            }
        }
        
        stage('Setup Environment') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                cd /home/nextits4/workspace/quantas
                                
                                echo "=== Installing process tools ==="
                                sudo dnf install -y procps-ng 2>/dev/null || echo "procps install failed or already installed"
                                
                                echo "=== Environment Setup ==="
                                if [ -f /opt/conda/bin/activate ]; then
                                    source /opt/conda/bin/activate quantas
                                    echo "Conda environment activated"
                                else
                                    echo "Using system Python"
                                    which python3
                                fi
                                
                                echo "=== Stopping existing processes ==="
                                pgrep -f "python.*main.py" | xargs -r kill -9 || true
                                pgrep -f "npm.*start" | xargs -r kill -9 || true
                                sleep 2
                                echo "Process cleanup completed"
                            '
                        '''
                    }
                }
            }
        }
        
        stage('Start Backend') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                cd /home/nextits4/workspace/quantas
                                
                                if [ -f /opt/conda/bin/activate ]; then
                                    source /opt/conda/bin/activate quantas
                                fi
                                
                                echo "=== Starting backend ==="
                                if [ -f backend/main.py ]; then
                                    cd backend
                                    pip install uvicorn fastapi python-multipart || echo "Dependencies already installed"
                                    nohup python main.py > /tmp/backend.log 2>&1 &
                                    echo "Backend started with PID: $!"
                                    cd ..
                                    sleep 3
                                    echo "Backend startup completed"
                                else
                                    echo "Backend main.py not found"
                                fi
                            '
                        '''
                    }
                }
            }
        }
        
        stage('Start Frontend') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                cd /home/nextits4/workspace/quantas
                                
                                echo "=== Starting frontend ==="
                                if [ -f frontend/package.json ]; then
                                    cd frontend
                                    
                                    # .env 파일 생성
                                    cat > .env << EOF
REACT_APP_API_URL=http://127.0.0.1:8502
REACT_APP_ENV=production
EOF
                                    
                                    if command -v npm >/dev/null 2>&1; then
                                        if [ ! -d node_modules ]; then
                                            echo "Installing npm dependencies..."
                                            timeout 300 npm install || echo "npm install timeout or failed"
                                        fi
                                        nohup npm start > /tmp/frontend.log 2>&1 &
                                        echo "Frontend started with PID: $!"
                                    else
                                        echo "npm not found"
                                    fi
                                    cd ..
                                else
                                    echo "Frontend package.json not found"
                                fi
                            '
                        '''
                    }
                }
            }
        }
        
        stage('Verify Deployment') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                echo "=== Process Status Check ==="
                                sleep 5
                                
                                BACKEND_COUNT=$(pgrep -f "python.*main.py" | wc -l)
                                FRONTEND_COUNT=$(pgrep -f "npm.*start" | wc -l)
                                
                                echo "Backend processes: $BACKEND_COUNT"
                                echo "Frontend processes: $FRONTEND_COUNT"
                                
                                echo "=== Port Status ==="
                                if command -v ss >/dev/null 2>&1; then
                                    ss -tlnp | grep ":8502" && echo "Backend port 8502 active" || echo "Backend port 8502 not active"
                                    ss -tlnp | grep ":8503" && echo "Frontend port 8503 active" || echo "Frontend port 8503 not active"
                                fi
                                
                                echo "=== Logs ==="
                                if [ -f /tmp/backend.log ]; then
                                    echo "Backend log (last 3 lines):"
                                    tail -n 3 /tmp/backend.log
                                fi
                                
                                if [ -f /tmp/frontend.log ]; then
                                    echo "Frontend log (last 3 lines):"
                                    tail -n 3 /tmp/frontend.log
                                fi
                                
                                echo "=== Access URLs ==="
                                echo "Backend: http://127.0.0.1:8502"
                                echo "Frontend: http://127.0.0.1:8503"
                            '
                        '''
                    }
                }
            }
        }
    }
    
    post {
        success {
            echo 'Deployment successful!'
            echo '================================'
            echo 'Access your application at:'
            echo 'Frontend: http://127.0.0.1:8503'
            echo 'Backend API: http://127.0.0.1:8502'
            echo 'API Docs: http://127.0.0.1:8502/docs'
            echo '================================'
        }
        failure {
            echo 'Deployment failed. Check individual stage logs.'
        }
    }
}
