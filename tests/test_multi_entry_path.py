"""PathEngine 多入口/多出口解析规则测试。"""

from src.parking_opt.domain.spot import RoadNetwork, RoadNode, NodeType, SpotType
from src.parking_opt.routing.path_engine import PathEngine

from tests._multi_entry_helpers import build_two_entry_net


def test_path_engine_collects_multiple_entries_and_default_entry():
    net = build_two_entry_net()
    pe = PathEngine(net)
    assert set(pe.entry_ids) == {"E1", "E2"}
    # 没有名为 ENTRY 的节点 → 默认入口为第一个 entry（遍历顺序 E1）
    assert pe.entry_id == "E1"
    assert pe.distance_to_spot("A") == 10.0
    assert pe.distance_to_spot("B", "E2") == 10.0
    # 交叉出口边使 E1 可绕行到 B（经 X2），距离应大于直连入口
    assert pe.distance_to_spot("B", "E1") == 30.0
    assert pe.distance_to_spot("A", "E2") == 30.0


def test_path_engine_default_entry_prefers_named_entry():
    net = RoadNetwork()
    net.add_node(RoadNode("E2", NodeType.ENTRY, 0, 0))
    net.add_node(RoadNode("ENTRY", NodeType.ENTRY, 50, 0))
    net.add_node(RoadNode("A", NodeType.PARKING_SPOT, 60, 0, SpotType.STANDALONE, "A", 1))
    net.add_edge("ENTRY", "A", 10); net.add_edge("A", "ENTRY", 10)
    pe = PathEngine(net)
    assert pe.entry_ids == ["E2", "ENTRY"]
    assert pe.entry_id == "ENTRY"  # 命名 ENTRY 优先
    assert pe.distance_to_spot("A") == 10.0


def test_path_engine_exit_rules_and_fallback():
    # 无出口布局：default_exit_id None，resolve_exit 回退入口
    net = build_two_entry_net(with_exits=False)
    pe = PathEngine(net)
    assert pe.exit_ids == []
    assert pe.default_exit_id is None
    assert pe.resolve_exit(None) == "E1"  # 回退默认入口
    assert pe.resolve_exit("X1") == "E1"  # 非法出口也回退入口

    # 有出口布局：默认出口优先 EXIT，否则第一个
    net2 = build_two_entry_net()
    pe2 = PathEngine(net2)
    assert set(pe2.exit_ids) == {"X1", "X2"}
    assert pe2.default_exit_id == "X1"  # 无命名 EXIT → 第一个
    assert pe2.resolve_exit("X2") == "X2"
    assert pe2.resolve_exit(None) == "X1"
