from fastapi import APIRouter

api_router = APIRouter()

from .routes import *  # 모든 라우트 가져오기
