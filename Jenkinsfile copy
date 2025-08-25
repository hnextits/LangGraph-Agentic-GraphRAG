pipeline {
    agent any

    stages {
        stage('Deploy Files') {
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
        
        stage('Start Services') {
            steps {
                sshagent(credentials: ['nextits_ai_4_ssh']) {
                    script {
                        sh '''
                            ssh -o StrictHostKeyChecking=no -p 2226 nextits4@127.0.0.1 '
                                cd /home/nextits4/workspace/quantas
                                
                                echo "=== Environment Setup ==="
                                if [ -f /opt/conda/bin/activate ]; then
                                    source /opt/conda/bin/activate quantas
                                    echo "Conda activated"
                                fi
                                
                                echo "=== Cleanup existing services ==="
                                # 간단한 포트 기반 정리
                                lsof -ti:8502 | xargs -r kill -9 2>/dev/null || true
                                lsof -ti:8503 | xargs -r kill -9 2>/dev/null || true
                                sleep 2
                                
                                echo "=== Starting Backend ==="
                                if [ -f backend/main.py ]; then
                                    cd backend
                                    pip install uvicorn fastapi python-multipart --quiet || echo "Deps install failed"
                                    nohup python main.py > /tmp/backend.log 2>&1 &
                                    echo "Backend started"
                                    cd ..
                                    sleep 3
                                fi
                                
                                echo "=== Starting Frontend ==="
                                if [ -f frontend/package.json ]; then
                                    cd frontend
                                    
                                    # .env 생성
                                    echo "REACT_APP_API_URL=http://127.0.0.1:8502" > .env
                                    echo "REACT_APP_ENV=production" >> .env
                                    
                                    if command -v npm >/dev/null; then
                                        [ ! -d node_modules ] && npm install --silent
                                        nohup npm start > /tmp/frontend.log 2>&1 &
                                        echo "Frontend started"
                                    fi
                                    cd ..
                                fi
                                
                                echo "=== Services started ==="
                                sleep 5
                                
                                # 포트 확인
                                lsof -i:8502 && echo "Backend port active" || echo "Backend port inactive"
                                lsof -i:8503 && echo "Frontend port active" || echo "Frontend port inactive"
                                
                                echo "=== Deployment Complete ==="
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
            echo '🎉 Deployment Successful!'
            echo '================================'
            echo 'Access your application:'
            echo 'Frontend: http://127.0.0.1:8503'
            echo 'Backend: http://127.0.0.1:8502'
            echo 'API Docs: http://127.0.0.1:8502/docs'
            echo '================================'
        }
        failure {
            echo '❌ Deployment failed. Check logs above.'
        }
    }
}
