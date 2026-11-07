import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { loadFacilitySnapshot, type FacilitySnapshot } from "../api/facilityClient";
import {
  departJourney,
  departTandemWithReplay,
  driverDemoReplan,
  loadCurrentDriverTrip,
  loadJourneyParkingLot,
  occupyJourney,
  occupyTandemWithReplay,
  reassignJourney,
  RecommendationApiError,
  reportExternalOccupancy,
  resetDemoJourney,
  startNavigation,
  type DriverTripSnapshot,
  type ParkingLot,
} from "../api/recommendationClient";
import { FacilityCanvas } from "./facility/FacilityCanvas";
import { FacilityLegend } from "./facility/FacilityLegend";
import { routeVehiclePosition } from "./facility/routeGeometry";
import { spaceState, statusLabel } from "./facility/viewModel";
import { conservativeServerClock } from "./serverClock";
import { TandemReplayPanel } from "./TandemReplayPanel";
import { facilityForTandemReplay } from "./journeyReplayFacility";
import { tandemReplayFrame } from "./tandemReplay";
import { routeTimeline } from "./routeTimeline";

function journeyError(error: unknown): string {
  if (error instanceof RecommendationApiError) {
    if (error.status === 0) return "当前处于离线状态。已保留上次同步画面，重新连接后可恢复行程。";
    if (error.status === 409) return "行程已在其他页面发生变化，正在读取最新状态。";
    return error.message;
  }
  return "当前无法读取行程，请稍后重试。";
}

function formatDuration(seconds: number): string {
  const safe = Math.max(0, Math.ceil(seconds));
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function maneuverGlyph(text: string): string {
  if (text.startsWith("右转")) return "↱";
  if (text.startsWith("左转")) return "↰";
  if (text.startsWith("按高亮")) return "↗";
  return "↑";
}

function statusCopy(state: string): { label: string; detail: string } {
  switch (state) {
    case "session_reserved": return { label: "车位已预留", detail: "准备好后开始场内指引，预留期限不会因刷新延长。" };
    case "navigating": return { label: "正在前往车位", detail: "车辆动画仅用于理解管理路线，不会自动提交停车状态。" };
    case "occupied": return { label: "已确认停入", detail: "占用由服务端记录，关闭页面不会自动释放。" };
    case "departed": return { label: "本次行程已结束", detail: "停车记录已保留在当前浏览器会话。" };
    case "expired": return { label: "预留已到期", detail: "原车位已经释放，请重新获取智能推荐。" };
    default: return { label: "本次行程已结束", detail: "请返回智能停车重新创建需求。" };
  }
}

function inspectedStatusLabel(state: ReturnType<typeof spaceState>, isJourneyTarget: boolean): string | null {
  if (state === null) return null;
  if (isJourneyTarget && state.claim_status === "session_reserved") return "已为本行程预留";
  if (isJourneyTarget && state.claim_status === "navigating") return "行程使用中";
  return statusLabel(state.effective_status);
}

function prefersReducedMotion(): boolean {
  try {
    return globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function stableTripIdentity(snapshot: DriverTripSnapshot): string {
  return JSON.stringify({
    journey: snapshot.journey,
    driver: snapshot.driver,
    current_route: snapshot.current_route,
    current_node_id: snapshot.current_node_id,
    last_replan: snapshot.last_replan,
    started_at: snapshot.started_at,
    parked_at: snapshot.parked_at,
    ended_at: snapshot.ended_at,
    tandem_arrival_replay_enabled: snapshot.tandem_arrival_replay_enabled,
    tandem_arrival_replay: snapshot.tandem_arrival_replay,
    tandem_departure_replay_enabled: snapshot.tandem_departure_replay_enabled,
    tandem_departure_replay: snapshot.tandem_departure_replay,
  });
}

function assertJourneyFacilityView(snapshot: DriverTripSnapshot, facility: FacilitySnapshot): void {
  const journey = snapshot.journey;
  if (journey === null || journey === undefined) return;
  const { layout, state } = facility;
  if (layout.parking_lot_id !== journey.parking_lot_id || state.parking_lot_id !== journey.parking_lot_id || state.scenario_id !== journey.scenario_id) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "行程与完整停车场状态不属于同一场景");
  }
  const route = snapshot.current_route;
  if (route !== null && route !== undefined && route.layout_version !== layout.layout_version) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前路线与停车场布局版本不一致");
  }
  const target = journey.space_id === null || journey.space_id === undefined ? null : layout.spaces.find((space) => space.space_id === journey.space_id) ?? null;
  const targetState = journey.space_id === null || journey.space_id === undefined ? null : state.spaces.find((space) => space.space_id === journey.space_id) ?? null;
  if (["session_reserved", "navigating", "occupied"].includes(journey.state) && (target === null || targetState === null)) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程目标车位不在完整停车场状态中");
  }
  if (
    (journey.state === "session_reserved" && targetState?.claim_status !== "session_reserved") ||
    (journey.state === "navigating" && targetState?.claim_status !== "navigating")
  ) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前行程与目标车位声明状态不一致");
  }
  if (journey.state === "occupied" && (targetState?.claim_status !== "none" || targetState.observed_status !== "occupied" || targetState.effective_status !== "occupied")) {
    throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "已停入行程与目标车位占用状态不一致");
  }
  if (route !== null && route !== undefined) {
    if (route.node_ids.some((nodeId) => !layout.nodes.some((node) => node.node_id === nodeId))) {
      throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "当前路线引用了布局中不存在的节点");
    }
    const invalidEdge = route.edge_ids.some((edgeId, index) => {
      const edge = layout.edges.find((candidate) => candidate.edge_id === edgeId);
      const fromNode = route.node_ids[index];
      const toNode = route.node_ids[index + 1];
      return edge === undefined || fromNode === undefined || toNode === undefined || !(
        edge.from_node_id === fromNode && edge.to_node_id === toNode ||
        !edge.directed && edge.from_node_id === toNode && edge.to_node_id === fromNode
      );
    });
    if (invalidEdge || target?.access_node_id !== route.to_node_id) {
      throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "路线边或目标车位与布局不一致");
    }
  }
}

