import type { FacilitySnapshot, RoutePreview } from "../../api/facilityClient";
import { spaceById, spaceState, statusLabel } from "./viewModel";

export function FacilitySelectionDetails({ snapshot, floorId, selectedSpaceId, entranceId, preview, routeLoading, onFloor, onEntrance, onPreview, onFocus }: { snapshot: FacilitySnapshot; floorId: string; selectedSpaceId: string | null; entranceId: string; preview: RoutePreview | null; routeLoading: boolean; onFloor: (id: string) => void; onEntrance: (id: string) => void; onPreview: () => void; onFocus: () => void }) {
  const space = spaceById(snapshot.layout, selectedSpaceId);
  const state = spaceState(snapshot, selectedSpaceId);
  return (
    <aside className="facility-details">
      <div className="facility-detail-heading"><span>只读查看</span><h2>{space?.space_id ?? "选择一个车位"}</h2><p>{space === null ? "点击画布中的车位查看状态和属性。" : `${statusLabel(state?.effective_status ?? "unknown")} · ${space.charging ? "充电位" : "普通位"}${space.stack_group_id == null ? "" : ` · 纵深 ${String(space.depth)}`}`}</p></div>
      {snapshot.layout.floors.length > 1 ? <label>楼层<select value={floorId} onChange={(event) => { onFloor(event.target.value); }}>{snapshot.layout.floors.map((item) => <option key={item.floor_id} value={item.floor_id}>{item.label}</option>)}</select></label> : null}
      <label>路线入口<select value={entranceId} onChange={(event) => { onEntrance(event.target.value); }}>{snapshot.layout.entrances.map((item) => <option key={item.entrance_id} value={item.entrance_id}>{item.label}</option>)}</select></label>
      {space === null || state === null ? <div className="facility-empty-detail">状态、充电属性和纵深信息将在这里显示。</div> : <div className="facility-facts"><span><small>当前状态</small><strong>{statusLabel(state.effective_status)}</strong></span><span><small>分区</small><strong>{snapshot.layout.zones.find((item) => item.zone_id === space.zone_id)?.label ?? space.zone_id}</strong></span><span><small>类型</small><strong>{space.stack_group_id == null ? "独立车位" : `纵深第 ${String(space.depth)} 位`}</strong></span><span><small>观察来源</small><strong>{state.observation_source}</strong></span></div>}
      <div className="facility-detail-actions"><button type="button" className="secondary-action" disabled={space === null} onClick={onFocus}>聚焦车位</button><button type="button" className="primary-action" disabled={space === null || state?.assignable !== true || routeLoading} onClick={onPreview}>{routeLoading ? "正在计算" : "查看场内路线"}</button></div>
      {preview === null ? <p className="readonly-note">路线预览不会推荐或锁定车位，也不会创建停车行程。</p> : <div className="route-summary"><strong>{preview.route.distance_m.toFixed(0)} 米 · 约 {Math.ceil(preview.route.dynamic_eta_s)} 秒</strong><span>{preview.route.instructions.length} 个场内步骤</span></div>}
    </aside>
  );
}
