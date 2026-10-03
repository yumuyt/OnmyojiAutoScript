# This Python file uses the following encoding: utf-8
"""收菜任务从重启页独立出来 / 重启定时开关 的相关测试

背景(用户反馈):
1. 重启的时间设置没意义: 重启多用于任务卡死后的恢复, 却被"勾选启用就必须设时间"绑住
2. 收菜设置挂在重启页里, 应该独立出来

这里只测纯逻辑(配置结构 / 迁移 / 排程), 不碰设备。
"""
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from module.config.config_model import ConfigModel
from tasks.Harvest.config import Harvest
from tasks.Harvest.config_scheduler import HarvestScheduler
from tasks.Restart.config import Restart
from tasks.Restart.config_scheduler import RestartScheduler

CONFIG_DIR = Path(__file__).resolve().parents[3] / 'config'


@pytest.fixture(autouse=True, scope='module')
def _isolated_config_dir(tmp_path_factory):
    """把工作目录换到临时目录, 里面放一份 config 的副本

    Config/ConfigModel 都是按 Path.cwd() / 'config' / '<name>.json' 读写配置的,
    而它们到处会自动 save(比如 ConfigModel.__setattr__)。不隔离的话跑一次测试就会
    把真实的 config/template.json 重写一遍(踩过一次: 255 增 69 删)。
    chdir 能挡住所有这样的写, 不用一个个去 patch。
    """
    workdir = tmp_path_factory.mktemp('oas_test_cwd')
    shutil.copytree(CONFIG_DIR, workdir / 'config')
    old_cwd = Path.cwd()
    import os
    os.chdir(workdir)
    try:
        yield workdir
    finally:
        os.chdir(old_cwd)
REPO_DIR = Path(__file__).resolve().parents[3]
# OASX 启动时会从后端 GET /home/additional_translate 拉这张运行时中文表并合并进它自己的翻译,
# 所以新增的任务名/字段名/说明 key 必须同时出现在这里, 否则界面上显示英文(或直接显示 key)。
RUNTIME_I18N = REPO_DIR / 'assets' / 'i18n' / 'zh-CN.json'


def _runtime_i18n() -> dict:
    return json.loads(RUNTIME_I18N.read_text(encoding='utf-8'))


# ---------------------------------------------------------------- 重启: 定时开关

def test_restart_has_schedule_switch_and_defaults_off():
    """重启必须有"定时重启"开关, 且默认关闭(默认只做卡死恢复)"""
    assert RestartScheduler.model_fields['schedule'].default is False


def test_restart_page_no_longer_has_harvest_config():
    """收菜设置不该再出现在重启任务的页面结构里"""
    groups = Restart.model_fields
    assert 'harvest_config' not in groups, '重启页里还有收菜设置'
    assert {'scheduler', 'tasks_config_reset', 'login_character_config'} <= set(groups)


def test_restart_schedule_off_does_not_use_server_update():
    """定时重启关闭时, server_update/next_run 都不该参与排程

    ScriptTask.app_restart 关掉定时后直接把下次运行排到一周后, 不再走 server=True 那条路。
    """
    scheduler = RestartScheduler()
    assert scheduler.schedule is False
    source = (Path(__file__).resolve().parents[3] / 'tasks' / 'Restart' / 'script_task.py').read_text(encoding='utf-8')
    assert 'scheduler.schedule' in source
    # 关掉时用的是"一周后"的 target + server=False
    assert 'timedelta(weeks=1)' in source
    assert 'server=False' in source


# ---------------------------------------------------------------- 收菜: 独立任务

def test_harvest_is_a_standalone_task():
    """收菜有自己的配置 / 调度器 / 页面结构"""
    assert set(Harvest.model_fields) == {'scheduler', 'harvest_time', 'harvest_config'}
    assert HarvestScheduler.model_fields['enable'].default is True

    toggles = set(Harvest.model_fields['harvest_config'].annotation.model_fields)
    assert toggles == {
        'enable_courtyard_affairs', 'enable_jade', 'enable_sign', 'enable_sign_999',
        'enable_mail', 'enable_soul', 'enable_ap',
    }


