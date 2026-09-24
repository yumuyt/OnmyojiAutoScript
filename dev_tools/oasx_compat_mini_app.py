"""只挂载 OASX 兼容层的迷你服务，用于在不打扰用户正在运行的 OAS 的前提下做日志接口实测"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from fastapi import FastAPI

from module.server.oasx_compat import oasx_app

app = FastAPI()
app.include_router(oasx_app)

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=22289, log_level='warning')
