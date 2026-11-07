import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  loadParkingDiscovery,
  type DiscoveryLotSummary,
  type DiscoveryReferencePoint,
  type ParkingDiscoveryData,
  type ParkingLot,
} from "../api/client";
import {
  availabilityLabel,
  availabilityLevel,
  formatDistance,
  formatEta,
  formatUpdatedAt,
  mapPosition,
} from "./mapConfig";

type LoadState =
  | { status: "loading" }
  | { status: "ready"; data: ParkingDiscoveryData }
  | { status: "error"; error: ApiError };

function Price({ lot }: { lot: ParkingLot }) {
  return <span><strong>¥{lot.pricing.first_hour_yuan.toFixed(0)}</strong>/首小时</span>;
}

function StatePanel({
  title,
  message,
  action,
  actionLabel = "重新加载",
}: {
  title: string;
  message: string;
  action?: () => void;
  actionLabel?: string;
}) {
  return (
    <section className="state-panel" role="status">
      <span aria-hidden="true">!</span>
      <h2>{title}</h2>
      <p>{message}</p>
      {action === undefined ? null : <button onClick={action}>{actionLabel}</button>}
    </section>
  );
}

function errorPresentation(error: ApiError): { title: string; message: string } {
  if (error.status === 503) {
    return { title: "停车场数据源暂时不可用", message: "服务已失败关闭，不会用本地随机数据冒充实时空位。" };
  }
  if (error.status === 0 && error.code !== "REQUEST_TIMEOUT") {
    return { title: "当前处于离线状态", message: error.message };
  }
  if (["CONTRACT_MISMATCH", "DISCOVERY_SCOPE_MISMATCH", "INVALID_JSON_RESPONSE"].includes(error.code)) {
    return { title: "停车场数据暂时无法使用", message: `${error.message}。请重试；若持续出现请联系演示人员。` };
  }
  return { title: "停车场服务响应异常", message: error.message };
}

function nearestReference(
  references: DiscoveryReferencePoint[],
  x: number,
  y: number,
): DiscoveryReferencePoint | undefined {
  return references.reduce<DiscoveryReferencePoint | undefined>((nearest, reference) => {
    if (nearest === undefined) return reference;
    const distance = Math.hypot(reference.position.x_pct - x, reference.position.y_pct - y);
    const nearestDistance = Math.hypot(nearest.position.x_pct - x, nearest.position.y_pct - y);
    return distance < nearestDistance ? reference : nearest;
  }, undefined);
}