def test_harvest_has_no_scheduler_time_field():
    """收菜时刻是内置时间, 调度器里不该再有"每天几点执行"

    踩过的坑: 原先把它放在调度器里(harvest_time), 页面上多出一行"每天几点执行",
    而且它跟"下一次运行时间"两套语义混在一起。
    """
    assert 'harvest_time' not in HarvestScheduler.model_fields
    assert 'run_time' not in HarvestScheduler.model_fields
    # 内置时间在 harvest_time 这一组里, 每天两次
    harvest_time_cls = Harvest.model_fields['harvest_time'].annotation
    assert set(harvest_time_cls.model_fields) == {'run_time_1', 'run_time_2'}
    assert harvest_time_cls.model_fields['run_time_1'].default.hour == 0
    assert harvest_time_cls.model_fields['run_time_1'].default.minute == 15
    assert harvest_time_cls.model_fields['run_time_2'].default.hour == 20
    assert harvest_time_cls.model_fields['run_time_2'].default.minute == 0


def test_harvest_next_run_follows_builtin_times():
    """内置时间的排期: 今天还没到点就是今天, 否则明天的第一个时刻"""
    from tasks.Component.config_base import Time
    from tasks.Harvest.script_task import ScriptTask

    task = ScriptTask.__new__(ScriptTask)
    task.run_times = lambda: (Time(hour=0, minute=15, second=0), Time(hour=20, minute=0, second=0))

    cases = [
        (datetime(2026, 10, 3, 0, 5, 0), datetime(2026, 10, 3, 0, 15, 0)),
        (datetime(2026, 10, 3, 12, 0, 0), datetime(2026, 10, 3, 20, 0, 0)),
        (datetime(2026, 10, 3, 20, 30, 0), datetime(2026, 10, 4, 0, 15, 0)),
        (datetime(2026, 10, 3, 23, 59, 0), datetime(2026, 10, 4, 0, 15, 0)),
    ]
    for now, expected in cases:
        got = task.next_harvest_time(now)
        assert got == expected, f'{now} 应当排到 {expected}, 实际 {got}'


def test_harvest_next_run_same_time_twice_is_daily():
    """两个时刻配成同一个 -> 等于每天只收一次, 不能死循环/排到过去"""
    from tasks.Component.config_base import Time
    from tasks.Harvest.script_task import ScriptTask

    task = ScriptTask.__new__(ScriptTask)
    task.run_times = lambda: (Time(hour=8, minute=0, second=0), Time(hour=8, minute=0, second=0))

    now = datetime(2026, 10, 3, 9, 0, 0)
    assert task.next_harvest_time(now) == datetime(2026, 10, 4, 8, 0, 0)
    now = datetime(2026, 10, 3, 7, 0, 0)
    assert task.next_harvest_time(now) == datetime(2026, 10, 3, 8, 0, 0)


def test_new_ui_keys_have_chinese_in_runtime_table():
    """新增的界面 key 必须在 OASX 的运行时中文表里, 否则界面显示英文

    踩过的坑: 只改了后端字段名/说明, OASX 那边没加中文, 用户看到的就是
    "Harvest" / "harvest_time_help" 这种英文 key。
    """
    cn = _runtime_i18n()

    # 任务名 -> OASX 二级菜单 + 页面标题
    assert 'Harvest' in cn, '收菜任务的标题没有中文'
    # 内置时间那一组 + 两个时刻
    assert 'harvest_time' in cn
    assert 'run_time_1' in cn
    assert 'run_time_2' in cn
    # 重启页新增的"定时重启"开关 + 它的说明
    assert 'schedule' in cn
    assert 'restart_schedule_help' in cn

    # 模型里用到的每个 description key 都要有中文, 不能漏
    harvest_time_cls = Harvest.model_fields['harvest_time'].annotation
    fields = [
        (harvest_time_cls, 'run_time_1'),
        (harvest_time_cls, 'run_time_2'),
        (Harvest.model_fields['harvest_config'].annotation, 'enable_courtyard_affairs'),
        (RestartScheduler, 'schedule'),
    ]
    for model, name in fields:
        desc = model.model_fields[name].description
        assert desc, f'{name} 应当带说明'
        assert desc in cn, f'{desc} 不在运行时中文表里, 界面会显示成 key'


