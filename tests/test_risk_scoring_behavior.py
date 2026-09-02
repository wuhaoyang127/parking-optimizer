"""风险感知多准则评分策略（risk_scoring）行为测试。"""

from src.parking_opt.domain.spot import Spot, SpotType
from src.parking_opt.simulation.parking_lot import ParkingLot
from src.parking_opt.strategies.baselines import NearestPath
from src.parking_opt.strategies.risk_scoring import RiskScoringStrategy

from tests._risk_helpers import StubPathEngine, build_lot, veh


def test_no_available_returns_waiting():
    lot = build_lot()
    filler = veh("VFILL")
    for s in lot.get_available_spots():
        lot.assign(filler, s)
    assert lot.get_available_spots() == []
    spot, status = RiskScoringStrategy().assign(veh("V1"), 10, lot, StubPathEngine())
    assert status == "waiting"
    assert spot is None


def test_returns_assigned_when_available():
    lot = build_lot()
    spot, status = RiskScoringStrategy().assign(veh("V1"), 0, lot, StubPathEngine())
    assert status == "assigned"
    assert spot is not None


def test_only_standalone_spots():
    """场内只有独立位时正常分配到独立位。"""
    spots = [Spot("A1", SpotType.STANDALONE, "A1", "A1", 1),
             Spot("A2", SpotType.STANDALONE, "A2", "A2", 1)]
    lot = ParkingLot(spots)
    pe = StubPathEngine({"A1": 5.0, "A2": 3.0})
    spot, status = RiskScoringStrategy().assign(veh("V1"), 0, lot, pe)
    assert status == "assigned"
    assert spot.spot_type == SpotType.STANDALONE


def test_has_tandem_spot_runs():
    """存在纵深里层空位时不崩溃并给出有效车位。"""
    lot = build_lot()
    spot, status = RiskScoringStrategy(1.0, 1.0, 1.0).assign(
        veh("V1"), 0, lot, StubPathEngine())
    assert status == "assigned"
    assert spot.spot_id in {"A1", "A2", "G1-1", "G1-2"}


def test_risk_vs_distance_conflict():
    """近处纵深外层(会挡住已停短停里层车) vs 远处安全独立位：

    高风险权重下应放弃近处高风险位、选远处独立位；风险权重为 0 时选最近位。
    """
    lot = build_lot()
    # G1-2(里层)已被一辆短停车占用；候选 v 为长停车
    short_inner = veh("U", arrival=0.0, real=600.0, est=600.0)
    lot.assign(short_inner, lot.get_spot("G1-2"))
    pe = StubPathEngine({"G1-1": 1.0, "A1": 10.0, "A2": 11.0})
    v_long = veh("V", arrival=0.0, real=6000.0, est=6000.0)

    # 只看距离：选最近的 G1-1
    only_dist = RiskScoringStrategy(w_distance=1.0, w_risk=0.0, w_depth=0.0)
    spot_d, _ = only_dist.assign(v_long, 0, lot, pe)
    assert spot_d.spot_id == "G1-1"

    # 高风险权重：G1-1 会挡住短停里层车(风险=1)，应改选远处安全独立位
    risk_averse = RiskScoringStrategy(w_distance=1.0, w_risk=5.0, w_depth=0.0)
    spot_r, _ = risk_averse.assign(v_long, 0, lot, pe)
    assert spot_r.spot_id != "G1-1"
    assert spot_r.spot_type == SpotType.STANDALONE


def test_short_stay_low_risk_outer():
    """短停车放到会挡住晚走里层车前面：v 比里层车早走则不构成阻挡(风险=0)。"""
    lot = build_lot()
    long_inner = veh("U", arrival=0.0, real=6000.0, est=6000.0)
    lot.assign(long_inner, lot.get_spot("G1-2"))
    s = RiskScoringStrategy()
    v_short = veh("V", arrival=0.0, real=600.0, est=600.0)
    # G1-1 的风险应为 0（v 早走，不会挡住晚走的里层车）
    risk = s._risk_cost(lot.get_spot("G1-1"), v_short, lot)
    assert risk == 0.0
    # 反之长停车 v 放 G1-1 会挡住……此处里层是长停，v 短停 → 不挡；构造相反验证
    v_long = veh("W", arrival=0.0, real=9000.0, est=9000.0)
    # 里层长停车 est=6000，v_long est=9000 > 6000 → v 会挡住它 → 风险=1
    assert s._risk_cost(lot.get_spot("G1-1"), v_long, lot) == 1.0


def test_inner_blocked_by_later_outer():
    """把 v 放里层 G1-2，而外层 G1-1 已被晚走的车占用 → v 离场需移位(风险=1)。"""
    lot = build_lot()
    late_outer = veh("O", arrival=0.0, real=9000.0, est=9000.0)
    lot.assign(late_outer, lot.get_spot("G1-1"))
    s = RiskScoringStrategy()
    v = veh("V", arrival=0.0, real=1200.0, est=1200.0)
    assert s._risk_cost(lot.get_spot("G1-2"), v, lot) == 1.0
    # 若外层车比 v 早走则不构成阻挡
    lot.free(lot.get_spot("G1-1"))
    early_outer = veh("O2", arrival=0.0, real=300.0, est=300.0)
    lot.assign(early_outer, lot.get_spot("G1-1"))
    assert s._risk_cost(lot.get_spot("G1-2"), v, lot) == 0.0