export function ParkingDiscoveryPage() {
  const { parkingLotId } = useParams();
  const navigate = useNavigate();
  const [loadKey, setLoadKey] = useState(0);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [query, setQuery] = useState("");
  const [activeRegion, setActiveRegion] = useState("全部区域");
  const [referenceId, setReferenceId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void loadParkingDiscovery(controller.signal)
      .then((data) => {
        setState({ status: "ready", data });
        setReferenceId((current) =>
          data.area.references.some((item) => item.reference_id === current)
            ? current
            : data.area.default_reference_id,
        );
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setState({ status: "error", error: error instanceof ApiError ? error : new ApiError(0, "UNKNOWN_ERROR", "停车场数据加载失败") });
      });
    return () => {
      controller.abort();
    };
  }, [loadKey]);

  const data = state.status === "ready" ? state.data : null;
  const lots = useMemo(() => data?.lots ?? [], [data]);
  const discoveryByLot = useMemo(
    () => new Map((data?.area.lots ?? []).map((item) => [item.parking_lot_id, item])),
    [data],
  );
  const regions = useMemo(() => ["全部区域", ...new Set(lots.map((lot) => lot.region_label))], [lots]);
  const normalized = query.trim().toLocaleLowerCase("zh-CN");
  const filtered = useMemo(
    () => lots.filter((lot) =>
      (activeRegion === "全部区域" || lot.region_label === activeRegion) &&
      (normalized.length === 0 || `${lot.name} ${lot.region_label}`.toLocaleLowerCase("zh-CN").includes(normalized))),
    [activeRegion, lots, normalized],
  );
  const knownSelected = parkingLotId === undefined ? undefined : lots.find((lot) => lot.parking_lot_id === parkingLotId);
  const selected = parkingLotId === undefined ? filtered[0] : filtered.find((lot) => lot.parking_lot_id === parkingLotId);
  const currentReference = data?.area.references.find((item) => item.reference_id === referenceId) ?? data?.area.references[0];
  const estimateFor = (summary: DiscoveryLotSummary) =>
    summary.offsite_estimates.find((item) => item.reference_id === currentReference?.reference_id);
  const filteredWithDiscovery = filtered.flatMap((lot) => {
    const discovery = discoveryByLot.get(lot.parking_lot_id);
    return discovery === undefined ? [] : [{ lot, discovery }];
  });
  const totalAvailable = filtered.reduce((total, lot) => total + lot.available_spaces, 0);
  const distances = filteredWithDiscovery.flatMap(({ discovery }) => {
    const estimate = estimateFor(discovery);
    return estimate === undefined ? [] : [estimate.distance_m];
  });
  const nearestDistance = distances.length === 0 ? null : Math.min(...distances);

  useEffect(() => {
    if (data === null || parkingLotId === undefined || knownSelected === undefined) return;
    if (!filtered.some((lot) => lot.parking_lot_id === parkingLotId)) {
      const next = filtered[0];
      void navigate(next === undefined ? "/parking" : `/parking/${next.parking_lot_id}`, { replace: true });
    }
  }, [data, filtered, knownSelected, navigate, parkingLotId]);

  function selectLot(lot: ParkingLot) {
    void navigate(`/parking/${lot.parking_lot_id}`);
  }

  function retry() {
    setState({ status: "loading" });
    setLoadKey((value) => value + 1);
  }

  function updateReference(event: MouseEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest("button") || data === null) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = ((event.clientX - bounds.left) / bounds.width) * 100;
    const y = ((event.clientY - bounds.top) / bounds.height) * 100;
    const reference = nearestReference(data.area.references, x, y);
    if (reference !== undefined) {
      setReferenceId(reference.reference_id);
    }
  }

  if (state.status === "loading") {
    return <section className="discovery-page" aria-busy="true"><div className="page-heading"><span className="eyebrow">SMART PARKING · 城市出行</span><h1>正在读取停车场</h1></div><div className="loading-grid"><i /><i /><i /></div></section>;
  }
  if (state.status === "error") {
    const presentation = errorPresentation(state.error);
    return <StatePanel {...presentation} action={retry} />;
  }
  if (lots.length === 0) {
    return <StatePanel title="当前没有可展示的停车场" message="数据源已连接，但没有返回停车场。请稍后刷新或联系演示人员。" action={retry} />;
  }
  if (parkingLotId !== undefined && knownSelected === undefined) {
    return <StatePanel title="未找到该停车场" message="这个停车场 ID 不属于当前数据源，请返回列表重新选择。" action={() => { void navigate("/parking", { replace: true }); }} actionLabel="返回停车场列表" />;
  }

  const sourceIsSynthetic = state.data.area.synthetic;
  const discoveryDegraded = state.data.area.source_health === "degraded";
  const sourceLabel = discoveryDegraded
    ? `${sourceIsSynthetic ? "Synthetic" : "真实"} 区域摘要已降级`
    : sourceIsSynthetic ? "固定 synthetic 场景" : "真实停车数据";
  const selectedDiscovery = selected === undefined ? undefined : discoveryByLot.get(selected.parking_lot_id);
  const selectedEstimate = selectedDiscovery === undefined ? undefined : estimateFor(selectedDiscovery);

  return (
    <section className="discovery-page">
      <header className="page-heading">
        <div><span className="eyebrow">SMART PARKING · 城市出行</span><h1>更快找到合适的车位</h1><p>比较区域内的空位、价格与充电概况，再进入智能停车。</p></div>
        <span className={`source-pill ${discoveryDegraded ? "degraded" : sourceIsSynthetic ? "" : "real"}`}><i />{sourceLabel}</span>
      </header>

      <div className="search-row">
        <label className="search-box"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => { setQuery(event.target.value); }} type="search" placeholder="搜索名称或区域，例如：学校、医院" /></label>
        <div className="region-filters" aria-label="停车区域">
          {regions.map((region) => <button key={region} type="button" className={activeRegion === region ? "active" : ""} onClick={() => { setActiveRegion(region); }}>{region}</button>)}
        </div>
      </div>

      <div className="summary-row" aria-label="停车场概览">
        <article><small>匹配停车场</small><strong>{filtered.length}</strong><span>个{sourceIsSynthetic ? "模拟" : "可用"}场景</span></article>
        <article><small>合计可用车位</small><strong>{totalAvailable}</strong><span>当前接口快照</span></article>
        <article><small>最近场外距离</small><strong>{nearestDistance === null ? "—" : formatDistance(nearestDistance)}</strong><span>参考点：{currentReference?.label ?? "未知"}</span></article>
      </div>

      {filtered.length === 0 ? (
        <StatePanel title="没有匹配的停车场" message="可尝试其他名称或区域，或清空搜索关键词。" />
      ) : (
        <div className="discovery-layout">
          <div className="region-map" aria-label="区域停车场示意图" onClick={updateReference}>
            <div className="map-heading"><div><small>{sourceIsSynthetic ? "模拟区域坐标" : "区域坐标"}</small><h2>停车场位置示意</h2></div><span>不表示真实道路</span></div>
            <div className="reference-controls" aria-label="距离参考点">
              {state.data.area.references.map((reference) => (
                <button
                  key={reference.reference_id}
                  type="button"
                  className={reference.reference_id === currentReference?.reference_id ? "active" : ""}
                  onClick={() => { setReferenceId(reference.reference_id); }}
                >
                  {reference.label}
                </button>
              ))}
            </div>
            <svg viewBox="0 0 900 560" preserveAspectRatio="none" aria-hidden="true"><path className="water" d="M-60 40 C170 140 115 390 390 640" /><g className="area-shapes"><rect x="505" y="50" width="310" height="160" rx="42"/><rect x="305" y="190" width="250" height="160" rx="48"/><rect x="58" y="300" width="250" height="190" rx="54"/><rect x="545" y="330" width="290" height="165" rx="48"/></g></svg>
            {currentReference === undefined ? null : <span className="location-dot" style={{ left: `${String(currentReference.position.x_pct)}%`, top: `${String(currentReference.position.y_pct)}%` }}><i />{currentReference.label}</span>}
            {filteredWithDiscovery.map(({ lot, discovery }) => {
              const position = mapPosition(lot, discovery);
              return <button key={lot.parking_lot_id} type="button" className={`map-pin ${availabilityLevel(lot)} ${selected?.parking_lot_id === lot.parking_lot_id ? "selected" : ""}`} style={{ left: `${String(position.x)}%`, top: `${String(position.y)}%` }} onClick={() => { selectLot(lot); }} aria-label={`${lot.name}，${String(lot.available_spaces)} 个空位`}><b>P</b><span>{position.shortName}</span><small>{lot.available_spaces} 空位</small></button>;
            })}
            <div className="map-boundary">点击空白区域将吸附到版本化参考点，并更新场外距离与 ETA；不提供真实道路导航</div>
          </div>

          <div className="lot-list" aria-label="停车场列表">
            {filteredWithDiscovery.map(({ lot, discovery }) => {
              const position = mapPosition(lot, discovery);
              const estimate = estimateFor(discovery);
              return <button key={lot.parking_lot_id} type="button" className={selected?.parking_lot_id === lot.parking_lot_id ? "selected" : ""} onClick={() => { selectLot(lot); }}><span className="lot-symbol">{position.icon}</span><span className="lot-copy"><strong>{lot.name}</strong><small>{lot.region_label} · {lot.opening_status === "open" ? "营业中" : "暂不可用"} · ¥{lot.pricing.first_hour_yuan.toFixed(0)}/首小时 · 充电位 {lot.charging_spaces}</small><small>更新 {formatUpdatedAt(lot.updated_at)}</small></span><span className={`availability ${availabilityLevel(lot)}`}><b>{lot.available_spaces}</b> 空位{estimate === undefined ? null : <small>{formatDistance(estimate.distance_m)} · {formatEta(estimate.eta_s)}</small>}</span></button>;
            })}
          </div>

          {selected === undefined || selectedDiscovery === undefined ? null : (
            <aside className="lot-detail">
              <div className="detail-heading"><span className="lot-symbol large">{mapPosition(selected, selectedDiscovery).icon}</span><div><small>{selected.region_label}</small><h2>{selected.name}</h2></div></div>
              <span className={`status-line ${availabilityLevel(selected)}`}><i />{availabilityLabel(selected)} · {selected.available_spaces} / {selected.total_spaces} 可用</span>
              <div className="detail-stats"><article><small>首小时参考价</small><Price lot={selected} /></article><article><small>充电位配置</small><strong>{selected.charging_spaces}</strong><span>个车位</span></article><article><small>营业状态</small><strong>{selected.opening_status === "open" ? "开放" : selected.opening_status === "closed" ? "关闭" : "未知"}</strong><span>{selectedDiscovery.opening_hours_label}</span></article><article><small>数据状态</small><strong>{selected.data_source.health === "healthy" ? "正常" : "异常"}</strong><span>{selected.data_source.mode}</span></article></div>
              {selectedEstimate === undefined ? null : <div className="offsite-summary"><b>{formatDistance(selectedEstimate.distance_m)} · {formatEta(selectedEstimate.eta_s)}</b><p>{sourceIsSynthetic ? "版本化 synthetic 场外摘要" : "数据源提供的场外摘要"}；场内路线从入口另行计算。</p></div>}
              <button className="layout-button" type="button" onClick={() => { void navigate(`/parking/${selected.parking_lot_id}/layout`); }}>查看完整布局</button>
              <button className="continue-button" disabled={selected.opening_status !== "open" || selected.data_source.health !== "healthy"} onClick={() => { void navigate(`/recommend?parkingLotId=${selected.parking_lot_id}`); }}>{selected.opening_status === "closed" ? "当前已停止营业" : selected.opening_status === "unknown" ? "营业状态未知，暂不可选择" : selected.data_source.health !== "healthy" ? "数据异常，暂不可选择" : "选择此停车场"}</button>
              <small className="updated-line">数据更新时间：{formatUpdatedAt(selected.updated_at)} · {selected.pricing.note}</small>
            </aside>
          )}
        </div>
      )}
    </section>
  );
}