def test_harvest_listed_in_daily_task_menu():
    """收菜要出现在日常任务分类下(否则 OASX 侧没有入口)"""
    from module.config.config_menu import ConfigMenu
    assert 'Harvest' in ConfigMenu().menu['Daily Task']


def test_config_model_loads_harvest_task():
    model = ConfigModel('template')
    groups = model.script_task('Harvest')
    assert list(groups.keys()) == ['scheduler', 'harvest_time', 'harvest_config']


# ---------------------------------------------------------------- 老配置迁移

def test_migrate_old_restart_harvest_config():
    """老配置里的 restart.harvest_config 要搬到收菜任务上, 不能静默丢掉"""
    data = {
        'restart': {
            'scheduler': {'enable': True},
            'harvest_config': {
                'enable': False,
                'enable_jade': False,
                'enable_sign': True,
                'enable_mail': False,
            },
        }
    }
    ConfigModel._migrate_harvest_config(data)

    assert 'harvest_config' not in data['restart'], '老字段没删掉, 会反复迁移'
    assert data['harvest']['scheduler']['enable'] is False, '旧的收菜总开关要映射到调度开关'
    config = data['harvest']['harvest_config']
    assert config['enable_jade'] is False
    assert config['enable_sign'] is True
    assert config['enable_mail'] is False


def test_migrate_is_noop_without_old_config():
    data = {'restart': {'scheduler': {'enable': True}}}
    ConfigModel._migrate_harvest_config(data)
    assert 'harvest' not in data


@pytest.mark.parametrize('config_name', ['oas1', 'oas2'])
def test_real_configs_load_and_migrate(config_name):
    """跑一遍用户的真实配置(在内存里), 迁移结果和文件不同"""
    path = CONFIG_DIR / f'{config_name}.json'
    if not path.exists():
        pytest.skip(f'{path} not exists')
    raw = json.loads(path.read_text(encoding='utf-8'))
    if 'harvest_config' not in raw.get('restart', {}):
        pytest.skip('已经迁移过了')

    model = ConfigModel(config_name)
    old = raw['restart']['harvest_config']
    assert model.harvest.scheduler.enable == old.get('enable', True)
    assert model.harvest.harvest_config.enable_ap == old.get('enable_ap', True)
    # 重启的定时开关默认是关的, 也就是"不再定时重启"
    assert model.restart.scheduler.schedule is False


# ---------------------------------------------------------------- 收菜排程(内置时间)

# 上面已有: test_harvest_next_run_follows_builtin_times / test_harvest_next_run_same_time_twice_is_daily
# 这里再确认写入配置时显式传了 server=False(否则会被服务时间改写)


def test_plan_next_run_passes_server_false():
    """排期必须显式 server=False

    否则 scheduler.server_update 不是 09:00 时会被改写成"明天 server_update 时刻",
    内置的收菜时刻就白配了(寮宴会/首领退治都有同样的注释)。
    """
    from tasks.Component.config_base import Time
    from tasks.Harvest.script_task import ScriptTask

    task = ScriptTask.__new__(ScriptTask)
    task.run_times = lambda: (Time(hour=0, minute=15, second=0), Time(hour=20, minute=0, second=0))
    calls = {}
    task.set_next_run = lambda **kwargs: calls.update(kwargs)

    with patch('tasks.Harvest.script_task.datetime') as dt:
        dt.now.return_value = datetime(2026, 10, 3, 12, 0, 0)
        task.plan_next_run()

    assert calls['task'] == 'Harvest'
    assert calls['server'] is False, '收菜时刻不能被 server_update 改写'
    assert calls['target'] == datetime(2026, 10, 3, 20, 0, 0)


# ---------------------------------------------------------------- 登录后顺带收菜

def test_login_harvest_uses_harvest_task_switch():
    """登录流程里的顺带收菜看的是收菜任务的开关, 且改成走 HarvestHandler"""
    source = (Path(__file__).resolve().parents[3] / 'tasks' / 'Restart' / 'login.py').read_text(encoding='utf-8')
    assert 'config.harvest.scheduler.enable' in source
    assert 'restart.harvest_config' not in source, '重启页的收菜配置已经搬走了'
    assert 'HarvestHandler' in source


