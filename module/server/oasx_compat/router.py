# This Python file uses the following encoding: utf-8
"""
OASX 兼容层路由汇总

- 阶段 1：配置 / 任务的导入导出（config_transfer.py）——已完成
- 阶段 2：日志接口（log_api.py）——待实现
- 阶段 3：统计接口（stats_api.py）——待实现

方案见工作区文档 OASX-compat-plan.md
"""
from fastapi import APIRouter

from module.server.oasx_compat.config_transfer import config_transfer_app

oasx_app = APIRouter()
oasx_app.include_router(config_transfer_app)