export function JourneyPage() {
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<DriverTripSnapshot | null>(null);
  const [facility, setFacility] = useState<FacilitySnapshot | null>(null);
  const [lot, setLot] = useState<ParkingLot | null>(null);
  const [floorId, setFloorId] = useState<string | null>(null);
  const [inspectedSpaceId, setInspectedSpaceId] = useState<string | null>(null);
  const [pageVisible, setPageVisible] = useState(() => document.visibilityState === "visible");
  const [motionAllowed, setMotionAllowed] = useState(() => document.visibilityState === "visible" && !prefersReducedMotion());
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [clock, setClock] = useState<{ observedAt: string; monotonicAt: number } | null>(null);
  const [nowMs, setNowMs] = useState(0);
  const [motionNowMs, setMotionNowMs] = useState(0);
  const [replayNowMs, setReplayNowMs] = useState(0);
  const [replayStartedAtMs, setReplayStartedAtMs] = useState<number | null>(null);
  const [manualReplaySteps, setManualReplaySteps] = useState(0);
  const [dismissedArrivalReplayId, setDismissedArrivalReplayId] = useState<string | null>(null);
  const [dismissedEtaWarning, setDismissedEtaWarning] = useState<string | null>(null);
  const recoveryRef = useRef<Promise<DriverTripSnapshot> | null>(null);
  const expirySyncRef = useRef<string | null>(null);
  const recoveryAbortRef = useRef<AbortController | null>(null);
  const replayIdentityRef = useRef<string | null>(null);

  const recover = useCallback(() => {
    if (recoveryRef.current !== null && recoveryAbortRef.current?.signal.aborted !== true) return recoveryRef.current;
    const recoveryController = new AbortController();
    recoveryAbortRef.current = recoveryController;
    const operation = (async () => {
      const started = performance.now();
      let next = await loadCurrentDriverTrip(recoveryController.signal);
      recoveryController.signal.throwIfAborted();
      let nextFacility: FacilitySnapshot | null = null;
      let nextLot: ParkingLot | null = null;
      for (let attempt = 0; attempt < 2 && next.journey !== null && next.journey !== undefined; attempt += 1) {
        const journey = next.journey;
        [nextFacility, nextLot] = await Promise.all([
          loadFacilitySnapshot(journey.parking_lot_id, recoveryController.signal),
          loadJourneyParkingLot(journey.parking_lot_id, recoveryController.signal),
        ]);
        recoveryController.signal.throwIfAborted();
        const confirmed = await loadCurrentDriverTrip(recoveryController.signal);
        recoveryController.signal.throwIfAborted();
        if (stableTripIdentity(next) === stableTripIdentity(confirmed)) {
          next = confirmed;
          break;
        }
        next = confirmed;
        nextFacility = null;
        nextLot = null;
      }
      if (next.journey !== null && next.journey !== undefined && (nextFacility === null || nextLot === null)) {
        throw new RecommendationApiError(409, "JOURNEY_VIEW_CHANGED", "行程状态持续变化，无法形成一致画面");
      }
      const received = performance.now();
      const nextClock = conservativeServerClock(next.observed_at, started, received);
      const journey = next.journey;
      if (journey !== null && journey !== undefined) {
        if (nextFacility === null || nextLot === null) {
          throw new RecommendationApiError(409, "JOURNEY_VIEW_CHANGED", "行程状态持续变化，无法形成一致画面");
        }
        const nextLayout = nextFacility.layout;
        if (nextLot.parking_lot_id !== journey.parking_lot_id) {
          throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "行程、布局与停车场不属于同一范围");
        }
        nextFacility = facilityForTandemReplay(next, nextFacility);
        assertJourneyFacilityView(next, nextFacility);
        const targetFloorId = nextLayout.spaces.find((space) => space.space_id === journey.space_id)?.floor_id;
        setFloorId((current) => current !== null && nextLayout.floors.some((floor) => floor.floor_id === current) ? current : targetFloorId ?? nextLayout.default_floor_id);
        setInspectedSpaceId((current) => current !== null && nextLayout.spaces.some((space) => space.space_id === current) ? current : journey.space_id ?? null);
      }
      recoveryController.signal.throwIfAborted();
      setClock(nextClock);
      setSnapshot(next);
      setFacility(nextFacility);
      setLot(nextLot);
      setMessage(null);
      return next;
    })().finally(() => {
      if (recoveryAbortRef.current === recoveryController) recoveryAbortRef.current = null;
      if (recoveryRef.current === operation) recoveryRef.current = null;
    });
    recoveryRef.current = operation;
    return operation;
  }, []);

  const recoverFresh = useCallback(async () => {
    const pending = recoveryRef.current;
    if (pending !== null) await pending.catch(() => undefined);
    return recover();
  }, [recover]);

  useEffect(() => {
    let active = true;
    void recover()
      .catch((error: unknown) => { if (active) setMessage(journeyError(error)); })
      .finally(() => { if (active) setLoading(false); });
    return () => {
      active = false;
      recoveryAbortRef.current?.abort();
    };
  }, [recover]);

  useEffect(() => {
    const tick = (forceMotion = false) => {
      const current = clock === null ? Date.now() : new Date(clock.observedAt).getTime() + performance.now() - clock.monotonicAt;
      setNowMs(current);
      if (forceMotion || motionAllowed) setMotionNowMs(current);
      setReplayNowMs(performance.now());
    };
    tick(true);
    if (!pageVisible) return undefined;
    const timer = globalThis.setInterval(() => { tick(); }, 250);
    return () => { globalThis.clearInterval(timer); };
  }, [clock, motionAllowed, pageVisible]);

  useEffect(() => {
    const sync = () => { if (document.visibilityState === "visible") void recover().catch((error: unknown) => { setMessage(journeyError(error)); }); };
    const timer = globalThis.setInterval(sync, 3_000);
    globalThis.addEventListener("online", sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      globalThis.clearInterval(timer);
      globalThis.removeEventListener("online", sync);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [recover]);

  useEffect(() => {
    let media: MediaQueryList | null = null;
    try {
      media = globalThis.matchMedia("(prefers-reduced-motion: reduce)");
    } catch {
      media = null;
    }
    const update = () => {
      const visible = document.visibilityState === "visible";
      setReducedMotion(media?.matches === true);
      setPageVisible(visible);
      setMotionAllowed(visible && !(media?.matches === true));
    };
    update();
    document.addEventListener("visibilitychange", update);
    if (media !== null) media.addEventListener("change", update);
    return () => {
      document.removeEventListener("visibilitychange", update);
      if (media !== null) media.removeEventListener("change", update);
    };
  }, []);

  const journey = snapshot?.journey;
  const route = snapshot?.current_route;
  const tandemArrivalReplay = snapshot?.tandem_arrival_replay ?? null;
  const tandemDepartureReplay = snapshot?.tandem_departure_replay ?? null;
  const tandemReplayKind = tandemDepartureReplay !== null
    ? "departure"
    : tandemArrivalReplay !== null && journey?.state === "occupied" && dismissedArrivalReplayId !== tandemArrivalReplay.replay_id
      ? "arrival"
      : null;
  const tandemReplay = tandemReplayKind === "departure" ? tandemDepartureReplay : tandemReplayKind === "arrival" ? tandemArrivalReplay : null;
  const failedReplan = snapshot?.last_replan?.status === "failed";
  const etaWarning = snapshot?.last_replan?.status === "warning" &&
    snapshot.last_replan.reason_codes.includes("ETA_EXCEEDS_RESERVATION");
  const etaWarningKey = etaWarning ? `${snapshot.last_replan?.cost_snapshot.cost_version ?? ""}:${snapshot.last_replan?.cost_snapshot.observed_at ?? ""}` : null;
  const remaining = journey?.expires_at === null || journey?.expires_at === undefined ? 0 : Math.max(0, (new Date(journey.expires_at).getTime() - nowMs) / 1000);
  const elapsedS = (() => {
    if (journey?.state !== "navigating" || failedReplan || route === null || route === undefined || snapshot?.started_at === null || snapshot?.started_at === undefined) return 0;
    const replanMatchesRoute = snapshot.last_replan?.route?.cost_version === route.cost_version;
    const latestReplan = replanMatchesRoute ? snapshot.last_replan?.cost_snapshot.observed_at : undefined;
    const anchor = latestReplan ?? snapshot.started_at;
    return Math.max(0, (motionNowMs - new Date(anchor).getTime()) / 1000);
  })();
  const timeline = useMemo(() => route === null || route === undefined
    ? { activeStep: 0, edgeProgress: 0, progress: 0 }
    : routeTimeline(route, elapsedS), [elapsedS, route]);
  const replayElapsedS = replayStartedAtMs === null ? 0 : Math.max(0, (replayNowMs - replayStartedAtMs) / 1000);
  const replayFrame = useMemo(() => {
    if (tandemReplay === null || facility === null) return null;
    return tandemReplayFrame(
      facility.layout,
      tandemReplay,
      replayElapsedS,
      reducedMotion ? manualReplaySteps : undefined,
    );
  }, [facility, manualReplaySteps, reducedMotion, replayElapsedS, tandemReplay]);

  useEffect(() => {
    if (tandemReplay === null || replayIdentityRef.current === tandemReplay.replay_id) return;
    replayIdentityRef.current = tandemReplay.replay_id;
    const started = performance.now();
    setReplayStartedAtMs(started);
    setReplayNowMs(started);
    setManualReplaySteps(0);
  }, [tandemReplay]);

  useEffect(() => {
    if (journey?.expires_at === null || journey?.expires_at === undefined || remaining > 0) return;
    if (!["session_reserved", "navigating"].includes(journey.state)) return;
    const key = `${journey.journey_id}:${String(journey.version)}:${journey.expires_at}`;
    if (expirySyncRef.current === key) return;
    expirySyncRef.current = key;
    void recover().catch((error: unknown) => { setMessage(journeyError(error)); });
  }, [journey, recover, remaining]);

  useEffect(() => {
    if (journey?.state === "soft_held" || journey?.state === "waiting") {
      void navigate(`/recommend?parkingLotId=${encodeURIComponent(journey.parking_lot_id)}`, { replace: true });
    }
  }, [journey?.parking_lot_id, journey?.state, navigate]);

  if (loading) return <section className="trip-shell"><div className="trip-state" aria-busy="true"><span className="spinner" /><h1>正在恢复当前行程</h1><p>路线与期限从服务端读取，不会因刷新重置。</p></div></section>;
  if (snapshot === null && message !== null) return <section className="trip-shell"><div className="trip-state"><span className="trip-state-icon">!</span><h1>暂时无法读取行程</h1><p>{message}</p><button className="primary-action" onClick={() => { setLoading(true); void recover().catch((error: unknown) => { setMessage(journeyError(error)); }).finally(() => { setLoading(false); }); }}>重新连接</button></div></section>;
  if (journey === null || journey === undefined) return <section className="trip-shell"><div className="trip-state"><span className="trip-state-icon">↗</span><h1>还没有进行中的停车行程</h1><p>先选择停车场并获得智能推荐，确认车位后会在这里显示路线。</p><Link className="primary-action" to="/parking">去找停车场</Link></div></section>;

  const status = statusCopy(journey.state);
  const journeyTarget = journey.space_id ?? "未分配";
  const activeRoute = route !== null && route !== undefined && facility !== null && floorId !== null && !failedReplan;
  const vehicle = activeRoute ? routeVehiclePosition(facility.layout, route, timeline) : null;
  const inspectedState = facility === null ? null : spaceState(facility, inspectedSpaceId);
  const inspectedLabel = inspectedStatusLabel(inspectedState, inspectedSpaceId === journey.space_id);
  const targetFacilitySpace = facility?.layout.spaces.find((item) => item.space_id === journey.space_id);
  const tandemTarget = targetFacilitySpace?.depth !== undefined && targetFacilitySpace.depth > 1;
  const tandemArrivalEligible = journey.state === "navigating" &&
    snapshot?.tandem_arrival_replay_enabled === true &&
    lot?.synthetic === true &&
    facility?.state.demo_profile?.profile_id === "tandem-focus" &&
    tandemTarget;
  const tandemDepartureEligible = journey.state === "occupied" &&
    snapshot?.tandem_departure_replay_enabled === true &&
    lot?.synthetic === true &&
    facility?.state.demo_profile?.profile_id === "tandem-focus" &&
    tandemTarget;
  const can = (operation: string) => journey.legal_operations.includes(operation);
  const run = (command: () => Promise<unknown>, success?: () => void) => {
    setActing(true);
    setMessage(null);
    void command()
      .then(async () => { await recoverFresh(); if (success !== undefined) success(); })
      .catch(async (error: unknown) => {
        setMessage(journeyError(error));
        await recoverFresh().catch(() => undefined);
      })
      .finally(() => { setActing(false); });
  };
  const replace = (command: () => Promise<unknown>) => {
    run(command, () => {
      void navigate(`/recommend?parkingLotId=${encodeURIComponent(journey.parking_lot_id)}`);
    });
  };
  const restartTandemReplay = () => {
    const started = performance.now();
    setReplayStartedAtMs(started);
    setReplayNowMs(started);
    setManualReplaySteps(0);
  };
  return (
    <section className="trip-shell">
      <header className="trip-heading">
        <div><span>当前行程</span><h1>{replayFrame === null ? status.label : replayFrame.complete ? (tandemReplayKind === "arrival" ? "协同入位已完成" : "协同移位已完成") : `正在回放协同${tandemReplayKind === "arrival" ? "入位" : "离场"}`}</h1><p>{replayFrame === null ? status.detail : `服务端已完成权威${tandemReplayKind === "arrival" ? "入位" : "离场"}事务；这里按事件顺序回放阻挡车、缓冲位和当前车辆的移动过程。`}</p></div>
        {["session_reserved", "navigating"].includes(journey.state) ? <div className={`reservation-clock ${remaining <= 60 ? "urgent" : ""}`}><small>服务端预留剩余</small><strong>{formatDuration(remaining)}</strong><span>刷新不续期</span></div> : null}
      </header>
      {message === null ? null : <p className="trip-alert">{message}</p>}
      {failedReplan ? <div className="trip-alert trip-alert-critical"><strong>当前没有可达路线</strong><span>最后一条路线仅作为历史记录，车辆动画已经停止，预留时间没有延长。请重新推荐或稍后重试。</span></div> : null}
      {etaWarning && etaWarningKey !== dismissedEtaWarning ? <div className="trip-alert trip-alert-warning"><div><strong>预计到达时间可能超过当前预留窗口</strong><span>你可以继续按当前路线行驶，也可以释放当前车位并重新推荐。</span></div><div className="inline-actions"><button disabled={acting} className="secondary-action" onClick={() => { setDismissedEtaWarning(etaWarningKey); }}>继续当前路线</button><button disabled={acting || !can("reassign")} className="primary-action" onClick={() => { replace(() => reassignJourney(journey, "eta_exceeds_reservation")); }}>重新推荐</button></div></div> : null}
      <div className="trip-overview">
        <article><small>停车场</small><strong>{lot?.name ?? journey.parking_lot_id}</strong><span>{lot?.region_label ?? "当前场景"}</span></article>
        <article><small>目标车位</small><strong>{journey.space_id ?? "待重新分配"}</strong><span>{lot?.synthetic === true ? "Synthetic 场景" : "当前接口数据"}</span></article>
        <article><small>路线状态</small><strong>{replayFrame !== null ? replayFrame.complete ? (tandemReplayKind === "arrival" ? "协同入位完成" : "协同离场完成") : `协同阶段 ${String(replayFrame.activeStep + 1)}` : failedReplan ? "路线暂不可达 · 动画已停止" : journey.state === "navigating" ? timeline.progress >= 1 ? "已到车位附近" : `已行进 ${String(Math.round(timeline.progress * 100))}%` : activeRoute ? "等待出发" : "路线已结束"}</strong><span>状态版本 v{journey.version}</span></article>
      </div>
      {replayFrame !== null && tandemReplay !== null && tandemReplayKind !== null && facility !== null && floorId !== null ? <TandemReplayPanel kind={tandemReplayKind} replay={tandemReplay} facility={facility} floorId={floorId} selectedSpaceId={inspectedSpaceId} frame={replayFrame} reducedMotion={reducedMotion} onSelect={setInspectedSpaceId} onRestart={restartTandemReplay} onNextStage={() => { setManualReplaySteps((current) => Math.min(tandemReplay.steps.length, current + 1)); }} onContinue={tandemReplayKind === "arrival" ? () => { setDismissedArrivalReplayId(tandemReplay.replay_id); } : undefined} /> : activeRoute ? <div className="trip-grid-layout">
        <article className="route-panel">
          <div className="route-panel-heading" data-route-cost-version={route.cost_version}><div><small>场内路线</small><h2>{facility.layout.nodes.find((node) => node.node_id === route.from_node_id)?.label ?? "当前入口"} → {journey.space_id}</h2></div><div><b>{Math.round(route.distance_m)} m</b><span>约 {Math.ceil(route.dynamic_eta_s)} 秒</span></div></div>
          <div className="route-demo-status"><span><i />管理层路线演示</span><span>{journey.state === "navigating" ? "行进画面仅供理解路线" : "预览完整路线后再出发"}</span></div>
          {facility.layout.floors.length > 1 ? <label className="journey-floor-select">楼层<select aria-label="当前行程楼层" value={floorId} onChange={(event) => { setFloorId(event.target.value); }}><option value="" disabled>选择楼层</option>{facility.layout.floors.map((floor) => <option key={floor.floor_id} value={floor.floor_id}>{floor.label}</option>)}</select></label> : null}
          <div className="journey-facility-stage">
            <FacilityCanvas snapshot={facility} floorId={floorId} selectedSpaceId={inspectedSpaceId} targetSpaceId={journey.space_id ?? null} route={route} vehicle={vehicle?.floor_id === floorId ? vehicle : null} routeMotion={journey.state === "navigating" && motionAllowed} ariaLabel="当前行程完整停车场布局" onSelect={setInspectedSpaceId} />
            <FacilityLegend />
            <p className="journey-space-inspection" aria-live="polite">{inspectedSpaceId === journey.space_id ? `当前行程目标 ${journeyTarget}` : `只读查看 ${inspectedSpaceId ?? "未选择车位"} · 行程目标仍为 ${journeyTarget}`}{inspectedLabel === null ? "" : ` · ${inspectedLabel}`}</p>
            <span className="map-caption">二维管理层布局 · 静态车辆表示当前状态快照中的占用 · 路线动画不是实时定位</span>
          </div>
        </article>
        <aside className="guidance-panel">
          <span>分步指引</span><h2>{journey.state === "navigating" ? "请沿高亮路线前往" : "准备开始场内指引"}</h2>
          {route.instructions[timeline.activeStep] === undefined ? null : <div className="route-next-turn" aria-label="当前指引"><span aria-hidden="true">{timeline.progress >= 1 ? "✓" : maneuverGlyph(route.instructions[timeline.activeStep]?.text ?? "")}</span><div><small>{timeline.progress >= 1 ? "路线演示已到终点" : `第 ${String(timeline.activeStep + 1)} 步 · ${String(route.instructions.length)} 步指引`}</small><strong>{timeline.progress >= 1 ? "请核对车位并自行确认停入" : route.instructions[timeline.activeStep]?.text}</strong></div></div>}
          <div className="route-progress-caption"><span>路线演示进度</span><b>{Math.round(timeline.progress * 100)}%</b></div><div className="route-guidance-progress" role="progressbar" aria-label="路线演示进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(timeline.progress * 100)}><span style={{ width: `${String(timeline.progress * 100)}%` }} /></div>
          <ol>{route.instructions.map((instruction, index) => <li key={`${instruction.edge_id}-${String(instruction.sequence)}`} data-edge-id={instruction.edge_id} aria-current={journey.state === "navigating" && timeline.progress < 1 && index === timeline.activeStep ? "step" : undefined} className={journey.state === "navigating" && index <= timeline.activeStep ? index === timeline.activeStep ? "active current" : "active completed" : ""}><i>{instruction.sequence}</i><div><strong>{instruction.text}</strong><small>{Math.round(instruction.distance_m)} m · 约 {Math.ceil(instruction.travel_time_s)} 秒</small></div></li>)}</ol>
          {journey.state === "session_reserved" ? <button disabled={acting || remaining <= 0} className="primary-action wide" onClick={() => { setActing(true); void startNavigation(journey).then(() => recoverFresh()).catch((error: unknown) => { setMessage(journeyError(error)); return recoverFresh().catch(() => undefined); }).finally(() => { setActing(false); }); }}>{acting ? "正在同步…" : "开始场内指引"}</button> : null}
          {journey.state === "navigating" ? <div className="driving-note"><b>动画不会自动确认停车</b><p>到达画面终点后，请以现场情况为准；只有你的明确操作才会改变停车状态。</p></div> : null}
          {journey.state === "navigating" ? <div className="journey-actions" aria-label="当前行程操作">
            {can("driver_demo_replan") && lot?.synthetic === true ? <><button disabled={acting || remaining <= 0} className="secondary-action" onClick={() => { run(() => driverDemoReplan(journey, "simulate_deviation")); }}>模拟偏航</button><button disabled={acting || remaining <= 0} className="secondary-action" onClick={() => { run(() => driverDemoReplan(journey, "simulate_cost_update")); }}>模拟通道繁忙</button></> : null}
            {can("report_external_occupancy") ? <button disabled={acting || remaining <= 0} className="secondary-action" onClick={() => { replace(() => reportExternalOccupancy(journey)); }}>推荐位被占</button> : null}
            {can("reassign") ? <button disabled={acting || remaining <= 0} className="secondary-action" onClick={() => { replace(() => reassignJourney(journey, "unable_to_park")); }}>无法停入</button> : null}
            {can("occupy") ? tandemArrivalEligible ? <button disabled={acting || remaining <= 0} className="primary-action" onClick={() => { run(() => occupyTandemWithReplay(journey, facility.state.state_version)); }}>{acting ? "正在校验协同入位…" : "我已到达，开始协同入位"}</button> : <button disabled={acting || remaining <= 0} className="primary-action" onClick={() => { run(() => occupyJourney(journey)); }}>我已停入</button> : null}
          </div> : null}
        </aside>
      </div> : <div className="trip-terminal"><h2>{failedReplan ? "路线暂时不可达" : status.label}</h2><p>{failedReplan ? "系统已停止路线动画，原车位预留不会续期。你可以重新推荐，或等待通道恢复后再次模拟路线更新。" : tandemDepartureEligible ? "当前车辆位于内侧纵深位，外侧协同车辆已恢复原位。可继续展示完整协同离场过程。" : status.detail}</p>{failedReplan ? <div className="inline-actions">{can("driver_demo_replan") && lot?.synthetic === true ? <button disabled={acting || remaining <= 0} className="secondary-action" onClick={() => { run(() => driverDemoReplan(journey, "simulate_cost_update")); }}>再次检查路线</button> : null}<button disabled={acting || !can("reassign")} className="primary-action" onClick={() => { replace(() => reassignJourney(journey, "unable_to_park")); }}>重新推荐</button></div> : journey.state === "occupied" ? <div className="inline-actions">{tandemDepartureEligible ? <button disabled={acting || !can("depart")} className="primary-action" onClick={() => { run(() => departTandemWithReplay(journey, facility.state.state_version)); }}>{acting ? "正在校验协同离场…" : "演示协同移位后离场"}</button> : <button disabled={acting || !can("depart")} className="primary-action" onClick={() => { run(() => departJourney(journey)); }}>正常离场</button>}{tandemDepartureEligible ? <button disabled={acting || !can("depart")} className="secondary-action" onClick={() => { run(() => departJourney(journey)); }}>直接结束离场</button> : null}{lot?.synthetic === true && can("reset_demo") ? <button disabled={acting} className="secondary-action" onClick={() => { run(() => resetDemoJourney(journey)); }}>演示重置</button> : null}</div> : <Link className="primary-action" to={`/recommend?parkingLotId=${encodeURIComponent(journey.parking_lot_id)}`}>重新获取推荐</Link>}</div>}
    </section>
  );
}