def test_login_no_longer_owns_harvest_implementation():
    """收菜的实现只应该有一份(在 tasks/Harvest/handler.py)"""
    from tasks.Restart.login import LoginHandler
    assert not hasattr(LoginHandler, 'harvest_mail')
    assert not hasattr(LoginHandler, 'harvest_courtyard_affairs')

    from tasks.Harvest.handler import HarvestHandler
    assert hasattr(HarvestHandler, 'harvest')
    assert hasattr(HarvestHandler, 'harvest_mail')
    assert hasattr(HarvestHandler, 'harvest_courtyard_affairs')


# ---------------------------------------------------------------- 回归: 真实踩过的两个崩

def test_harvest_task_has_ui_goto_and_login():
    """回归: 收菜任务必须能回庭院 + 能登录

    踩过的坑: HarvestHandler 一开始只继承 BaseTask + RestartAssets, 跑起来直接
    AttributeError: 'ScriptTask' object has no attribute 'ui_goto'
    -> 任务失败 + 脚本进程退出。
    """
    from tasks.Harvest.script_task import ScriptTask

    assert hasattr(ScriptTask, 'ui_goto'), 'ui_goto 来自 GameUi, 收菜回庭院要用'
    assert hasattr(ScriptTask, 'app_handle_login')
    assert hasattr(ScriptTask, 'harvest')
    # 组合关系也要锁住: GameUi 自带 GameUiAssets, 再叠 LoginHandler 会 MRO 冲突
    names = [c.__name__ for c in ScriptTask.__mro__]
    assert 'GameUi' in names
    assert 'LoginMixin' in names
    assert 'LoginHandler' not in names


def test_all_task_compositions_can_be_instantiated():
    """回归: 每个 ScriptTask 都要能实例化

    登录逻辑抽成 LoginMixin、收菜继承 GameUi 之后, 最容易炸的就是继承/MRO,
    这里按 script.py 的方式(load_module)把代表性任务都建一遍。
    """
    from module.base.utils import load_module

    repo = REPO_DIR
    # 用真实配置对象: BaseTask 的各个 mixin(CostumeBase 等)真的会读 config 字段。
    # NOTE 必须是"长得像 Config"的对象: BaseTask.__init__ 读 self.config.global_game,
    #      上游 Costume 提交后 get_task_name() 还会读 self.config.model.running_task。
    # 用真实配置对象: BaseTask 的各个 mixin(CostumeBase 等)真的会读 config 字段
    # (self.config.global_game / self.config.model.running_task ...), 手搓 stub 跟不上,
    # 直接用 Config(本模块有隔离 config 目录的 fixture)。
    from module.config.config import Config

    forward = MagicMock()
    forward.config = Config('template')
    forward.device = MagicMock()

    tasks = ['Harvest', 'Restart', 'DailyTrifles', 'KekkaiUtilize', 'Delegation', 'Dokan']
    for name in tasks:
        path = repo / 'tasks' / name / 'script_task.py'
        assert path.exists(), f'{name}/script_task.py 不存在'
        module = load_module('script_task', str(path))
        task = module.ScriptTask(config=forward.config, device=forward.device)
        assert hasattr(task, 'run'), f'{name} 的 ScriptTask 没有 run()'


def test_restart_startup_skip_defers_one_week_exactly_once():
    """回归: 启动时如果 Restart 是待办, 只推迟一次(一周), 之后要能正常跑

    踩过的坑(三轮, 全是循环):
      1. 只 skip 不重排 -> Restart 永远 pending, is_first_task 永远 True -> 无限刷日志
      2. 每次推迟 1 分钟 -> 每分钟推迟一次, 永不到期(而且"立即执行"也被改写成延后一分钟)
      3. else 分支只打日志不 break -> 每秒刷 8 条 "Restart is pending ... run it now"
    所以: 一次性标志 + 推进到未来 + 该跑的时候真的往下走(不能 continue)。
    """
    text = (REPO_DIR / 'script.py').read_text(encoding='utf-8')
    m = re.search(
        r"if task == 'Restart' and not self\.config\.restart\.scheduler\.schedule(.*?)\n\n",
        text,
        re.S,
    )
    assert m, '找不到启动时跳过 Restart 的分支'
    branch = m.group(1)
    code = '\n'.join(line for line in branch.splitlines() if not line.strip().startswith('#'))

    assert '_restart_deferred_from_startup' in code, '没有一次性标志 -> 会反复推迟'
    assert re.search(r'self\._restart_deferred_from_startup = True', code)
    assert 'timedelta(weeks=1)' in code, '启动跳过应当排到一周后'
    # 推迟那一句必须是"只给 target": 带 success=True 会被 min() 选中明天(或 success_interval)
    assert "task_delay(task='Restart', server=False" in code
    # 一次性标志的初始化
    assert '_restart_deferred_from_startup = False' in text
    # 已经不再依赖 is_first_task
    assert 'is_first_task' not in text, 'is_first_task 只在真正跑过任务后才变 False, 是循环的根源'


