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
        PROD_BACKEND_PORT = '8501'
        PROD_FRONTEND_PORT = '8502'
        
        // Conda 환경명
        TEST_CONDA_ENV = 'test_server'
        PROD_CONDA_ENV = 'prod'
        
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
                            echo "⚠️ DEV 브랜치는 자동 배포하지 않습니다. 빌드를 건너뜁니다."
                            currentBuild.result = 'NOT_BUILT'
                            return
                        }
                        env.AUTO_TEST_DEPLOY = 'false'
                        env.CURRENT_ACTION = params.ACTION
                        if (params.ACTION != 'TEST_DEPLOY' && params.ACTION != 'DEV_TO_PROD_DEPLOY') {
                            error "DEV 브랜치에서는 TEST_DEPLOY 또는 DEV_TO_PROD_DEPLOY만 허용됩니다."
                        }
                    } else if (currentBranch.startsWith('test') || currentBranch.startsWith('TEST')) {
                        if (isWebhookTrigger || params.AUTO_DEPLOY_TEST) {
                            env.AUTO_TEST_DEPLOY = 'true'
                            env.CURRENT_ACTION = 'TEST_DEPLOY'
                        } else {
                            env.AUTO_TEST_DEPLOY = 'false'
                            env.CURRENT_ACTION = params.ACTION
                        }
                    } else if (currentBranch == 'main' || currentBranch == 'master') {
                        if (!params.ACTION.startsWith('PROD_')) {
                            error "MAIN 브랜치에서는 PROD_* 액션만 허용됩니다."
                        }
                        env.AUTO_TEST_DEPLOY = 'false'
                        env.CURRENT_ACTION = params.ACTION
                    } else {
                        error "지원하지 않는 브랜치입니다: ${currentBranch}"
                    }
                }
            }
        }

        stage('Push DEV to TEST') {
            when { 
                allOf {
                    anyOf {
                        expression { env.CURRENT_ACTION == 'TEST_DEPLOY' }
                        expression { env.CURRENT_ACTION == 'DEV_TO_PROD_DEPLOY' }
                    }
                    expression { 
                        def currentBranch = env.BRANCH_NAME ?: env.GIT_BRANCH?.replace('origin/', '') ?: 'unknown'
                        return currentBranch.startsWith('dev') || currentBranch.startsWith('DEV')
                    }
                }
            }
            steps {
                script {
                    echo "🔀 DEV → TEST 브랜치 푸시 시작..."
                    def gitUrl = scm.getUserRemoteConfigs()[0].getUrl()
                    withCredentials([string(credentialsId: 'github-pat', variable: 'GITHUB_TOKEN')]) {
                        sh """
                            git config user.name "Jenkins CI"
                            git config user.email "jenkins@nextits.com"
                            GIT_URL_WITH_PAT=\$(echo "${gitUrl}" | sed "s|https://|https://\${GITHUB_TOKEN}@|")
                            git remote set-url origin "\$GIT_URL_WITH_PAT"
                            git fetch origin --prune
                            git push origin HEAD:TEST --force
                        """
                        slackSend(channel: env.SLACK_CHANNEL, color: 'good', message: "🔀 [${env.JOB_NAME}] DEV → TEST 푸시 완료", tokenCredentialId: env.SLACK_CREDENTIAL_ID)
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
                anyOf {
                    expression { env.CURRENT_ACTION == 'PROD_DEPLOY' }
                    expression { env.CURRENT_ACTION == 'DEV_TO_PROD_DEPLOY' }
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
                            git checkout main || git checkout master
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
                    def deployBranch = isTestServer ? 'TEST' : 'main'
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
                    expression { env.CURRENT_ACTION.endsWith('_DEPLOY') }
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
                            ssh -p ${port} ${user}@${server} << 'EOF'
                                cd ${workspace}
                                source \$(conda info --base)/etc/profile.d/conda.sh
                                conda activate ${condaEnv} || (conda create -n ${condaEnv} python=3.9 -y && conda activate ${condaEnv})
                                
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

                                # Backend 시작
                                cd backend
                                pip install -r requirements.txt --quiet
                                PORT=\$B_PORT nohup python main.py > /tmp/backend.log 2>&1 &
                                
                                # Frontend 시작
                                cd ../frontend
                                npm install --silent
                                if [ "${isTestServer}" = "true" ]; then
                                    PORT=\$F_PORT nohup npm run dev > /tmp/frontend.log 2>&1 &
                                else
                                    npm run build
                                    PORT=\$F_PORT nohup npm run start > /tmp/frontend.log 2>&1 &
                                fi
                            EOF
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
                    expression { env.CURRENT_ACTION.endsWith('_DEPLOY') }
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
                            ssh -p ${port} ${user}@${server} << 'EOF'
                                echo "=== Health Check (10s wait) ==="
                                sleep 10
                                if [ "${isTestServer}" = "true" ]; then
                                    echo "테스트 서버 활성 여부 확인 중..."
                                    netstat -tln | grep -E ":(${env.TEST_BACKEND_PORT_MIN}|${env.TEST_BACKEND_PORT_MAX}|${env.TEST_FRONTEND_PORT_MIN}|${env.TEST_FRONTEND_PORT_MAX})"
                                else
                                    curl -s http://localhost:${env.PROD_BACKEND_PORT} > /dev/null && echo "✅ Backend OK" || echo "❌ Backend Fail"
                                    curl -s http://localhost:${env.PROD_FRONTEND_PORT} > /dev/null && echo "✅ Frontend OK" || echo "❌ Frontend Fail"
                                fi
                            EOF
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
