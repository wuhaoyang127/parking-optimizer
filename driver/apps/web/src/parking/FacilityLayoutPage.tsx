import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { loadFacilitySnapshot, loadFacilityState, loadRoutePreview, type FacilitySnapshot, type RoutePreview } from "../api/facilityClient";
import { FacilityCanvas } from "./facility/FacilityCanvas";
import { FacilityLegend } from "./facility/FacilityLegend";
import { FacilitySelectionDetails } from "./facility/FacilitySelectionDetails";
import { facilityStats, sourceLabel } from "./facility/viewModel";

type PageState = { status: "loading" } | { status: "error"; error: ApiError } | { status: "ready"; snapshot: FacilitySnapshot };

function previewScopeFor(page: PageState, searchParams: URLSearchParams): string {
  if (page.status !== "ready") return "";
  const floorId = searchParams.get("floor") ?? page.snapshot.layout.default_floor_id;
  const entranceId = searchParams.get("entrance") ?? page.snapshot.layout.default_entrance_id;
  return `${page.snapshot.layout.parking_lot_id}|${page.snapshot.layout.layout_version}|${page.snapshot.state.scenario_version}|${page.snapshot.state.state_version}|${floorId}|${entranceId}|${searchParams.get("space") ?? ""}`;
}

export function FacilityLayoutPage() {
  const { parkingLotId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [reloadKey, setReloadKey] = useState(0);
  const [page, setPage] = useState<PageState>({ status: "loading" });
  const [preview, setPreview] = useState<RoutePreview | null>(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const requestSequence = useRef(0);
  const routeSequence = useRef(0);
  const pollInFlight = useRef(false);
  const pollAbort = useRef<AbortController | null>(null);
  const routeScope = useRef("");
  const shellRef = useRef<HTMLDivElement>(null);
  const focusRef = useRef<() => void>(() => undefined);

  useLayoutEffect(() => {
    routeSequence.current += 1;
    routeScope.current = previewScopeFor(page, searchParams);
  }, [page, searchParams]);

  useEffect(() => {
    if (parkingLotId === undefined) return;
    requestSequence.current += 1;
    pollAbort.current?.abort();
    pollInFlight.current = false;
    const controller = new AbortController();
    void loadFacilitySnapshot(parkingLotId, controller.signal)
      .then((snapshot) => { setPreview(null); setPage({ status: "ready", snapshot }); })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setPage({ status: "error", error: error instanceof ApiError ? error : new ApiError(0, "UNKNOWN_ERROR", "完整布局加载失败") });
      });
    return () => { controller.abort(); requestSequence.current += 1; pollAbort.current?.abort(); pollInFlight.current = false; };
  }, [parkingLotId, reloadKey]);

  const refreshState = useCallback(async () => {
    if (page.status !== "ready" || parkingLotId === undefined || pollInFlight.current || document.visibilityState === "hidden" || !navigator.onLine) return;
    pollInFlight.current = true;
    const sequence = ++requestSequence.current;
    const controller = new AbortController();
    pollAbort.current = controller;
    const requestedLotId = parkingLotId;
    const requestedLayoutVersion = page.snapshot.layout.layout_version;
    const requestedScenarioVersion = page.snapshot.state.scenario_version;
    try {
      const nextState = await loadFacilityState(parkingLotId, page.snapshot.layout, controller.signal);
      if (sequence !== requestSequence.current) return;
      setPage((current) => current.status === "ready" && current.snapshot.layout.parking_lot_id === requestedLotId && current.snapshot.layout.layout_version === requestedLayoutVersion && current.snapshot.state.scenario_version === requestedScenarioVersion && nextState.scenario_version === requestedScenarioVersion ? { status: "ready", snapshot: { layout: current.snapshot.layout, state: nextState } } : current);
      const selectedId = searchParams.get("space");
      const selectedState = nextState.spaces.find((item) => item.space_id === selectedId);
      setPreview((current) => current?.state_version === nextState.state_version && selectedState?.assignable === true ? current : null);
      routeSequence.current += 1;
      setRouteLoading(false);
      setInlineError(null);
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) setInlineError(error instanceof ApiError ? error.message : "状态刷新失败");
    } finally {
      if (pollAbort.current === controller) { pollAbort.current = null; pollInFlight.current = false; }
    }
  }, [page, parkingLotId, searchParams]);

  useEffect(() => {
    if (page.status !== "ready") return;
    const timer = globalThis.setInterval(() => { void refreshState(); }, 3000);
    const resume = () => { if (document.visibilityState === "visible") void refreshState(); };
    document.addEventListener("visibilitychange", resume);
    globalThis.addEventListener("online", resume);
    return () => { globalThis.clearInterval(timer); document.removeEventListener("visibilitychange", resume); globalThis.removeEventListener("online", resume); };
  }, [page.status, refreshState]);

  if (parkingLotId === undefined) return <section className="state-panel"><span aria-hidden="true">!</span><h2>停车场 ID 缺失</h2><p>请从停车场列表进入完整布局。</p><Link className="secondary-action" to="/parking">返回停车场列表</Link></section>;
  if (page.status === "loading" || (page.status === "ready" && page.snapshot.layout.parking_lot_id !== parkingLotId)) return <section className="facility-page" aria-busy="true"><div className="facility-page-heading"><span>完整布局</span><h1>正在读取停车场</h1></div><div className="facility-loading" /></section>;
  if (page.status === "error") return <section className="state-panel"><span aria-hidden="true">!</span><h2>{page.error.status === 404 ? "未找到该停车场" : "完整布局暂时不可用"}</h2><p>{page.error.message}</p><button type="button" onClick={() => { setPage({ status: "loading" }); setReloadKey((value) => value + 1); }}>重新加载</button><Link className="secondary-action" to="/parking">返回停车场列表</Link></section>;

  const { snapshot } = page;
  const floorId = searchParams.get("floor") ?? snapshot.layout.default_floor_id;
  const entranceId = searchParams.get("entrance") ?? snapshot.layout.default_entrance_id;
  const selectedSpaceId = searchParams.get("space");
  const entrance = snapshot.layout.entrances.find((item) => item.entrance_id === entranceId);
  const selectedSpace = snapshot.layout.spaces.find((item) => item.space_id === selectedSpaceId);
  const invalidReference = !snapshot.layout.floors.some((item) => item.floor_id === floorId) || entrance === undefined || (selectedSpaceId !== null && selectedSpace?.floor_id !== floorId);
  if (invalidReference) return <section className="state-panel"><span aria-hidden="true">!</span><h2>布局链接已失效</h2><p>链接中的楼层、入口或车位不属于当前发布布局。系统不会猜测或替换目标。</p><button type="button" onClick={() => { setSearchParams({ floor: snapshot.layout.default_floor_id, entrance: snapshot.layout.default_entrance_id }, { replace: true }); }}>打开默认布局</button></section>;

  const stats = facilityStats(snapshot);
  const expectedPreviewScope = previewScopeFor(page, searchParams);
  const visiblePreview = preview?.parking_lot_id === snapshot.layout.parking_lot_id && preview.layout_version === snapshot.layout.layout_version && preview.scenario_version === snapshot.state.scenario_version && preview.state_version === snapshot.state.state_version && preview.entrance_id === entranceId && preview.target_space_id === selectedSpaceId ? preview : null;
  function updateParam(name: "space" | "entrance", value: string) {
    const next = new URLSearchParams(searchParams);
    next.set("floor", floorId);
    next.set(name, value);
    if (name === "space") setPreview(null);
    routeSequence.current += 1;
    setRouteLoading(false);
    setSearchParams(next);
  }

  function updateFloor(nextFloorId: string) {
    const next = new URLSearchParams(searchParams);
    next.set("floor", nextFloorId);
    next.set("entrance", entranceId);
    next.delete("space");
    routeSequence.current += 1;
    setRouteLoading(false);
    setPreview(null);
    setSearchParams(next);
  }

  async function requestPreview() {
    if (selectedSpaceId === null) return;
    const controller = new AbortController();
    const sequence = ++routeSequence.current;
    const requestedScope = expectedPreviewScope;
    setRouteLoading(true);
    setInlineError(null);
    try {
      const response = await loadRoutePreview(snapshot, entranceId, selectedSpaceId, controller.signal);
      if (sequence === routeSequence.current && requestedScope === routeScope.current) setPreview(response);
    } catch (error) {
      if (sequence === routeSequence.current && requestedScope === routeScope.current) {
        setPreview(null);
        setInlineError(error instanceof ApiError ? error.message : "路线预览失败");
        if (error instanceof ApiError && error.status === 409) await refreshState();
      }
    } finally {
      if (sequence === routeSequence.current) setRouteLoading(false);
    }
  }

  return (
    <section className="facility-page" ref={shellRef}>
      <header className="facility-page-heading"><div><Link to={`/parking/${snapshot.layout.parking_lot_id}`}>← 返回停车场</Link><span>完整停车场布局</span><h1>停车场全景</h1><p>{sourceLabel(snapshot.state.source.source_kind)} · 管理层二维示意 · 更新于 {new Date(snapshot.state.observed_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</p></div><button type="button" className="icon-command" title="全屏查看" aria-label="全屏查看" onClick={() => { void shellRef.current?.requestFullscreen(); }}>⛶</button></header>
      <div className="facility-stat-strip" aria-label="停车场状态统计"><span><small>总车位</small><strong>{stats.total}</strong></span><span><small>空闲</small><strong>{stats.available}</strong></span><span><small>占用</small><strong>{stats.occupied}</strong></span><span><small>不可用</small><strong>{stats.unavailable}</strong></span><span><small>未知</small><strong>{stats.unknown}</strong></span><span><small>充电</small><strong>{stats.charging}</strong></span><span><small>纵深</small><strong>{stats.tandem}</strong></span></div>
      {inlineError === null ? null : <div className="facility-inline-error" role="alert">{inlineError}</div>}
      <div className="facility-workspace">
        <div className="facility-stage"><FacilityCanvas key={floorId} snapshot={snapshot} floorId={floorId} selectedSpaceId={selectedSpaceId} route={visiblePreview?.route ?? null} routeMotion onSelect={(id) => { updateParam("space", id); }} onFocusReady={(focus) => { focusRef.current = focus; }} /><FacilityLegend /></div>
        <FacilitySelectionDetails snapshot={snapshot} floorId={floorId} selectedSpaceId={selectedSpaceId} entranceId={entranceId} preview={visiblePreview} routeLoading={routeLoading} onFloor={updateFloor} onEntrance={(id) => { updateParam("entrance", id); setPreview(null); }} onPreview={() => { void requestPreview(); }} onFocus={() => { focusRef.current(); }} />
      </div>
    </section>
  );
}