def test_restart_from_error_is_not_swallowed_by_startup_skip():
    """回归: 任务报错触发的 Restart 不能被"启动跳过"吞掉

    踩过的坑(2026-10-03 19:42, oas1 首领退治):
      退治卡死 -> GameStuckError -> task_call('Restart') -> 被这条"启动时跳过 Restart,
      推迟一周"吞掉 -> 游戏没重启 -> 退治原地又跑一遍(22 分钟), 一轮接一轮地空跑。
    所以: 错误触发的重启要打标记(_restart_from_error), 跳过分支必须尊重它。
    """
    text = (REPO_DIR / 'script.py').read_text(encoding='utf-8')

    # 1) 四个错误分支都走 task_call_restart()(而不是直接 config.task_call('Restart'))
    assert 'def task_call_restart(self)' in text, '缺少"错误触发的重启"入口'
    assert text.count('self.task_call_restart()') >= 4, \
        f'错误分支没有全部标记: {text.count("self.task_call_restart()")} 处'
    code_lines = [line for line in text.splitlines() if not line.strip().startswith('#')]
    direct = [line for line in code_lines if "self.config.task_call('Restart')" in line]
    assert len(direct) == 1, f'除 task_call_restart 里那句外还有直接调用: {direct}'

    m = re.search(
        r"if task == 'Restart' and not self\.config\.restart\.scheduler\.schedule(.*?)\n\n",
        text,
        re.S,
    )
    assert m, '找不到启动时跳过 Restart 的分支'
    code = '\n'.join(line for line in m.group(1).splitlines() if not line.strip().startswith('#'))

    # 2) 跳过分支同时要求"不是错误触发的重启"
    assert '_restart_from_error' in code, '错误触发的 Restart 还是会被吞掉'
    # 3) 标记的初始化与"用掉"
    assert 'self._restart_from_error = False' in text, '缺少标记初始化/复位'
    assert 'self._restart_from_error = True' in text, 'task_call_restart 没有打标记'


def test_restart_schedule_off_defers_one_week_not_tomorrow():
    """回归: 关掉定时重启后, 一次重启结束应当排到一周后, 不能变成"每天一次"

    踩过的坑: set_next_run(success=True, target=+远期) —— Config.task_delay 取
    min(success_interval, target), 于是选中了明天(实测 2026-10-04 而不是预期日期)。
    """
    text = (REPO_DIR / 'tasks' / 'Restart' / 'script_task.py').read_text(encoding='utf-8')
    m = re.search(r'if not self\.config\.restart\.scheduler\.schedule:(.*?)\n\n', text, re.S)
    assert m, '找不到"定时重启关闭"的分支'
    branch = m.group(1)
    # 只看代码行: 注释里会提到 success=True 这个反面教材
    code = '\n'.join(line for line in branch.splitlines() if not line.strip().startswith('#'))

    assert 'timedelta(weeks=1)' in code
    assert 'success=True' not in code, '带 success=True 会被 min() 选中明天 -> 还是每天重启'
    assert 'server=False' in code


