# This Python file uses the following encoding: utf-8
"""
OASX 兼容层路由汇总

- 阶段 1：配置 / 任务的导入导出（config_transfer.py）——已完成
- 阶段 2：日志接口（log_api.py）——已完成
- 阶段 3：统计接口（stats_api.py）——已完成

方案见工作区文档 OASX-compat-plan.md
"""
from fastapi import APIRouter

from module.server.oasx_compat.config_transfer import config_transfer_app
from module.server.oasx_compat.log_api import error_log_app, log_app
from module.server.oasx_compat.stats_api import stats_app

oasx_app = APIRouter()
oasx_app.include_router(config_transfer_app)
# 顺序要紧：/logs/errors* 必须在 /logs/{script_name} 之前注册
oasx_app.include_router(error_log_app)
oasx_app.include_router(log_app)
oasx_app.include_router(stats_app)
