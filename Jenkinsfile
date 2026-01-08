pipeline {
    agent any
    
    parameters {
        choice(
            name: 'ACTION',
            choices: [
                'TEST_DEPLOY',          // 테스트 서버 배포 (코드만)
                'TEST_START',           // 테스트 서버 시작
                'TEST_STOP',            // 테스트 서버 중지
                'TEST_RESTART',         // 테스트 서버 재시작
                'PROD_DEPLOY',          // 운영서버 배포 (코드만)
                'PROD_START',           // 운영서버 시작
                'PROD_STOP',            // 운영서버 중지
                'PROD_RESTART',         // 운영서버 재시작
                'DEV_TO_PROD_DEPLOY'    // DEV → PROD 직접 배포 (긴급 배포용)
            ],
            description: 'Select action to perform'
        )
        booleanParam(
            name: 'AUTO_DEPLOY_TEST', 
            defaultValue: false, 
            description: 'Auto deploy to test server (for DEV branch commits)'
        )
    }

    environment {
        // Git 저장소 이름 동적 추출
        REPO_NAME = scm.getUserRemoteConfigs()[0].getUrl().tokenize('/').last().replaceAll("\\.git", '')

        // 테스트 서버 정보
        TEST_SERVER = '127.0.0.1'
        TEST_PORT = '2226'
        TEST_USER = 'nextits_test'
        TEST_WORKSPACE = "/home/${TEST_USER}/workspace/${REPO_NAME}"
        
        // 테스트 서버 포트 범위
        TEST_FRONTEND_PORT_MIN = '6007'
        TEST_FRONTEND_PORT_MAX = '6012'
        TEST_BACKEND_PORT_MIN = '5007'
        TEST_BACKEND_PORT_MAX = '5012'
        
        // 운영 서버 정보
        PROD_SERVER = '127.0.0.1'
        PROD_PORT = '2223'
        PROD_USER = 'nextits'
        PROD_WORKSPACE = "/home/${PROD_USER}/workspace/${REPO_NAME}"
        PROD_BACKEND_PORT = '5004'
        PROD_FRONTEND_PORT = '8504'
        
        // Conda 환경명 및 Python 버전
        TEST_CONDA_ENV = 'test_server'
        PROD_CONDA_ENV = 'space'
        PYTHON_VERSION = '3.11'
        
        // SSH Credentials
        TEST_SSH_CREDENTIAL = 'nextits_ai_4_ssh'
        PROD_SSH_CREDENTIAL = 'nextits_ai_4_ssh'

        // Slack 정보
        SLACK_CHANNEL = '#workflow'
        SLACK_CREDENTIAL_ID = 'slack_nextits'
    }

    stages {
        stage('Branch Detection & Auto Deploy') {
            steps {
                script {
                    def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                    echo "Current branch: ${currentBranch}"
                    echo "Selected ACTION: ${params.ACTION}"
                    
                    def buildCause = currentBuild.getBuildCauses()[0]?._class ?: ''
                    def isWebhookTrigger = buildCause.contains('GitHubPushCause') || buildCause.contains('SCMTrigger')
                    def isManualTrigger = buildCause.contains('UserIdCause')
                    
                    echo "빌드 트리거: ${isWebhookTrigger ? 'Git Push (Webhook)' : isManualTrigger ? '수동 실행' : '기타'}"
                    
                    if (currentBranch.startsWith('dev') || currentBranch.startsWith('DEV')) {
                        if (isWebhookTrigger) {
                            echo "⚠️ DEV 브랜치 푸시는 아무런 행동을 수행하지 않습니다."
                            currentBuild.result = 'NOT_BUILT'
                            return
                        }
                        env.CURRENT_ACTION = params.ACTION
                    } else if (currentBranch.startsWith('test') || currentBranch.startsWith('TEST')) {
                        env.CURRENT_ACTION = isWebhookTrigger ? 'TEST_DEPLOY' : params.ACTION
                        echo "🚀 TEST 브랜치 액션: ${env.CURRENT_ACTION}"
                    } else if (currentBranch == 'main' || currentBranch == 'master' || currentBranch == 'MAIN' || currentBranch == 'MASTER') {
                        env.CURRENT_ACTION = isWebhookTrigger ? 'PROD_DEPLOY' : params.ACTION
                        echo "🚀 MAIN 브랜치 액션: ${env.CURRENT_ACTION}"
                    } else {
                        // 기본적으로 수동 실행인 경우 파라미터 액션을 따름
                        if (isManualTrigger) {
                            env.CURRENT_ACTION = params.ACTION
                            echo "🚀 수동 실행 액션 (${currentBranch}): ${env.CURRENT_ACTION}"
                        } else {
                            error "지원하지 않는 브랜치입니다: ${currentBranch}"
                        }
                    }
                }
            }
        }

        stage('Push DEV to MAIN') {
            when { 
                allOf {
                    expression { env.CURRENT_ACTION == 'DEV_TO_PROD_DEPLOY' }
                    expression { 
                        def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                        return currentBranch.startsWith('dev') || currentBranch.startsWith('DEV')
                    }
                }
            }
            steps {
                script {
                    echo "🔀 DEV → MAIN 브랜치 직접 푸시 시작..."
                    def gitUrl = scm.getUserRemoteConfigs()[0].getUrl()
                    withCredentials([string(credentialsId: 'github-pat', variable: 'GITHUB_TOKEN')]) {
                        sh """
                            git config user.name "Jenkins CI"
                            git config user.email "jenkins@nextits.com"
                            GIT_URL_WITH_PAT=\$(echo "${gitUrl}" | sed "s|https://|https://\${GITHUB_TOKEN}@|")
                            git remote set-url origin "\$GIT_URL_WITH_PAT"
                            git fetch origin --prune
                            git push origin HEAD:refs/heads/MAIN --force
                        """
                        slackSend(channel: env.SLACK_CHANNEL, color: 'good', message: "🔀 [${env.JOB_NAME}] DEV → MAIN 직접 푸시 완료", tokenCredentialId: env.SLACK_CREDENTIAL_ID)
                    }
                }
            }
        }

        stage('Production Deploy Validation') {
            when { 
                anyOf {
                    expression { env.CURRENT_ACTION == 'PROD_DEPLOY' }
                    expression { env.CURRENT_ACTION == 'DEV_TO_PROD_DEPLOY' }
                }
            }
            steps {
                script {
                    timeout(time: 10, unit: 'MINUTES') {
                        def approval = input(
                            message: '운영서버 배포를 진행하시겠습니까?',
                            ok: '배포 승인',
                            parameters: [
                                booleanParam(name: 'DEPLOYMENT_CONFIRMED', defaultValue: false, description: '배포를 확인했습니다'),
                                string(name: 'DEPLOYER_NAME', defaultValue: '', description: '배포자 이름 입력')
                            ]
                        )
                        if (!approval.DEPLOYMENT_CONFIRMED || !approval.DEPLOYER_NAME) {
                            error "운영서버 배포가 취소되었습니다."
                        }
                        env.DEPLOYER_NAME = approval.DEPLOYER_NAME
                    }
                }
            }
        }

        stage('Merge TEST to MAIN') {
            when { 
                allOf {
                    expression { env.CURRENT_ACTION == 'PROD_DEPLOY' }
                    expression { 
                        def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                        return currentBranch.startsWith('test') || currentBranch.startsWith('TEST')
                    }
                }
            }
            steps {
                script {
                    def gitUrl = scm.getUserRemoteConfigs()[0].getUrl()
                    withCredentials([string(credentialsId: 'github-pat', variable: 'GITHUB_TOKEN')]) {
                        sh """
                            GIT_URL_WITH_PAT=\$(echo "${gitUrl}" | sed "s|https://|https://\${GITHUB_TOKEN}@|")
                            TEMP_DIR=\$(mktemp -d)
                            git clone "\$GIT_URL_WITH_PAT" \$TEMP_DIR/repo
                            cd \$TEMP_DIR/repo
                            git config user.email "jenkins@nextits.com"
                            git config user.name "Jenkins CI"
                            git checkout MAIN
                            git merge origin/TEST --no-commit --no-ff
                            git commit -m "Merge TEST to MAIN for production deployment by ${env.DEPLOYER_NAME}"
                            git push origin HEAD
                            rm -rf \$TEMP_DIR
                        """
                        slackSend(channel: env.SLACK_CHANNEL, color: 'good', message: "🔀 [${env.JOB_NAME}] TEST → MAIN 머지 완료", tokenCredentialId: env.SLACK_CREDENTIAL_ID)
                    }
                }
            }
        }

        stage('Deploy Files (Git Sync)') {
            when {
                expression { env.CURRENT_ACTION.endsWith('_DEPLOY') }
            }
            steps {
                script {
                    def isTestServer = env.CURRENT_ACTION.startsWith('TEST_')
                    def targetServer = isTestServer ? env.TEST_SERVER : env.PROD_SERVER
                    def targetPort = isTestServer ? env.TEST_PORT : env.PROD_PORT
                    def targetUser = isTestServer ? env.TEST_USER : env.PROD_USER
                    def targetWorkspace = isTestServer ? env.TEST_WORKSPACE : env.PROD_WORKSPACE
                    def sshCredential = isTestServer ? env.TEST_SSH_CREDENTIAL : env.PROD_SSH_CREDENTIAL
                    def deployBranch = isTestServer ? 'TEST' : 'MAIN'
                    def gitUrl = scm.getUserRemoteConfigs()[0].getUrl()

                    withCredentials([string(credentialsId: 'github-pat', variable: 'GITHUB_TOKEN')]) {
                        def deployScript = """
                            set -e
                            GIT_URL_WITH_PAT=\$(echo "${gitUrl}" | sed "s|https://|https://\${GITHUB_TOKEN}@|")
                            if [ -d "${targetWorkspace}/.git" ]; then
                                cd "${targetWorkspace}"
                                git remote set-url origin "\$GIT_URL_WITH_PAT"
                                git fetch origin --force --prune
                                git reset --hard origin/${deployBranch}
                                git clean -fd
                            else
                                mkdir -p "${targetWorkspace}"
                                git clone -b ${deployBranch} "\$GIT_URL_WITH_PAT" "${targetWorkspace}"
                            fi
                        """
                        writeFile file: 'deploy.sh', text: deployScript
                        sshagent(credentials: [sshCredential]) {
                            sh "scp -P ${targetPort} deploy.sh ${targetUser}@${targetServer}:/tmp/deploy.sh"
                            sh "ssh -p ${targetPort} ${targetUser}@${targetServer} 'GITHUB_TOKEN=${GITHUB_TOKEN} bash /tmp/deploy.sh'"
                        }
                    }
                }
            }
        }

        stage('Server Operations') {
            when {
                anyOf {
                    expression { env.CURRENT_ACTION.endsWith('_START') }
                    expression { env.CURRENT_ACTION.endsWith('_RESTART') }
                    expression { env.CURRENT_ACTION == 'PROD_DEPLOY' } // PROD_DEPLOY만 서버 작업 포함
                    expression { env.CURRENT_ACTION == 'TEST_DEPLOY' } // TEST_DEPLOY만 서버 작업 포함
                    expression { env.CURRENT_ACTION.endsWith('_STOP') }
                }
            }
            steps {
                script {
                    def isTestServer = env.CURRENT_ACTION.startsWith('TEST_')
                    def server = isTestServer ? env.TEST_SERVER : env.PROD_SERVER
                    def port = isTestServer ? env.TEST_PORT : env.PROD_PORT
                    def user = isTestServer ? env.TEST_USER : env.PROD_USER
                    def workspace = isTestServer ? env.TEST_WORKSPACE : env.PROD_WORKSPACE
                    def condaEnv = isTestServer ? env.TEST_CONDA_ENV : env.PROD_CONDA_ENV
                    def sshCredential = isTestServer ? env.TEST_SSH_CREDENTIAL : env.PROD_SSH_CREDENTIAL
                    def isStop = env.CURRENT_ACTION.endsWith('_STOP')

                    sshagent(credentials: [sshCredential]) {
                        sh """
                            ssh -tt -o BatchMode=yes -p ${port} ${user}@${server} << 'REMOTEEFFECT'
                                # 워크스페이스로 확실하게 이동
                                cd "${workspace}" || { echo "❌ 워크스페이스 이동 실패: ${workspace}"; exit 1; }
                                
                                # 1. Conda 초기화 및 환경 리스트 확인
                                export PATH="/home/${user}/anaconda3/bin:/home/${user}/miniconda3/bin:\$PATH"
                                CONDA_BASE=\$(conda info --base 2>/dev/null || echo "")
                                if [ -z "\$CONDA_BASE" ]; then
                                    echo "❌ Conda를 찾을 수 없습니다. 설치 경로를 확인해주세요."
                                    exit 1
                                fi
                                
                                source "\$CONDA_BASE/etc/profile.d/conda.sh"
                                
                                # 2. 지정된 Conda 환경 존재 여부 확인 및 생성
                                if ! conda env list | grep -q "^${condaEnv} "; then
                                    echo "🚀 ${condaEnv} 환경 생성 중... (Python ${env.PYTHON_VERSION})"
                                    conda create -n ${condaEnv} python=${env.PYTHON_VERSION} -y || exit 1
                                fi
                                
                                # 3. Conda 환경 활성화
                                conda activate ${condaEnv} || exit 1
                                
                                # 포트 결정
                                if [ "${isTestServer}" = "true" ]; then
                                    B_PORT=\$(for p in \$(seq ${env.TEST_BACKEND_PORT_MIN} ${env.TEST_BACKEND_PORT_MAX}); do if ! netstat -tln | grep -q ":\$p "; then echo \$p; break; fi; done)
                                    F_PORT=\$(for p in \$(seq ${env.TEST_FRONTEND_PORT_MIN} ${env.TEST_FRONTEND_PORT_MAX}); do if ! netstat -tln | grep -q ":\$p "; then echo \$p; break; fi; done)
                                else
                                    B_PORT=${env.PROD_BACKEND_PORT}
                                    F_PORT=${env.PROD_FRONTEND_PORT}
                                fi

                                # 프로세스 정리
                                lsof -ti:\$B_PORT | xargs -r kill -9 || true
                                lsof -ti:\$F_PORT | xargs -r kill -9 || true
                                
                                if [ "${isStop}" = "true" ]; then
                                    echo "✅ 서버 중지 완료"
                                    exit 0
                                fi

                                # 4. Backend 빌드 및 Poetry 인스톨
                                # 프로젝트 루트(pyproject.toml 위치)에서 실행
                                if ! command -v \$HOME/.local/bin/poetry &> /dev/null; then
                                    curl -sSL https://install.python-poetry.org | python3 -
                                fi
                                POETRY_BIN="\$HOME/.local/bin/poetry"
                                
                                \$POETRY_BIN config virtualenvs.create false
                                echo "📦 의존성 설치 중..."
                                \$POETRY_BIN install --only main --quiet
                                
                                # 5. 실행
                                cd backend || { echo "❌ backend 디렉토리 미발견"; exit 1; }
                                echo "🚀 Backend 실행 중 (Port: \$B_PORT)..."
                                # nohup과 & 를 사용하여 백그라운드 실행 시, stdout/stderr를 파일로 리다이렉트하고 
                                # 프로세스 그룹을 분리하여 Jenkins 세션 종료 시 같이 종료되지 않게 함
                                PORT=\$B_PORT nohup python main.py > /tmp/backend.log 2>&1 &
                                sleep 2 # 프로세스가 시작될 시간을 줌
                                disown
                                
                                # Frontend 시작
                                cd ../frontend || { echo "❌ frontend 디렉토리 미발견"; exit 1; }
                                echo "📦 Frontend 의존성 설치 및 빌드 중..."
                                npm install --silent
                                
                                if [ "${isTestServer}" = "false" ] && [ "${env.CURRENT_ACTION.endsWith('_DEPLOY')}" = "true" ]; then
                                    npm run build
                                fi
                                
                                if [ "${isTestServer}" = "true" ]; then
                                    PORT=\$F_PORT nohup npm run dev > /tmp/frontend.log 2>&1 &
                                else
                                    PORT=\$F_PORT nohup npm run start > /tmp/frontend.log 2>&1 &
                                fi
                                sleep 2 # 프로세스가 시작될 시간을 줌
                                disown
                                
                                echo "✅ 서버 프로세스 실행 명령 전송 완료 (Backend: \$B_PORT, Frontend: \$F_PORT)"
                                exit 0
REMOTEEFFECT
                        """
                    }
                }
            }
        }

        stage('Health Check') {
            when {
                anyOf {
                    expression { env.CURRENT_ACTION.endsWith('_START') }
                    expression { env.CURRENT_ACTION.endsWith('_RESTART') }
                    // 수동 DEPLOY 시에만 헬스체크 수행 (DEV_TO_PROD_DEPLOY 제외)
                    expression { 
                        (env.CURRENT_ACTION == 'PROD_DEPLOY' || env.CURRENT_ACTION == 'TEST_DEPLOY') && 
                        currentBuild.getBuildCauses()[0]?._class.contains('UserIdCause') 
                    }
                }
            }
            steps {
                script {
                    def isTestServer = env.CURRENT_ACTION.startsWith('TEST_')
                    def server = isTestServer ? env.TEST_SERVER : env.PROD_SERVER
                    def port = isTestServer ? env.TEST_PORT : env.PROD_PORT
                    def user = isTestServer ? env.TEST_USER : env.PROD_USER
                    
                    sshagent(credentials: [isTestServer ? env.TEST_SSH_CREDENTIAL : env.PROD_SSH_CREDENTIAL]) {
                        sh """
                            ssh -p ${port} ${user}@${server} << 'REMOTEEFFECT'
                                echo "=== Health Check (10s wait) ==="
                                sleep 10
                                if [ "${isTestServer}" = "true" ]; then
                                    echo "테스트 서버 활성 여부 확인 중..."
                                    netstat -tln | grep -E ":(${env.TEST_BACKEND_PORT_MIN}|${env.TEST_BACKEND_PORT_MAX}|${env.TEST_FRONTEND_PORT_MIN}|${env.TEST_FRONTEND_PORT_MAX})"
                                else
                                    curl -s http://localhost:${env.PROD_BACKEND_PORT} > /dev/null && echo "✅ Backend OK" || echo "❌ Backend Fail"
                                    curl -s http://localhost:${env.PROD_FRONTEND_PORT} > /dev/null && echo "✅ Frontend OK" || echo "❌ Frontend Fail"
                                fi
REMOTEEFFECT
                        """
                    }
                }
            }
        }
    }

    post {
        always {
            script {
                def color = currentBuild.currentResult == 'SUCCESS' ? 'good' : 'danger'
                slackSend(channel: env.SLACK_CHANNEL, color: color, message: "🔔 [${env.JOB_NAME}] 빌드 결과: ${currentBuild.currentResult}\n- 액션: ${env.CURRENT_ACTION}\n- <${env.BUILD_URL}|빌드 로그 보기>", tokenCredentialId: env.SLACK_CREDENTIAL_ID)
            }
        }
        success {
            script {
                echo "🎉 ${env.CURRENT_ACTION} 성공!"
                if (env.CURRENT_ACTION.startsWith('TEST_DEPLOY')) {
                    echo "테스트 서버 배포 완료. 브랜치별 Conda 환경과 동적 포트가 할당되었습니다."
                } else if (env.CURRENT_ACTION == 'PROD_DEPLOY') {
                    echo "운영 서버 배포 완료. 배포자: ${env.DEPLOYER_NAME ?: 'Unknown'}"
                }
            }
        }
        failure {
            script {
                echo "❌ ${env.CURRENT_ACTION} 실패!"
                def isTestServer = env.CURRENT_ACTION?.startsWith('TEST_')
                def targetServer = isTestServer ? env.TEST_SERVER : env.PROD_SERVER
                def targetPort = isTestServer ? env.TEST_PORT : env.PROD_PORT
                def targetUser = isTestServer ? env.TEST_USER : env.PROD_USER
                
                echo "디버깅 정보: ssh -p ${targetPort} ${targetUser}@${targetServer}"
                if (isTestServer) {
                    echo "테스트 로그: /tmp/test_backend_[PORT].log"
                } else {
                    echo "운영 로그: /tmp/prod_backend.log"
                }
            }
        }
    }
}
