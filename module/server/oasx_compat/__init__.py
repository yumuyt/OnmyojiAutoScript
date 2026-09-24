# This Python file uses the following encoding: utf-8
"""
OASX 面板兼容层（第三方面板 OASX 需要的、而本仓库上游暂时没有的接口）

设计约束（很重要，请不要破坏）：
1. 本目录下的所有代码都是**新增**的，不修改 module/server/ 下任何上游文件；
2. 上游文件只允许在 module/server/app.py 里加 2 行注册代码；
3. 不引入新的第三方依赖（requirements.txt 保持不动）。

这样以后 `git rebase upstream/dev` 时冲突面最小。
"""
from module.server.oasx_compat.router import oasx_app

__all__ = ['oasx_app']
