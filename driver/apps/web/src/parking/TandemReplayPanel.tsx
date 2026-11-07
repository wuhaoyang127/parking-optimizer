import { useMemo } from "react";

import type { FacilitySnapshot } from "../api/facilityClient";
import { FacilityCanvas } from "./facility/FacilityCanvas";
import { FacilityLegend } from "./facility/FacilityLegend";
import type { TandemReplay, TandemReplayFrame } from "./tandemReplay";

interface TandemReplayPanelProps {
  kind: "arrival" | "departure";
  replay: TandemReplay;
  facility: FacilitySnapshot;
  floorId: string;
  selectedSpaceId: string | null;
  frame: TandemReplayFrame;
  reducedMotion: boolean;
  onSelect: (spaceId: string) => void;
  onRestart: () => void;
  onNextStage: () => void;
  onContinue?: (() => void) | undefined;
}

export function TandemReplayPanel({
  kind,
  replay,
  facility,
  floorId,
  selectedSpaceId,
  frame,
  reducedMotion,
  onSelect,
  onRestart,
  onNextStage,
  onContinue,
}: TandemReplayPanelProps) {
  const active = replay.steps[frame.activeStep];
  const percent = Math.round(frame.progress * 100);
  const arrival = kind === "arrival";
  const canvasFacility = useMemo(() => arrival && "before_facility_state" in replay && !frame.complete
    ? { layout: facility.layout, state: replay.before_facility_state }
    : facility, [arrival, facility, frame.complete, replay]);
  const hiddenOccupiedSpaceIds = useMemo(() => [replay.target_space_id, ...replay.steps
    .filter((step) => step.action === "relocate_to_buffer")
    .map((step) => step.from_location.location_id)], [replay]);
  return (
    <div className="trip-grid-layout tandem-replay-layout" data-replay-id={replay.replay_id} data-replay-kind={kind}>
      <article className="route-panel tandem-replay-panel">
        <div className="route-panel-heading" data-route-cost-version={replay.cost_version}>
          <div>
            <small>{arrival ? "纵深协同入位回放" : "纵深协同离场回放"}</small>
            <h2>{arrival ? "阻挡车 → 缓冲位 → 当前车辆入位" : "阻挡车 → 缓冲位 → 当前车辆离场"}</h2>
          </div>
          <div>
            <b>{percent}%</b>
            <span>{frame.complete ? (arrival ? "协同入位完成" : "协同移位完成") : `阶段 ${String(frame.activeStep + 1)} / ${String(replay.steps.length)}`}</span>
          </div>
        </div>
        <div className="tandem-replay-progress" aria-label={`协同${arrival ? "入位" : "离场"}进度 ${String(percent)}%`}>
          <span style={{ width: `${String(percent)}%` }} />
        </div>
        <div className="journey-facility-stage">
          <FacilityCanvas
            snapshot={canvasFacility}
            floorId={floorId}
            selectedSpaceId={selectedSpaceId}
            targetSpaceId={replay.target_space_id}
            route={frame.route}
            actors={frame.actors}
            hiddenOccupiedSpaceIds={hiddenOccupiedSpaceIds}
            routeMotion={!reducedMotion && !frame.complete}
            ariaLabel={arrival ? "纵深协同入位完整停车场布局" : "纵深协同离场完整停车场布局"}
            onSelect={onSelect}
          />
          <FacilityLegend />
          <div className="tandem-actor-legend" aria-label="移位车辆图例">
            <span className="driver">您的车辆</span>
            <span className="blocker">外侧阻挡车辆</span>
          </div>
          <span className="map-caption">服务端权威事件的管理层过程回放 · 不是实时定位、车辆控制或自动驾驶</span>
        </div>
      </article>
      <aside className="guidance-panel tandem-guidance-panel">
        <span>{arrival ? "协同入位步骤" : "协同离场步骤"}</span>
        <h2>{frame.complete ? (arrival ? "协同入位已完成" : "协同移位已完成") : active?.label ?? `准备协同${arrival ? "入位" : "离场"}`}</h2>
        <ol>
          {replay.steps.map((step, index) => (
            <li
              key={`${replay.replay_id}-${String(step.sequence)}`}
              className={index <= frame.activeStep ? "active" : ""}
              data-action={step.action}
              aria-current={!frame.complete && index === frame.activeStep ? "step" : undefined}
            >
              <i>{step.sequence}</i>
              <div>
                <strong>{step.label}</strong>
                <small>{Math.round(step.route.distance_m)} m · 约 {Math.ceil(step.duration_s)} 秒</small>
              </div>
            </li>
          ))}
        </ol>
        <div className="driving-note">
          <b>先校验，再移动</b>
          <p>缓冲位不足、路线不可达或状态过期时，服务端会在任何车辆移动前失败关闭。</p>
        </div>
        <div className="tandem-replay-actions">
          {reducedMotion && !frame.complete ? <button type="button" className="primary-action" onClick={onNextStage}>查看下一阶段</button> : null}
          {arrival && frame.complete && onContinue !== undefined ? <button type="button" className="primary-action" onClick={onContinue}>查看停车状态</button> : null}
          <button type="button" className="secondary-action" onClick={onRestart}>重新播放过程</button>
        </div>
      </aside>
    </div>
  );
}

