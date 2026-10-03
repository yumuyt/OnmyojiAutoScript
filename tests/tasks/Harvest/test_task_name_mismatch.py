# -*- coding: utf-8 -*-
"""
D 修复: 任务内部复用别的任务类时(例如 Restart 登录后调 HarvestHandler 收菜),
get_task_name() 只警告、按类自己的名字取皮肤, 不再 raise ScriptError。

背景(2026-10-03 20:06 / 20:15):
上游 Costume 提交(本地 ae146342 <- 上游 08079eaf)新增了 get_task_name() 里
"model 任务名 != 类所在目录名" 就 raise ScriptError 的检查。而 Restart 登录后会去
tasks/Harvest 里收菜(running_task=Restart, 类在 tasks/Harvest) -> 抛错 ->
script.py 的 `except ScriptError` 直接 exit(1) -> oas1/oas2 两个实例整个进程退出。
"""
from types import SimpleNamespace

from tasks.Harvest.script_task import ScriptTask as HarvestScriptTask


class FakeHarvestTask:
    """借 Harvest 的 get_task_name; 本测试文件本身就在 tests/tasks/Harvest/ 下,
    所以 inspect.getfile(type(self)) 得到的父目录名是 Harvest。"""

    get_task_name = HarvestScriptTask.get_task_name


def make_task(running_task):
    task = FakeHarvestTask()
    task.config = SimpleNamespace(model=SimpleNamespace(running_task=running_task))
    return task


def test_running_task_mismatch_only_warns():
    """running_task=Restart 时不再抛错, 且用类自己的名字(Harvest)取皮肤"""
    assert make_task('Restart').get_task_name() == 'Harvest'


def test_running_task_same_name_ok():
    assert make_task('Harvest').get_task_name() == 'Harvest'


def test_running_task_empty_falls_back_to_class_name():
    assert make_task('').get_task_name() == 'Harvest'
