# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from time import sleep

import numpy as np

from module.base.protect import random_sleep
from module.base.timer import Timer
from module.exception import GamePageUnknownError, TaskEnd
from module.logger import logger

from tasks.Component.GeneralBattle.config_general_battle import GeneralBattleConfig
from tasks.Component.GeneralBattle.general_battle import GeneralBattle
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.Component.SwitchSoul.switch_soul import SwitchSoul
from tasks.FightForShikigami.assets import FightForShikigamiAssets
from tasks.FightForShikigami.config import Banquet, FightForShikigami
from tasks.GameUi.page import page_main, page_shikigami_records

"""
为崽而战 —— 八百八狸盛宴

流程：
    庭院（右侧挂牌列命中「为崽而战」）
      → 活动主界面（点「八百八狸盛宴」）
      → 六边形地图（进入后镜头会自动移到高亮区域）
      → 点高亮格 → 「妖怪退治」战斗入口页
      → 点右下角「退治」→ 战斗 → 回到地图 → 循环

终止条件（任一命中即收工）：
    1) 游戏内提示「体力消耗已达上限」（次数耗尽）
    2) OCR 读到「每日消耗上限 X/X」且已消耗 >= 上限
    3) 运行时长 / 局数达到配置上限
    4) 地图上再也找不到高亮格
"""


