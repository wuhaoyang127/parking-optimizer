from __future__ import annotations
"""数据读写：JSON Schema 加载与保存"""

import json
from pathlib import Path
from ..domain.spot import RoadNetwork, RoadNode, NodeType, SpotType, Vehicle


def load_road_network(filepath: str | Path) -> RoadNetwork:
    """从JSON加载路网"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    network = RoadNetwork()
    for n in data['nodes']:
        node_type = NodeType(n['type'])
        spot_type = None
        if node_type == NodeType.PARKING_SPOT:
            spot_type = SpotType(n.get('spot_type', 'STANDALONE'))

        network.add_node(RoadNode(
            node_id=n['id'],
            node_type=node_type,
            x=n.get('x', 0.0),
            y=n.get('y', 0.0),
            spot_type=spot_type,
            stack_group_id=n.get('stack_group_id'),
            depth=n.get('depth', 1),
        ))

    for e in data.get('edges', []):
        network.add_edge(e['from'], e['to'], e['length'])

    return network


def save_road_network(network: RoadNetwork, filepath: str | Path):
    """保存路网到JSON"""
    nodes = []
    for n in network.nodes.values():
        node_data = {'id': n.node_id, 'type': n.node_type.value, 'x': n.x, 'y': n.y}
        if n.node_type == NodeType.PARKING_SPOT:
            node_data['spot_type'] = n.spot_type.value if n.spot_type else 'STANDALONE'
            node_data['stack_group_id'] = n.stack_group_id or n.node_id
            node_data['depth'] = n.depth or 1
        nodes.append(node_data)

    edges = [{'from': e.from_node, 'to': e.to_node, 'length': e.length}
             for e in network.edges]

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({'nodes': nodes, 'edges': edges}, f, indent=2, ensure_ascii=False)


def load_demand(filepath: str | Path) -> list[Vehicle]:
    """从JSON加载车辆需求"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return [
        Vehicle(
            vehicle_id=v['id'],
            arrival_time=v['arrival_time'],
            parking_duration=v['parking_duration'],
            estimated_duration=v.get('estimated_duration', 7200.0),
        )
        for v in data['vehicles']
    ]


def save_demand(vehicles: list[Vehicle], metadata: dict | None = None,
                filepath: str | Path = "demand.json"):
    """保存车辆需求到JSON"""
    data = {
        'vehicles': [
            {
                'id': v.vehicle_id,
                'arrival_time': v.arrival_time,
                'parking_duration': v.parking_duration,
                'estimated_duration': v.estimated_duration,
            }
            for v in vehicles
        ],
        'metadata': metadata or {}
    }
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_events(events: list, filepath: str | Path):
    """保存事件日志到JSONL"""
    with open(filepath, 'w', encoding='utf-8') as f:
        for event in events:
            event_dict = {
                'time': event.time,
                'type': event.event_type.value,
            }
            if event.vehicle_id:
                event_dict['vehicle_id'] = event.vehicle_id
            if event.spot_id:
                event_dict['spot_id'] = event.spot_id
            if event.strategy:
                event_dict['strategy'] = event.strategy
            event_dict.update(event.metadata)
            f.write(json.dumps(event_dict, ensure_ascii=False) + '\n')


def save_metrics(metrics: dict, filepath: str | Path):
    """保存指标到JSON"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)


def load_config(filepath: str | Path = "configs/default.json") -> dict:
    """加载配置文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)