def test_task_delay_min_picks_interval_over_far_target(monkeypatch):
    """把 task_delay 的 min() 语义钉住, 避免以后又用错参数

    只改内存里的 ConfigModel, 并把 Config.save 打桩, 不写任何配置文件。
    """
    from module.config.config import Config

    monkeypatch.setattr(Config, 'save', lambda self: None, raising=True)

    now = datetime.now()
    config = Config('template')
    config.model.restart.scheduler.success_interval = timedelta(days=1)

    # 带 success -> 取 success_interval(明天)
    config.task_delay(task='Restart', success=True, server=False, target=now + timedelta(days=3650))
    got = config.model.restart.scheduler.next_run
    assert (got - now).days < 2, f'带 success=True 时应当取较近的明天, 实际 {got}'

    # 只给 target -> 取给定时间
    config.task_delay(task='Restart', server=False, target=now + timedelta(days=7))
    got = config.model.restart.scheduler.next_run
    assert 6 <= (got - now).days <= 7, f'只给 target 时应当排到目标时间, 实际 {got}'

    # 实际用的"一周后"排期
    config.task_delay(task='Restart', server=False, target=now + timedelta(weeks=1))
    got = config.model.restart.scheduler.next_run
    assert 6 <= (got - now).days <= 7, f'一周后应当约 7 天, 实际 {got}'


def test_restart_task_does_not_redo_handled_restart_at_startup():
    """回归: 重启任务的组合关系(仍然是 LoginHandler)"""
    from tasks.Restart.script_task import ScriptTask as RestartTask

    assert hasattr(RestartTask, 'app_handle_login')
    assert hasattr(RestartTask, 'app_restart')
    assert hasattr(RestartTask, 'delay_pending_tasks')


# ---------------------------------------------------------------- 调度循环(端到端)

def test_scheduler_loop_defers_restart_once_then_runs_it(monkeypatch):
    """端到端跑一遍 Script.loop: Restart 待办时只推迟一次, 然后真的执行

    这一条是补前几轮反复踩坑的: 之前只检查源码文本, 所以
    "只打日志不往下走"的死循环(实测每秒刷 8 条日志) 完全测不出来。
    这里真的驱动 loop, 用哨兵异常在迭代边界停住, 断言:
      - 第 1 次拿到 Restart: 推迟到一周后, 不执行
      - 第 2 次拿到 Restart: 真的往下走(执行 run)
      - 配置里的 next_run 变成一周后
    """
    import script as script_module
    from module.config.config import Config
    from module.logger import logger

    monkeypatch.setattr(Config, 'save', lambda self: None, raising=True)
    monkeypatch.setattr(logger, 'set_file_logger', lambda *a, **k: None, raising=True)
    # 不要在测试里读设备/模拟器窗口
    monkeypatch.setattr(script_module, 'IS_WINDOWS', False, raising=True)

    config = Config('template')
    # 只有 Restart 待办, 且没勾"定时重启"
    config.model.restart.scheduler.schedule = False
    config.model.restart.scheduler.next_run = datetime.now() - timedelta(minutes=1)

    instance = script_module.Script('template')
    monkeypatch.setattr(type(instance), 'config',
                        property(lambda self: config), raising=True)
    # 第二次迭代会走到 self.device(真实设备检测在这台机器上会直接退出)
    monkeypatch.setattr(type(instance), 'device',
                        property(lambda self: MagicMock()), raising=True)

    state = {'rounds': 0, 'ran': []}

    class RanSentinel(Exception):
        """run() 被调用 = 我们想要的终点"""

    def counting_get_next_task(self):
        state['rounds'] += 1
        if state['rounds'] > 4:
            raise AssertionError(f'循环了 {state["rounds"]} 次仍在拿任务, 说明有空转')
        return 'Restart'

    def fake_run(self, cmd):
        state['ran'].append(cmd)
        raise RanSentinel(cmd)

    monkeypatch.setattr(script_module.Script, 'get_next_task', counting_get_next_task, raising=True)
    monkeypatch.setattr(script_module.Script, 'run', fake_run, raising=True)

    try:
        instance.loop()
    except RanSentinel:
        pass
    else:
        raise AssertionError('loop 没有走到执行 Restart 就结束了')

    # 第 1 次推迟(不执行), 第 2 次才执行
    assert state['rounds'] == 2, f'期望"推迟一次再执行", 实际拿了 {state["rounds"]} 次任务'
    assert state['ran'] == ['Restart']
    # 推迟之后排到了一周后
    assert config.model.restart.scheduler.next_run > datetime.now() + timedelta(days=6)