class ScriptTask(RightActivity, GeneralBattle, SwitchSoul, FightForShikigamiAssets):

    # ---------------- 六边形网格几何（1280x720 实测标定） ----------------
    # 六边形是「尖顶」六边形（左右两条竖直边），横向被拉伸：
    #   · 相邻列间距（左右竖直边之间的距离）= 168
    #   · 竖直边长度 ≈ 80
    # 注意不是正六边形，高度 / 宽度比例与正六边形不同，改动前请重新标定。
    #
    # 下面这几个容差是拿真实截图离线跑算法标定出来的，不要随意收紧：
    # 竖边会被建筑/角色立绘截断，检测到的 y 中心最大会偏 ~19px，
    # 所以合并和配对的 y 容差必须给够（行间距是 120，放宽到 35 也不会串行）。
    HEX_COL_STEP = 168
    HEX_HALF_W = 84
    HEX_EDGE_MIN = 44
    HEX_EDGE_MAX = 128
    HEX_EDGE_MERGE_GAP = 6      # 同一竖边允许的列断裂
    HEX_EDGE_MERGE_DY = 25      # 同一竖边允许的 y 抖动
    HEX_PAIR_DX_TOL = 12        # 配对时列间距容差
    HEX_PAIR_DY_TOL = 35        # 配对时两条边的高度差容差

    # ---------------- 高亮黄判别 ----------------
    # 高亮格描边 ≈ RGB(255, 250, 140)，普通米黄格 ≈ RGB(215, 200, 135)
    # 两者 B 通道接近（都 ~135），主要差别在 R/G，所以用 R+G 做阈值。
    YELLOW_RG = 480
    YELLOW_B = 170

    # 搜索范围，避开四周 UI（左上通报栏、顶部标题、底部按钮）
    MAP_TOP = 100
    MAP_BOTTOM = 640
    MAP_LEFT = 10
    MAP_RIGHT = 1270

    def run(self):
        conf: FightForShikigami = self.config.fight_for_shikigami

        # 1. 先回庭院。
        #    必须放在换御魂之前：活动页面里没有直达式神录的路径。
        if not self.goto_main():
            self.finish(success=False)
            return

        # 2. 自动换御魂
        if conf.switch_soul_config.enable:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul(conf.switch_soul_config.switch_group_team)
        if conf.switch_soul_config.enable_switch_by_name:
            self.ui_get_current_page()
            self.ui_goto(page_shikigami_records)
            self.run_switch_soul_by_name(conf.switch_soul_config.group_name,
                                         conf.switch_soul_config.team_name)

        # 3. 庭院 → 为崽而战 → 八百八狸盛宴地图
        if not self.enter_activity():
            self.finish(success=False)
            return

        # 4. 主循环
        self.banquet_loop(conf)

        # 5. 退出活动回到庭院
        self.exit_activity()

        self.finish(success=True)

    def finish(self, success: bool):
        self.set_next_run(task='FightForShikigami', success=success, finish=True)
        raise TaskEnd('FightForShikigami')

    # ------------------------------------------------------------------
    # 回庭院
    # ------------------------------------------------------------------
    def goto_main(self) -> bool:
        """
        回到庭院。

        注意这里**必须捕获 GamePageUnknownError**：
        如果任务启动时游戏停在活动里的某个未注册页面，ui_get_current_page() 会判定
        Unknown page、乱点几下 SAFE_RANDOM_CLICK，最后抛 GamePageUnknownError；
        而框架对它的处理是 script.py 里的 `self.config.task_call('Restart')`
        —— 也就是强制重启游戏。捕获后转成自己的可控处理，不要再触发那条路径。

        正常情况：为崽而战的活动页面已经在 tasks/GameUi/page.py 注册好了
        （活动主界面 / 六边形地图 / 战斗入口页），ui_get_current_page() 能认出来，
        ui_goto(page_main) 也能沿返回键一路走回庭院。
        """
        try:
            self.ui_get_current_page()
            if self.ui_goto(page_main):
                return True
            logger.warning('未能回到庭院')
            return False
        except GamePageUnknownError:
            logger.critical('当前页面不被识别，无法回庭院')
            logger.critical('如果游戏停在某些活动页面（例如「为崽而战·浮世之航」活动首页）里，'
                            '请先手动退回庭院再运行本任务')
            return False

    # ------------------------------------------------------------------
    # 进入活动
    # ------------------------------------------------------------------
    def enter_activity(self) -> bool:
        """庭院 → 命中「为崽而战」→ 进活动主界面 → 点「八百八狸盛宴」进地图"""
        # 这一步不能省：换御魂会把我们留在【式神录】，
        # 只有先回庭院才能看到右侧的挂牌列。
        if not self.goto_main():
            return False
        if not self.enter_weizai():
            return False
        if not self.enter_banquet():
            return False
        return True

    def enter_weizai(self, timeout: int = 60) -> bool:
        """
        在庭院右侧的挂牌列里找「为崽而战」。
        挂牌列是循环轮换的：找不到就点一下列尾的刷新箭头，换一批再找。
        """
        # 防空转护栏：不在庭院就直接找挂牌列是白找，
        # 之前漏了这一步导致在式神录上空转了 60 秒直到 GameStuckError。
        self.screenshot()
        if not self.appear(self.I_CHECK_MAIN):
            logger.warning('当前不在庭院，先回庭院')
            if not self.goto_main():
                return False

        timer = Timer(timeout).start()
        while 1:
            self.screenshot()

            if self.appear(self.I_FFS_ENTRY):
                logger.info('找到「为崽而战」入口')
                if not self.ui_click(self.I_FFS_ENTRY, stop=self.I_FFS_BANQUET,
                                     interval=2, timeout=20):
                    logger.warning('点击「为崽而战」后未进入活动主界面')
                    return False
                return True

            if timer.reached():
                logger.warning(f'等待「为崽而战」入口超时（{timeout}s），本次跳过')
                return False

            # 没找到 → 点刷新，让挂牌列换一批
            if self.appear_then_click(self.I_FFS_REFRESH, interval=2):
                logger.info('未找到入口，点击刷新挂牌列')
                continue

    def enter_banquet(self, timeout: int = 30) -> bool:
        """活动主界面 → 点「八百八狸盛宴」→ 六边形地图

        注意：左右两个入口（百妖之巅 / 寝肥合战）未解锁时样式几乎一样，
        模板只裁了旗上的文字区域，靠文字区分。
        """
        timer = Timer(timeout).start()
        while 1:
            self.screenshot()

            if self.appear(self.I_FFS_MAP_TITLE):
                # 进图后镜头会自动移到高亮区域，这里不等，
                # 交给主循环的 wait_map_stable() 等它停稳
                logger.info('已进入八百八狸盛宴地图，等镜头自动移动结束')
                return True

            if self.appear_then_click(self.I_FFS_BANQUET, interval=2):
                continue

            # 关掉可能挡路的弹窗
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1.5):
                continue

            if timer.reached():
                logger.warning('进入「八百八狸盛宴」超时')
                return False

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def banquet_loop(self, conf: FightForShikigami):
        banquet: Banquet = conf.banquet
        battle_config: GeneralBattleConfig = conf.general_battle

        # 注意：Timer 的 limit 单位是「秒」，必须把 timedelta 转成秒再传进去，
        # 否则 reached() 里 float > timedelta 会直接抛 TypeError
        limit_timer = Timer(banquet.limit_time_v.total_seconds())
        limit_timer.start()
        battle_count = 0

        while 1:
            if limit_timer.reached():
                logger.info(f'运行时长已达上限 {banquet.limit_time_v}，收工')
                break
            if banquet.limit_battle and battle_count >= banquet.limit_battle:
                logger.info(f'已达局数上限 {banquet.limit_battle}，收工')
                break

            # 1/2. 不在战斗入口页，就先在地图上找一个高亮格点进去
            #      注意：刚进地图 / 战斗结束回地图，镜头都会有一段自动移动的动画，
            #      动画期间截图只能拿到中间帧，必须等画面停稳再做检测
            if not self.is_on_battle_entry():
                # 本宴没开的时候，地图上虽然有大片黄色高亮，但那只是**预告区域**，
                # 点上去完全没有反应。必须先判掉，否则会白点一轮格子，
                # 还会误报成"所有高亮格都无法进入战斗"。
                if self.banquet_not_open():
                    logger.warning('本宴尚未开启，本次不打（地图上的黄色高亮只是预告区域）')
                    break
                cells = self.wait_map_stable()
                if not cells:
                    self.report_no_cells()
                    break
                logger.info(f'发现 {len(cells)} 个高亮格：{cells}')
                # 拟人化：真正动手点之前，偶尔停一下（像人在看地图）
                if banquet.random_sleep:
                    random_sleep(probability=0.2)
                if not self.click_until_battle_entry(cells):
                    logger.warning('所有高亮格都无法进入战斗，收工')
                    break

            # 3. 次数是否已经用完
            if self.daily_cost_exhausted():
                break

            # 4. 点「退治」进入战斗
            #    拟人化：这一步等价于"开始战斗"，是最该打散节奏的地方。
            #    写法与参考任务一致（ActivityShikigami / BudokaiTournament）：
            #    20% 概率随机休息 2~6 秒。
            if banquet.random_sleep:
                random_sleep(probability=0.2)
            retreat = self.click_retreat()
            if retreat == 'exhausted':
                break
            if retreat == 'not_found':
                # 入口页还在但按钮没了：这一格多半已经打完，退回地图重新找
                logger.info('「退治」按钮不见，退回地图重新寻找高亮格')
                self.back_to_map()
                continue

            # 5. 通用战斗流程
            battle_count += 1
            logger.hr(f'八百八狸盛宴 第 {battle_count} 局', 2)
            self.run_general_battle(battle_config)

            # 6. 等回到地图才能继续下一轮
            if not self.wait_back_to_map():
                logger.warning('战斗结束后未回到地图，收工')
                break

        logger.info(f'本次共战斗 {battle_count} 局')
        try:
            self.config.notifier.push(title='为崽而战',
                                      content=f'八百八狸盛宴本次共战斗 {battle_count} 局')
        except Exception as e:
            logger.warning(f'推送通知失败：{e}')

    def click_until_battle_entry(self, cells: list, per_try_timeout: int = 10) -> bool:
        """逐个点击高亮格，直到出现「妖怪退治」入口页"""
        for cell in cells[:4]:
            logger.info(f'点击高亮格 {cell}')
            self.device.click(cell[0], cell[1], control_name='FfsHexCell')
            sleep(0.5)      # 点击后先让界面动起来，避免在动画中途判断
            if self.wait_battle_entry(timeout=per_try_timeout):
                return True
            logger.warning(f'点击 {cell} 后未进入战斗入口页，试下一个')
        return False

    def wait_battle_entry(self, timeout: int = 15) -> bool:
        """等待「妖怪退治」战斗入口页出现，并给它一点时间做完入场动画"""
        timer = Timer(timeout).start()
        while 1:
            self.screenshot()
            if self.appear(self.I_FFS_BATTLE_TITLE):
                logger.info('已进入战斗入口页')
                sleep(0.8)      # 等入场动画走完，之后的 OCR/匹配才准
                return True
            if timer.reached():
                return False
            sleep(0.2)

    def read_daily_cost(self, retry: int = 5, interval: float = 0.5):
        """
        读取「每日消耗上限」计数。

        刚切进这一页时界面还在做入场动画，OCR 容易读错，
        所以要求**连续两次读数一致**才采信，否则重试。

        :return: (已消耗, 剩余, 上限) 或 None
        """
        last = None
        for _ in range(retry):
            self.screenshot()
            try:
                result = self.O_FFS_DAILY_COST.ocr(self.device.image)
            except Exception as e:
                logger.warning(f'每日消耗 OCR 失败：{e}')
                result = None
            if result and len(result) == 3 and last == result:
                return result
            last = result
            sleep(interval)
        logger.warning('每日消耗 OCR 连续两次读数不一致，采用最后一次结果')
        return last

    def daily_cost_exhausted(self) -> bool:
        """次数是否已耗尽：先看 OCR 读数，再看游戏内提示"""
        result = self.read_daily_cost()
        if result and len(result) == 3:
            current, remain, total = result
            logger.attr('每日消耗上限', f'{current}/{total}')
            # total 为 0 说明没识别到，不能据此判断
            if total and int(current) >= int(total):
                logger.info('每日消耗已达上限，今日不再战斗')
                return True

        if self.appear(self.I_FFS_STAMINA_LIMIT):
            logger.info('出现「体力消耗已达上限」提示')
            return True
        return False

    def click_retreat(self, timeout: int = 15) -> str:
        """点右下角「退治」进战斗。

        :return:
            'battle'    已进入战斗
            'exhausted' 次数用完（出现「体力消耗已达上限」提示）
            'not_found' 入口页还在但按钮点不到，这一格可能已经打完
        """
        timer = Timer(timeout).start()
        while 1:
            self.screenshot()

            if self.appear(self.I_FFS_STAMINA_LIMIT):
                logger.warning('体力消耗已达上限，今日次数已用完')
                return 'exhausted'

            # 入口页消失说明已经进战斗了
            if not self.appear(self.I_FFS_BATTLE_TITLE):
                logger.info('已进入战斗')
                return 'battle'

            if timer.reached():
                logger.warning('「退治」按钮未出现')
                return 'not_found'

            if self.appear_then_click(self.I_FFS_RETREAT, interval=1.5):
                timer.reset()
                continue

    def back_to_map(self, timeout: int = 20) -> bool:
        """从战斗入口页点返回，回到六边形地图"""
        timer = Timer(timeout).start()
        while 1:
            self.screenshot()
            # 入口页一消失就说明已经退回地图了 —— 别再点返回，
            # 否则地图上的返回键会把我们带出活动。
            # 镜头可能还在自动移动，交给主循环的 wait_map_stable() 等停稳。
            if not self.appear(self.I_FFS_BATTLE_TITLE):
                logger.info('已退回地图')
                return True
            if timer.reached():
                logger.warning('退回地图超时')
                return False
            if self.appear_then_click(self.I_FFS_BACK, interval=1.5):
                continue
            if self.appear_then_click(self.I_FFS_BACK_MAP, interval=1.5):
                continue

    def is_on_battle_entry(self) -> bool:
        """是否在「妖怪退治」战斗入口页"""
        return self.appear(self.I_FFS_BATTLE_TITLE)

    def is_on_map(self) -> bool:
        """是否在六边形地图页（入口页标题不在，且能找到高亮格或「退治完成」标记）"""
        if self.appear(self.I_FFS_BATTLE_TITLE):
            return False
        if self.appear(self.I_FFS_DONE):
            return True
        return bool(self.detect_highlight_cells())

    def report_no_cells(self):
        """
        地图上找不到高亮格时给出可区分的结论。

        实测「本期已全部打完」时地图上是真的没有高亮格，
        这时不能报成检测异常，否则会误导排查方向。
        """
        if self.appear(self.I_FFS_DONE):
            logger.info('地图上没有可攻击的高亮格，八百八狸已标记「退治完成」，本次收工')
        else:
            logger.warning('地图上没有找到高亮格。如果此时明明还有可攻击目标，'
                           '说明高亮格检测需要重新标定（黄色阈值 / 六边形网格几何），请抓图排查')

    def banquet_not_open(self) -> bool:
        """
        本宴是否还没开启。

        地图页顶部那行有两种状态（实测）：
            「本宴1时16分57秒后结束」   → 已开启，可以打
            「本宴3分41秒后开启挑战」   → **还没开**

        没开的时候地图上照样有大片黄色高亮，但那只是**预告区域**，点上去没有任何反应
        （实测日志：连点 3 个高亮格，战斗入口页始终不出现）。
        判定失败时一律当作"已开启"，宁可白试一轮也不要因为 OCR 抽风而错过活动。
        """
        try:
            self.screenshot()
            text = self.O_FFS_BANQUET_STATUS.ocr(self.device.image)
        except Exception as e:
            logger.warning(f'本宴状态识别失败：{e}')
            return False
        if not text:
            return False
        text = str(text).replace(' ', '')
        logger.attr('本宴状态', text)
        return '开启挑战' in text

    def wait_back_to_map(self, timeout: int = 60) -> bool:
        """战斗结束后等画面回来。

        实测：战后一般回到「妖怪退治」战斗入口页，可以在同一格连续再打；
        这一格打完后才会回到地图。两种都算成功，交给主循环判断下一步。
        """
        timer = Timer(timeout).start()
        while 1:
            self.screenshot()

            if self.ui_reward_appear_click():
                timer.reset()
                continue
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1.5):
                timer.reset()
                continue

            if self.is_on_battle_entry():
                logger.info('战斗结束，回到战斗入口页，继续打这一格')
                return True
            if self.is_on_map():
                logger.info('战斗结束，回到地图')
                return True

            if timer.reached():
                return False
            sleep(0.3)

    def exit_activity(self, timeout: int = 40) -> bool:
        """一路点返回，直到回到庭院"""
        logger.hr('退出为崽而战', 2)
        timer = Timer(timeout).start()
        while 1:
            self.screenshot()

            if self.appear(self.I_CHECK_MAIN):
                logger.info('已回到庭院')
                return True

            if self.ui_reward_appear_click():
                continue

            if timer.reached():
                logger.warning('返回庭院超时')
                return False

            # 返回键有两种样式，必须都试：
            #   地图页 = 圆形深色按钮 + 金色弧形箭头（I_FFS_BACK_MAP）
            #   活动主界面 / 战斗入口页 = 鸟居木框 + 左箭头（I_FFS_BACK）
            if self.appear_then_click(self.I_FFS_BACK_MAP, interval=1.5):
                continue
            if self.appear_then_click(self.I_FFS_BACK, interval=1.5):
                continue
            if self.appear_then_click(self.I_UI_BACK_RED, interval=1.5):
                continue
            if self.appear_then_click(self.I_UI_BACK_YELLOW, interval=1.5):
                continue

    # ------------------------------------------------------------------
    # 等画面停稳
    # ------------------------------------------------------------------
    @staticmethod
    def cells_similar(a: list, b: list, tol: int = 8) -> bool:
        """
        两次检测结果是否算「同一个画面」。

        容差取值有讲究：
          · 太小（如 2）→ 静止时的 1~2px 抖动会导致永远判不稳定
          · 太大（如 12）→ 镜头缓慢平移时，两组其实不同的格子逐项差值也可能都 <=12，
                            会被误判成已停稳
        实测静止抖动在 0~2px，取 8 两边都安全。
        """
        if not a or not b or len(a) != len(b):
            return False
        return all(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol
                   for p, q in zip(a, b))

    def wait_map_stable(self, timeout: int = 20, interval: float = 0.6) -> list:
        """
        等地图镜头停稳，再返回高亮格。

        判据用「连续两次检测到的高亮格一致」而不是逐像素比对：
        镜头在移动时检测结果必然抖动，所以这天然就能等到自动移动动画结束。
        实测点击「八百八狸盛宴」后有一段镜头自动移动的动画，
        动画期间截图会拿到中间帧，检测出来的格子是错的。

        :return: 停稳后的高亮格列表；超时则返回最后一次的检测结果
        """
        timer = Timer(timeout).start()
        last = None
        while 1:
            self.screenshot()

            # 本期已全部打完：地图上不会再出现高亮格，直接返回，不必等满超时
            if self.appear(self.I_FFS_DONE):
                logger.info('地图显示「退治完成」，已无可攻击目标')
                return []

            cells = self.detect_highlight_cells()
            if cells and self.cells_similar(cells, last):
                logger.info(f'地图已停稳，高亮格：{cells}')
                return cells
            last = cells
            if timer.reached():
                logger.warning(f'等待地图停稳超时（{timeout}s），按当前结果继续')
                return cells or []
            sleep(interval)

    # ------------------------------------------------------------------
    # 高亮格检测
    # ------------------------------------------------------------------
    def detect_highlight_cells(self) -> list:
        """
        在地图上找出高亮（可攻击）格子的中心点。

        原理：高亮格的六条边是亮黄色，其中左右两条是**竖直边**（长约 80px）。
        同排相邻格的竖直边是共享的，所以两个相距 HEX_COL_STEP 的竖直边
        就围出一个格子 —— 一条边既可能是左边格子的右边，也可能是右边格子的左边，
        因此每条边可以参与两次配对，不能去重。

        :return: [(x, y), ...] 格心坐标，按 y 再按 x 排序（优先打靠上的）
        """
        image = self.device.image
        if image is None:
            return []
        height, width = image.shape[:2]

        r = image[:, :, 0].astype(np.int16)
        g = image[:, :, 1].astype(np.int16)
        b = image[:, :, 2].astype(np.int16)
        mask = (r + g > self.YELLOW_RG) & (b < self.YELLOW_B)

        top = max(0, self.MAP_TOP)
        bottom = min(height, self.MAP_BOTTOM)
        left = max(0, self.MAP_LEFT)
        right = min(width, self.MAP_RIGHT)

        # 1. 收集竖直黄边（按列找长度合适的连续段）
        edges = []
        for x in range(left, right):
            ys = np.flatnonzero(mask[top:bottom, x])
            if ys.size == 0:
                continue
            breaks = np.flatnonzero(np.diff(ys) > 1) + 1
            for seg in np.split(ys, breaks):
                if self.HEX_EDGE_MIN <= seg.size <= self.HEX_EDGE_MAX:
                    edges.append((x, float(seg[0] + seg[-1]) / 2.0 + top))
        if not edges:
            logger.info('未检测到竖直黄边')
            return []

        # 2. 把属于同一条竖边的列合并成一个点。
        #
        #    不能只做一趟顺序扫描：同一列里可能同时有上下两条边，
        #    顺序扫描时它们会交错排列，把本该配对的两条边隔开。
        #    实测出现 x=811 与 x=812 各留两条（y≈239 和 y≈474），
        #    最终产出相距 2px 的"两个格子"。所以这里按 (x, y) 聚类。
        groups = []
        for edge in edges:
            for grp in groups:
                gx = sum(e[0] for e in grp) / len(grp)
                gy = sum(e[1] for e in grp) / len(grp)
                if (abs(edge[0] - gx) <= self.HEX_EDGE_MERGE_GAP
                        and abs(edge[1] - gy) <= self.HEX_EDGE_MERGE_DY):
                    grp.append(edge)
                    break
            else:
                groups.append([edge])
        edge_list = [(sum(e[0] for e in grp) / len(grp), sum(e[1] for e in grp) / len(grp))
                     for grp in groups]
        if len(edge_list) < 2:
            return []

        # 3. 配成格子
        cells = []
        for i in range(len(edge_list)):
            for j in range(i + 1, len(edge_list)):
                dx = edge_list[j][0] - edge_list[i][0]
                dy = abs(edge_list[j][1] - edge_list[i][1])
                if (abs(dx - self.HEX_COL_STEP) <= self.HEX_PAIR_DX_TOL
                        and dy <= self.HEX_PAIR_DY_TOL):
                    cells.append((int((edge_list[i][0] + edge_list[j][0]) / 2),
                                  int((edge_list[i][1] + edge_list[j][1]) / 2)))

        # 去重并排序，优先打靠上的。
        # 注意：配对时同一个格子可能产出多个相近结果（实测出现过相距 2px 的"两个格子"），
        # 会把同一个位置当成多个目标重复点，所以必须按距离合并。
        cells = sorted(set(cells), key=lambda c: (c[1], c[0]))
        unique = []
        for cell in cells:
            if any(abs(cell[0] - u[0]) <= 40 and abs(cell[1] - u[1]) <= 40 for u in unique):
                continue
            unique.append(cell)
        return unique


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.screenshot()

    t.run()