def test_does_not_read_real_parking_duration():
    """真实停车时长不同、预估时长相同 → 决策必须完全一致（无未来信息泄漏）。"""
    pe = StubPathEngine({"G1-1": 1.0, "A1": 10.0, "A2": 11.0})

    def scenario(real_dur):
        lot = build_lot()
        lot.assign(veh("U", 0.0, real=600.0, est=600.0), lot.get_spot("G1-2"))
        v = veh("V", arrival=0.0, real=real_dur, est=6000.0)  # est 固定，real 变化
        return RiskScoringStrategy(1.0, 5.0, 0.0).assign(v, 0, lot, pe)[0].spot_id

    # real 从 300 到 99999 变化，只要 est 不变，选择必须一致
    choices = {scenario(r) for r in (300.0, 6000.0, 99999.0)}
    assert len(choices) == 1, f"决策随真实停车时长变化，疑似未来信息泄漏: {choices}"


def test_decision_follows_estimate_not_real():
    """预估时长改变(真实不变) → 风险结论应随之改变，证明用的是预估值。"""
    pe = StubPathEngine({"G1-1": 1.0, "A1": 10.0, "A2": 11.0})
    s = RiskScoringStrategy()

    lot = build_lot()
    lot.assign(veh("U", 0.0, real=600.0, est=600.0), lot.get_spot("G1-2"))
    # 同一真实时长 real=6000，两种预估
    v_est_long = veh("V", arrival=0.0, real=6000.0, est=6000.0)   # 估计晚走 → 挡住里层
    v_est_short = veh("V", arrival=0.0, real=6000.0, est=300.0)   # 估计早走 → 不挡
    assert s._risk_cost(lot.get_spot("G1-1"), v_est_long, lot) == 1.0
    assert s._risk_cost(lot.get_spot("G1-1"), v_est_short, lot) == 0.0


def test_all_zero_weights_deterministic():
    """所有权重为 0：不崩溃，按 tie-break 确定性返回。"""
    lot = build_lot()
    pe = StubPathEngine({"A1": 3.0, "A2": 2.0, "G1-1": 1.0, "G1-2": 5.0})
    s = RiskScoringStrategy(0.0, 0.0, 0.0)
    r1 = s.assign(veh("V1"), 0, lot, pe)
    r2 = RiskScoringStrategy(0.0, 0.0, 0.0).assign(veh("V1"), 0, build_lot(), pe)
    assert r1[1] == "assigned"
    # 全 0 权重 → 代价全相等 → tie-break 取最近(再 depth/spot_id)，此处 G1-1 最近
    assert r1[0].spot_id == r2[0].spot_id == "G1-1"


def test_extreme_weights_no_crash():
    lot = build_lot()
    pe = StubPathEngine({"A1": 3.0, "A2": 2.0, "G1-1": 1.0, "G1-2": 5.0})
    for w in [(3.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 3.0), (3.0, 3.0, 3.0)]:
        spot, status = RiskScoringStrategy(*w).assign(veh("V1"), 0, lot, pe)
        assert status == "assigned" and spot is not None


def test_tie_break_deterministic():
    """完全对称场景(距离/风险/结构全相同)：确定性选最小 spot_id，且可复现。"""
    spots = [Spot("B2", SpotType.STANDALONE, "B2", "B2", 1),
             Spot("B1", SpotType.STANDALONE, "B1", "B1", 1),
             Spot("B3", SpotType.STANDALONE, "B3", "B3", 1)]
    pe = StubPathEngine()  # 全部距离 1.0
    picks = {RiskScoringStrategy(1.0, 1.0, 1.0).assign(
        veh("V1"), 0, ParkingLot([Spot(s.spot_id, s.spot_type, s.node_id,
                                       s.stack_group_id, s.depth) for s in spots]),
        pe)[0].spot_id for _ in range(5)}
    assert picks == {"B1"}


def test_degenerates_to_nearest():
    """w_risk=w_depth=0 时选中车位应与最近路径一致(取最小距离位)。"""
    lot = build_lot()
    pe = StubPathEngine({"A1": 7.0, "A2": 2.0, "G1-1": 4.0, "G1-2": 9.0})
    v = veh("V1")
    scoring = RiskScoringStrategy(w_distance=1.0, w_risk=0.0, w_depth=0.0)
    spot_s, _ = scoring.assign(v, 0, lot, pe)
    spot_n, _ = NearestPath().assign(v, 0, build_lot(), pe)
    assert spot_s.spot_id == spot_n.spot_id == "A2"
