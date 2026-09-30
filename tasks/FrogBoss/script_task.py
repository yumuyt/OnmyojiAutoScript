# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
from cached_property import cached_property
from datetime import datetime
import requests
import re
import json

from module.exception import TaskEnd
from module.logger import logger
from module.atom.image import RuleImage
from module.base.timer import Timer

from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.Component.RightActivity.right_activity import RightActivity
from tasks.Component.GeneralBattle.assets import GeneralBattleAssets
from tasks.Component.config_base import TimeDelta
from tasks.FrogBoss.assets import FrogBossAssets
from tasks.FrogBoss.config import Strategy

# 新版（2026-09-30）对弈竞猜面板在 1280x720 下的实测坐标，
# 仅在结算页素材没匹配上时兜底点击（顺序仍是先宝箱、后下一局，不会跳过奖励）
C_SETTLE_BOX = (754, 420)  # 结算页宝箱中心
C_SETTLE_NEXT = (799, 505)  # 结算页「下一局」的 » 图标中心


class ScriptTask(RightActivity, FrogBossAssets, GeneralBattleAssets):
    def run(self):
        self.enter(self.I_FROG_BOSS_ENTER)
        # 新版（2026-09）：对弈竞猜挂在「活动总览」里，挂牌列点进来可能只到总览页
        self.enter_panel()

        # 进入主界面
        idle_timer = Timer(30)
        idle_timer.start()
        while 1:
            self.screenshot()

            # 已经下注
            if self.appear(self.I_BETTED):
                logger.info('You have betted')
                break
            # 休息中
            if self.appear(self.I_FROG_BOSS_REST):
                logger.info('Frog Boss Rest')
                break
            # 竞猜成功 / 竞猜失败：新版两个页面的后续动作完全一样，都是「开宝箱 -> 下一局」
            win = self.appear(self.I_BET_SUCCESS)
            lose = self.appear(self.I_BET_FAILURE)
            if win or lose or self.settle_page_appear():
                logger.info('FrogBoss: 结算页（%s）' % (
                    '竞猜成功' if win else '竞猜失败' if lose else '标题没认出来，按印章/宝箱/按钮判定'))
                idle_timer.reset()
                self.detect()
                self.goto_next_round()
                continue
            # 正式竞猜
            if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                idle_timer.reset()
                self.do_bet()
                continue
            # 上次被中断停在压注页 / 确认弹窗（06/07/08 那种界面）：把这一注下完
            if self.appear(self.I_BET_SURE) or self.appear(self.I_GOLD_30):
                idle_timer.reset()
                self.confirm_bet()
                continue

            # 停在未知界面（面板没展开 / 活动休息但素材没认出来）时不要一直空转
            if idle_timer.reached():
                logger.warning('FrogBoss: 30 秒没有命中任何已知界面，放弃本次运行')
                self.save_debug_shot('未知界面')
                break

        logger.info('FrogBoss end')
        self.next_run()
        raise TaskEnd('FrogBoss')

    def settle_page_appear(self) -> bool:
        """
        结算页兜底判定。标题素材万一在实机上认不出来（文字有动画 / 又改版），
        只要鼓上的胜败印章、宝箱、下一局按钮里任何一个在，就认定这里是结算页。
        下注界面/压注页这些素材的分数都在 0.6 以下，不会误判。
        """
        return (self.appear(self.I_SUCCESS_LEFT) or self.appear(self.I_FAILURE_RIGHT)
                or self.appear(self.I_BET_SUCCESS_BOX) or self.appear(self.I_NEXT_COMPETITION))

    def match_score(self, image: RuleImage) -> float:
        """
        只算匹配分数（不改 roi_front），用来诊断素材在实机上到底差多少
        """
        import cv2
        target = image.image
        source = image.corp(self.device.image)
        if target is None or target.shape[0] > source.shape[0] or target.shape[1] > source.shape[1]:
            return -1.0
        return float(cv2.matchTemplate(source, target, cv2.TM_CCOEFF_NORMED).max())

    def save_debug_shot(self, reason: str) -> None:
        """
        把实机当前这一帧存到 ./log/screenshots/，方便回头核对素材到底长什么样
        """
        try:
            if self.device.save_screenshot(genre='frogboss', interval=5):
                logger.info(f'FrogBoss: 已保存现场截图（{reason}）到 log/screenshots/')
        except Exception as e:
            logger.warning(f'FrogBoss: 保存现场截图失败：{e}')

    def enter_panel(self) -> bool:
        """
        新版「活动总览」：庭院挂牌列点进来后，如果面板还没展开，
        需要在左栏「精彩活动」里再点一次「对弈竞猜」。
        已经是下注界面 / 已竞猜 / 休息中就什么都不做。
        """
        timer = Timer(20)
        timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_BET_LEFT) or self.appear(self.I_BET_RIGHT) \
                    or self.appear(self.I_BETTED) or self.appear(self.I_FROG_BOSS_REST):
                return True
            if timer.reached():
                logger.warning('FrogBoss: 20 秒内没有进到对弈竞猜面板')
                return False
            if self.appear_then_click(self.I_FROG_BOSS_ENTRY_LIST, interval=2):
                continue

    def goto_next_round(self, timeout: int = 60) -> bool:
        """
        从结算页回到下注界面。顺序必须和上游一致：先开宝箱 / 领奖，最后才点「下一局」——
        反过来写会在「宝箱还没开、下一局已经能点」的时候直接翻页，把奖励跳过去。

        新版结算页（2026-09 改版）实测：没有独立的领取入口，翻盘奖励是开箱即得，
        开箱后新增的可交互物只有「回放 / 下一局」两个按钮。这里只认右边的 » ，不会误点回放。

        素材万一在实机上认不出来（分数不够），这里也不会干等着：先存现场帧 + 打分数，
        再按改版实测坐标点一次宝箱、再点一次「下一局」——顺序仍然是先宝箱后下一局，
        所以不会把奖励跳过去。
        """
        timer = Timer(timeout)
        timer.start()
        stuck_timer = Timer(6)
        stuck_timer.start()
        blind_box, blind_next = False, False
        while 1:
            self.screenshot()
            if self.appear(self.I_BET_LEFT) and self.appear(self.I_BET_RIGHT):
                return True
            if timer.reached():
                logger.warning(f'FrogBoss: {timeout} 秒内没有回到下注界面')
                self.save_debug_shot('结算页没翻过去')
                return False
            if self.appear_then_click(self.I_BET_SUCCESS_BOX, interval=1):
                logger.info('FrogBoss: 结算页 -> 开宝箱')
                stuck_timer.reset()
                continue
            # 新版界面上这一步点不到（旧素材在新版全图多尺度搜索最高 0.62），保留只为和上游行为一致
            if self.appear_then_click(self.I_REWARD, interval=2):
                logger.info('FrogBoss: 结算页 -> 领取奖励')
                stuck_timer.reset()
                continue
            if self.appear_then_click(self.I_NEXT_COMPETITION, interval=4):
                logger.info('FrogBoss: 结算页 -> 下一局')
                stuck_timer.reset()
                continue
            # 兜底：素材没匹配上，打分数 + 存现场，再按实测坐标点一次
            if stuck_timer.reached():
                stuck_timer.reset()
                if not blind_box:
                    blind_box = True
                    logger.warning('FrogBoss: 结算页素材没匹配上，分数 宝箱 %.3f / 下一局 %.3f / 领奖 %.3f'
                                   % (self.match_score(self.I_BET_SUCCESS_BOX),
                                      self.match_score(self.I_NEXT_COMPETITION),
                                      self.match_score(self.I_REWARD)))
                    self.save_debug_shot('宝箱认不出')
                    logger.warning(f'FrogBoss: 按实测坐标点一次宝箱 {C_SETTLE_BOX}')
                    self.device.click(*C_SETTLE_BOX)
                elif not blind_next:
                    blind_next = True
                    self.save_debug_shot('下一局认不出')
                    logger.warning(f'FrogBoss: 按实测坐标点一次下一局 {C_SETTLE_NEXT}')
                    self.device.click(*C_SETTLE_NEXT)

    def next_run(self):
        time = self.config.model.frog_boss.frog_boss_config.before_end_frog
        time_delta = TimeDelta(hours=time.hour, minutes=time.minute, seconds=time.second)
        time_now = datetime.now()
        time_set = time_now.replace(minute=0, second=0, microsecond=0)
        if 10 <= time_now.hour < 12:
            time_set = time_set.replace(hour=14)
        elif 12 <= time_now.hour < 14:
            time_set = time_set.replace(hour=16)
        elif 14 <= time_now.hour < 16:
            time_set = time_set.replace(hour=18)
        elif 16 <= time_now.hour < 18:
            time_set = time_set.replace(hour=20)
        elif 18 <= time_now.hour < 20:
            time_set = time_set.replace(hour=22)
        elif 20 <= time_now.hour < 22:
            time_set = time_set.replace(hour=0) + TimeDelta(days=1)
        elif 22 <= time_now.hour < 24:
            time_set = time_set.replace(hour=12) + TimeDelta(days=1)
        else:
            time_set = time_set.replace(hour=12)

        self.set_next_run(task='FrogBoss', target=time_set - time_delta)

    def do_bet(self):
        logger.hr('do bet', level=2)
        self.screenshot()
        flag_glod_30 = 0
        count_left = self.O_LEFT_COUNT.ocr(self.device.image)
        count_right = self.O_RIGHT_COUNT.ocr(self.device.image)
        logger.info(f'Bet count: left {count_left}, right {count_right}')
        if not count_left and not count_right:
            # 读不出来时 Majority / Minority 会退化成固定押右，这种静默退化必须留痕
            logger.warning('FrogBoss: 左右押注数都没读出来（OCR 区域可能又变了），策略会退化成固定押右')
        match self.config.model.frog_boss.frog_boss_config.strategy_frog:
            case Strategy.Majority:
                click_image = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
            case Strategy.Minority:
                click_image = self.I_BET_LEFT if count_left < count_right else self.I_BET_RIGHT
            case Strategy.Bilibili:
                click_image = self.I_BET_LEFT if count_left > count_right else self.I_BET_RIGHT
            case Strategy.Dashen:
                click_image = self.get_dashen(count_left, count_right)
            case Strategy.AlwaysRed:
                click_image = self.I_BET_LEFT
            case Strategy.AlwaysBlue:
                click_image = self.I_BET_RIGHT
            case _:
                raise ValueError(f'Unknown bet mode: {self.config.model.frog_boss.frog_boss_config.strategy_frog}')
        logger.info(f'You strategy is {self.config.model.frog_boss.frog_boss_config.strategy_frog} and bet on {click_image}')
        # 点鼓进压注页（鼓消失即说明进去了），加超时，避免点不开时一直点
        drum_timer = Timer(20)
        drum_timer.start()
        while 1:
            self.screenshot()
            if not self.appear(click_image):
                break
            if drum_timer.reached():
                logger.warning('FrogBoss: 点鼓 20 秒没有进入压注页，放弃本轮')
                return
            self.appear_then_click(click_image, interval=2)
        gold_30_timer = Timer(10)
        gold_30_timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_GOLD_30_CHECK):
                break
            if gold_30_timer.reached():
                logger.info('Gold 30 not appear')
                break
            if self.appear_then_click(self.I_GOLD_30, interval=3):
                continue
        # 正式下注
        self.confirm_bet(flag_glod_30)

    def confirm_bet(self, flag_glod_30: int = 0, timeout: int = 60) -> bool:
        """
        在压注页 / 确认弹窗上把这一注下完：选 30 万 → 点右侧大鼓 → 点「确定」，直到出现「已竞猜」。
        上一次运行被打断停在压注页时，run() 也会调这里把这一注补完。
        """
        logger.info('Formal bet')
        bet_timer = Timer(timeout)
        bet_timer.start()
        while 1:
            self.screenshot()
            if self.appear(self.I_BETTED):
                return True
            if bet_timer.reached():
                logger.warning(f'FrogBoss: 下注 {timeout} 秒没有结果，放弃本轮')
                return False
            # 确认弹窗（「花费30万金币竞猜红方获胜，是否确认」）优先点确定
            if self.appear_then_click(self.I_UI_CONFIRM, interval=2):
                continue
            if self.appear_then_click(self.I_UI_CONFIRM_SAMLL, interval=2):
                continue
            if self.appear_then_click(self.I_BET_SURE, interval=2) and flag_glod_30 == 1:
                continue
            if self.appear_then_click(self.I_GOLD_30, interval=2):
                flag_glod_30 = 1
                continue

    def detect(self) -> bool:
        """
        检测是左边赢了还是右边赢的
        :return: True 左边赢了
        """
        if self.appear(self.I_SUCCESS_LEFT) and self.appear(self.I_FAILURE_RIGHT):
            result = True
            logger.info('Left win')
        elif self.appear(self.I_SUCCESS_RIGHT) and self.appear(self.I_FAILURE_LEFT):
            result = False
            logger.info('Right win')
        else:
            result = True
        return result

    def get_bilibili(self) -> RuleImage:
        """
        获取博主的策略选择
        :return:
        """
        pass

    def get_dashen(self, count_left, count_right) -> RuleImage:
        """
        获取博主的策略选择，整合多个博主的投注策略，并返回最终的下注建议
        :return: 'left' 或 'right' 的下注目标
        """
        logger.info('Fetching strategy from multiple Dashen UPer')
        # 定义正则表达式
        red_regex = re.compile(r'(押红|押左|压红|压左|红方|红色|我红|我左|红优|左|红六|红七|红八|红九|红十|91开|82开|73开|64开)')
        blue_regex = re.compile(r'(押蓝|押右|压蓝|压右|蓝方|蓝色|我蓝|我右|蓝优|右|蓝六|蓝七|蓝八|蓝九|蓝十|19开|28开|37开|46开)')

        # 获取 feedId 的函数
        def get_feed_id(uid):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/getSomeOneFeeds?feedTypes=1,2,3,4,6,7,10,11&someOneUid={uid}'
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                if 'result' in data and 'feeds' in data['result'] and len(data['result']['feeds']) > 0:
                    return data['result']['feeds'][0]['id']
            return None
        
        # 获取 feed 详细信息的函数
        def get_feed_details(feed_id):
            url = f'https://inf.ds.163.com/v1/web/feed/basic/facade?feedId={feed_id}'
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                try:
                    user_nick = data['result']['userInfos'][0]['user']['nick']
                    create_time = data['result']['feed']['createTime']
                    content_json = data['result']['feed']['content']
                    content_data = json.loads(content_json)
                    body_text = content_data['body']['text']
                    return {
                        'user_nick': user_nick,
                        'create_time': create_time,
                        'body_text': body_text
                    }
                except (KeyError, IndexError, json.JSONDecodeError):
                    return None
            return None
        
        # 检查发布时间是否符合规则
        def is_time_valid(create_time):
            # 定义时间段
            valid_time_ranges = [(10, 12), (12, 14), (14, 16), (16, 18), (18, 20), (20, 22), (22, 24)]
            now = datetime.now()
            # now = datetime(year=2024, month=10, day=3, hour=19, minute=45, second=0)  # 指定时间读取历史文章
            
            # 获取发布时间
            post_time = datetime.fromtimestamp(create_time / 1000)  # 假设 create_time 是毫秒级时间戳
            post_hour = post_time.hour
            
            # 检查发布时间是否在有效时间段内
            for start, end in valid_time_ranges:
                if start <= post_hour < end and start <= now.hour < end:
                    return True
            return False

        # 分析 body_text 来判断投注结果
        def analyze_bet(body_text):
            red_span=9999
            blue_span=9999
            if red_regex.search(body_text):
                red_span=red_regex.search(body_text).start()
            if blue_regex.search(body_text):
                blue_span=blue_regex.search(body_text).start()
            if red_span < blue_span:
                return 'LEFT'
            elif red_span > blue_span:
                return 'RIGHT'
            return 'Unknown'

        # 提供的 uid 列表
        uids = [
            {"name": "面灵气喵", "id": "462382f1127b46c5add1185d88f0ea40"},
            {"name": "余岁岁", "id": "54399446d5084a0e8878dac8f6ff56d0"},
            {"name": "七面相", "id": "840742d60e4a43208605ae68ca8c3f64"},
            {"name": "待机中的徐ok", "id": "c3c989fae4074d04b478b8ba47ae4120"},
            {"name": "雯雯", "id": "aaa923436aa440df9ac1ee3f47387b99"},
            {"name": "晨时微凉", "id": "72584a679e2f45b6859566b5523400d5"},
            {"name": "梅布斯尼", "id": "3d4726d99f2642a485729695b798cb8c"},
            {"name": "鸽海成路", "id": "1d2dcbbd7e3d481c8d0f27ba4ff0dc71"},
            {"name": "徐清林", "id": "21657a558bdd4ddfb6501298350336e7"},
            {"name": "不包邮哦亲", "id": "0e4e0c5a1e494a1fa9a58ac55de689c1"},
            {"name": "天真珈百璃", "id": "30e383c884f844a18a7a76fe3c1e888f"},
            {"name": "薛定谔家查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "嘤嘤井", "id": "e7107cd3010e418da26672669d8eeb5e"},
            {"name": "Prince班崎", "id": "74adeb1bfb2b4cf382edbbb430da2149"},
            {"name": "靠脸混饭", "id": "e87f855f36f24b34b9d8f8a4fb2d62b2"},
            {"name": "夜神月丶L", "id": "82de68c7672e4b6da65493fb829b57b6"},
            {"name": "是大荣啦", "id": "f6d6bb15d6024200a985752e2ab4c373"},
            {"name": "炒饭菌", "id": "06e2bba14a914012bc8064601cfa19ea"},
            {"name": "清流不加班", "id": "8982241de1844638b4bb455139b8dcc0"},
            {"name": "槐夏三十", "id": "a9724e98c1cb4a4e931ebc3f467ea73d"},
            {"name": "落沫颜", "id": "e9b0a16325af46628e8dfb9e7942cf1d"},
            {"name": "Mico林木森", "id": "b6b5bc8277e34f69aeca018db0081397"},
            {"name": "查查尔", "id": "d9dc2a75497c4a91b2db1e909a36544d"},
            {"name": "CC南浔", "id": "74db771d92a54c28ae3e98d19aa565a3"},
            {"name": "冰七喜Den", "id": "e498e524252041e29999b38e57c4df1d"},
            {"name": "行水姑娘", "id": "30b0c2923faa483f95572c324a5bc910"},
            {"name": "更慕林", "id": "e32aedbdd8da46a5b5b497a16c4b7658"}
            # ... 可以添加更多 uid
        ]


        # 主函数，遍历这批 uid
        count_uper_left = 0  # 统计博主投注左侧红方次数
        count_uper_right = 0  # 统计博主投注右侧蓝方次数

        for user in uids:
            uid = user['id']
            name = user['name']
            feed_id = get_feed_id(uid)
            if feed_id:
                details = get_feed_details(feed_id)
                # 检查 create_time 和 body_text
                if details and is_time_valid(int(details['create_time'])) and details['body_text']:
                    bet_result = analyze_bet(details['body_text'])
                    bet_rate = (re.compile(r"([5-9]\d%|\d+开|[一二三四五六七八九十零]+开|([红蓝][一二三四五六七八九十零,0-9])+)")
                            .search(details.get('body_text')))
                    if bet_rate:
                        bet_rate = ',' + bet_rate.group()
                    else:
                        bet_rate = ''
                    # 输出博主结论，可省略
                    # logger.info(f"{name}({details['user_nick']}) has bet on the {bet_result}{bet_rate}")

                    # 根据投注结果更新统计
                    if bet_result == 'LEFT':
                        count_uper_left += 1
                    elif bet_result == 'RIGHT':
                        count_uper_right += 1

        # 最终输出决策
        if count_uper_left > count_uper_right:
            logger.info(f"Final decision: The best bet is LEFT({count_uper_left}:{count_uper_right})")
            return self.I_BET_LEFT  # 返回下注的目标是左边
        elif count_uper_right > count_uper_left:
            logger.info(f"Final decision: The best bet is RIGHT({count_uper_right}:{count_uper_left})")
            return self.I_BET_RIGHT  # 返回下注的目标是右边
        else:
            logger.info("Final decision:Left and right bets are equal, default bet is minority")
            # 若五五开则投注少数博反压奖励
            if count_left < count_right:
                return self.I_BET_LEFT
            else:
                return self.I_BET_RIGHT


if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device
    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)

    t.run()

