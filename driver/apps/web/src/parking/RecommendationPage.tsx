import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import {
  advanceDriverDemoProfile,
  cancelJourney,
  confirmRecommendation,
  createRecommendation,
  declineTandem,
  loadCurrentDriverJourney,
  loadDriverContext,
  loadJourneyParkingLot,
  RecommendationApiError,
  retryWaiting,
  selectAlternative,
  type DriverContext,
  type JourneyRecommendation,
} from "../api/recommendationClient";
import { loadFacilitySnapshot } from "../api/facilityClient";
import { conservativeServerClock } from "./serverClock";

const ACTIVE_STATES = new Set(["waiting", "soft_held", "session_reserved", "navigating", "occupied"]);

function friendlyReason(result: JourneyRecommendation, requiresCharging: boolean): string {
  if (result.recommendation.degraded) {
    return result.recommendation.degradation_reason ?? "推荐服务已降级，当前使用常规推荐。";
  }
  if (result.recommendation.solver_status !== "success") {
    return requiresCharging
      ? "当前没有满足充电条件的可用车位，系统不会改配普通车位。"
      : "当前没有同时满足可用性与到达条件的车位。";
  }
  const route = result.recommendation.route;
  if (result.recommendation.explanation_codes.includes("USER_SELECTED_ALTERNATIVE")) {
    return `已按你的选择切换车位，预计场内行驶 ${String(Math.ceil(route?.dynamic_eta_s ?? 0))} 秒。`;
  }
  return `该车位当前可用，路线可达，预计场内行驶 ${String(Math.ceil(route?.dynamic_eta_s ?? 0))} 秒。`;
}

function errorMessage(error: unknown): string {
  if (error instanceof RecommendationApiError) {
    if (error.status === 409) return "页面状态已变化，正在读取服务端最新结果。";
    if (error.status === 0) return "网络暂时不可用。已保留上次同步结果，不会延长车位期限。";
    return error.message;
  }
  return "发生了未预期的错误，请返回停车场列表后重试。";
}

export function RecommendationPage() {
  const [params] = useSearchParams();
  const parkingLotId = params.get("parkingLotId");
  const navigate = useNavigate();
  const [context, setContext] = useState<DriverContext | null>(null);
  const [parkingLotLabel, setParkingLotLabel] = useState<{ id: string; label: string } | null>(null);
  const [result, setResult] = useState<JourneyRecommendation | null>(null);
  const [entranceId, setEntranceId] = useState("");
  const [requiresCharging, setRequiresCharging] = useState(false);
  const [expectedStayMinutes, setExpectedStayMinutes] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [waitingSeconds, setWaitingSeconds] = useState(0);
  const [waitingSince, setWaitingSince] = useState<string | null>(null);
  const [serverClock, setServerClock] = useState<{ observedAt: string; monotonicAt: number } | null>(null);

  const contextLotId = context?.parking_lot_id;
  useEffect(() => {
    if (contextLotId === undefined) return;
    const controller = new AbortController();
    let active = true;
    void loadJourneyParkingLot(contextLotId, controller.signal)
      .then((lot) => {
        if (lot.parking_lot_id !== contextLotId) {
          throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "停车场名称与当前需求不一致");
        }
        if (active) setParkingLotLabel({ id: contextLotId, label: lot.name });
      })
      .catch(() => {
        if (active) setParkingLotLabel({ id: contextLotId, label: "名称暂不可用，请返回停车场列表核对" });
      });
    return () => { active = false; controller.abort(); };
  }, [contextLotId]);

  const recover = useCallback(async () => {
    const requestStartedAt = performance.now();
    const snapshot = await loadCurrentDriverJourney();
    const requestReceivedAt = performance.now();
    setServerClock(conservativeServerClock(
      snapshot.observed_at,
      requestStartedAt,
      requestReceivedAt,
    ));
    const journey = snapshot.journey;
    const recommendation = snapshot.recommendation;
    const driver = snapshot.driver;
    if (
      journey !== null && journey !== undefined &&
      recommendation !== null && recommendation !== undefined &&
      driver !== null && driver !== undefined &&
      ACTIVE_STATES.has(journey.state)
    ) {
      const recovered: JourneyRecommendation = {
        schema_version: "2.0.0",
        journey,
        recommendation,
      };
      setResult(recovered);
      setWaitingSince(snapshot.waiting_since ?? null);
      setRequiresCharging(driver.requires_charging);
      setEntranceId(driver.entrance_node_id);
      const recoveredContext = await loadDriverContext(journey.parking_lot_id);
      setContext(recoveredContext);
      if (["session_reserved", "navigating", "occupied"].includes(journey.state)) {
        void navigate("/journey", { replace: true });
      }
      return true;
    }
    if (journey !== null && journey !== undefined && !ACTIVE_STATES.has(journey.state)) {
      setMessage(
        journey.state === "expired"
          ? "车位软锁已到期并释放，请重新推荐。"
          : "上一次停车需求已结束，请创建新的推荐。",
      );
    }
    setResult(null);
    return false;
  }, [navigate]);

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const restored = await recover();
        if (!restored && parkingLotId !== null) {
          const nextContext = await loadDriverContext(parkingLotId);
          setContext(nextContext);
          const onlyEntrance = nextContext.entrances.length === 1 ? nextContext.entrances[0] : undefined;
          setEntranceId(onlyEntrance?.node_id ?? "");
        }
      } catch (error) {
        setMessage(errorMessage(error));
      } finally {
        setLoading(false);
      }
    })();
  }, [parkingLotId, recover]);

  useEffect(() => {
    const tick = () => {
      const now = serverClock === null
        ? Date.now()
        : new Date(serverClock.observedAt).getTime() + (performance.now() - serverClock.monotonicAt);
      const expiresAt = result?.journey.expires_at;
      setRemaining(expiresAt === null || expiresAt === undefined
        ? 0
        : Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1000)));
      if (result?.journey.state === "waiting") {
        const start = waitingSince ?? result.journey.updated_at;
        setWaitingSeconds(Math.max(0, Math.floor((now - new Date(start).getTime()) / 1000)));
      }
    };
    tick();
    const timer = globalThis.setInterval(tick, 1000);
    return () => { globalThis.clearInterval(timer); };
  }, [result, serverClock, waitingSince]);

  useEffect(() => {
    const sync = () => {
      if (document.visibilityState !== "visible") return;
      void recover().catch((error: unknown) => { setMessage(errorMessage(error)); });
    };
    globalThis.addEventListener("online", sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      globalThis.removeEventListener("online", sync);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [recover]);

  useEffect(() => {
    if (result?.journey.state !== "soft_held" || remaining > 0) return;
    const timer = globalThis.setTimeout(() => { void recover().catch((error: unknown) => { setMessage(errorMessage(error)); }); }, 300);
    return () => { globalThis.clearTimeout(timer); };
  }, [recover, remaining, result?.journey.state]);

  const spaces = useMemo(
    () => new Map((context?.spaces ?? []).map((space) => [space.space_id, space])),
    [context],
  );
  const tandemIds = useMemo(
    () => new Set((context?.tandem_groups ?? []).flatMap((group) => group.space_ids_near_to_deep)),
    [context],
  );
  const primaryId = result?.recommendation.recommended_space_id ?? null;
  const primary = primaryId === null ? undefined : spaces.get(primaryId);
  const isTandem = primaryId !== null && tandemIds.has(primaryId);
  const alternativeId = result?.recommendation.alternative_space_ids[0];
  const alternative = alternativeId === undefined ? undefined : spaces.get(alternativeId);

  async function run(action: () => Promise<JourneyRecommendation>): Promise<void> {
    setSubmitting(true);
    setMessage(null);
    try {
      const next = await action();
      setResult(next);
      if (next.recommendation.degraded) setMessage(next.recommendation.degradation_reason ?? "推荐服务已降级，当前使用常规推荐");
      if (next.journey.state === "waiting") {
        setWaitingSince((current) => current ?? next.journey.updated_at);
      } else {
        setWaitingSince(null);
      }
    } catch (error) {
      setMessage(errorMessage(error));
      if (error instanceof RecommendationApiError && error.status === 409) {
        try { await recover(); } catch (recoveryError) { setMessage(errorMessage(recoveryError)); }
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function switchDemoProfile(): Promise<void> {
    if (context === null || result !== null) return;
    const currentContext = context;
    const currentProfile = context.demo_profile;
    if (currentProfile === null || currentProfile === undefined) return;
    setSubmitting(true);
    setMessage(null);
    try {
      const snapshot = await loadFacilitySnapshot(
        currentContext.parking_lot_id,
        new AbortController().signal,
      );
      if (snapshot.state.demo_profile?.profile_id !== currentProfile.profile_id) {
        throw new RecommendationApiError(409, "PROFILE_STALE", "模拟状态已变化");
      }
      const changed = await advanceDriverDemoProfile(
        currentContext.parking_lot_id,
        currentProfile,
        snapshot.state.state_version,
      );
      const nextContext = await loadDriverContext(currentContext.parking_lot_id);
      if (nextContext.demo_profile?.profile_id !== changed.demo_profile.profile_id) {
        throw new RecommendationApiError(200, "CONTRACT_MISMATCH", "模拟状态切换后上下文不一致");
      }
      setContext(nextContext);
      if (!nextContext.entrances.some((item) => item.node_id === entranceId)) {
        setEntranceId(nextContext.entrances.length === 1 ? nextContext.entrances[0]?.node_id ?? "" : "");
      }
      setMessage(`已切换为“${changed.demo_profile.label}”，下一次推荐将使用这组模拟状态。`);
    } catch (error) {
      setMessage(errorMessage(error));
      if (error instanceof RecommendationApiError && error.status === 409) {
        try { setContext(await loadDriverContext(currentContext.parking_lot_id)); } catch (reloadError) { setMessage(errorMessage(reloadError)); }
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <section className="recommend-shell" aria-busy="true"><div className="recommend-state"><span className="spinner" /><h1>正在恢复停车需求</h1><p>先读取服务端权威行程，再决定是否创建新推荐。</p></div></section>;

  if (context === null) {
    return <section className="recommend-shell"><div className="recommend-state"><span className="recommend-icon">⌖</span><h1>请先选择停车场</h1><p>智能推荐需要明确停车场，系统不会替你猜测。</p><Link className="primary-action" to="/parking">返回找停车场</Link>{message === null ? null : <p className="inline-alert">{message}</p>}</div></section>;
  }

  if (result?.journey.state === "waiting") {
    return <section className="recommend-shell"><header className="recommend-heading"><span>智能停车{context.demo_profile === null || context.demo_profile === undefined ? "" : ` · ${context.demo_profile.label}`}</span><h1>正在等待合规车位</h1><p>{requiresCharging ? "充电需求已保留，不会自动降级为普通车位。" : "当前没有满足条件的可用车位。"}</p></header><div className="waiting-card"><span className="pulse-ring">…</span><strong>已等待 {Math.floor(waitingSeconds / 60)}:{String(waitingSeconds % 60).padStart(2, "0")}</strong><p>不显示虚构的队列位置或预计等待时间。只有本页面刷新时才会重新尝试锁位。</p><div className="action-row"><button disabled={submitting} className="primary-action" onClick={() => { void run(() => retryWaiting(result)); }}>刷新车位</button><button disabled={submitting} className="secondary-action" onClick={() => { void (async () => { setSubmitting(true); try { await cancelJourney(result.journey); setResult(null); } catch (error) { setMessage(errorMessage(error)); try { await recover(); } catch (recoveryError) { setMessage(errorMessage(recoveryError)); } } finally { setSubmitting(false); } })(); }}>取消等待</button></div></div>{message === null ? null : <p className="inline-alert">{message}</p>}</section>;
  }

  if (result === null) {
    return <section className="recommend-shell"><header className="recommend-heading"><span>需求确认</span><h1>告诉我们你从哪里进入</h1><p>推荐会校验可用性、充电硬条件和场内到达时间，成功锁位后才显示结果。</p></header><div className="request-grid"><article className="request-card"><h2>停车需求</h2><label>停车场<strong>{parkingLotLabel?.id === context.parking_lot_id ? parkingLotLabel.label : "正在读取停车场名称…"}</strong></label>{context.demo_profile === null || context.demo_profile === undefined ? null : <div className="demo-profile-card"><div><span>模拟状态 {context.demo_profile.ordinal}/{context.demo_profile.total}</span><strong>{context.demo_profile.label}</strong></div><p>{context.demo_profile.description}</p><button type="button" className="secondary-action" disabled={submitting} onClick={() => { void switchDemoProfile(); }}>{submitting ? "正在切换…" : "换一组模拟状态"}</button></div>}<label>进入入口<select value={entranceId} onChange={(event) => { setEntranceId(event.target.value); }}><option value="">请选择入口</option>{context.entrances.map((item) => <option key={item.node_id} value={item.node_id}>{item.label}</option>)}</select></label><label>预计停留（可选）<select value={expectedStayMinutes} onChange={(event) => { setExpectedStayMinutes(event.target.value); }}><option value="">暂不确定</option><option value="30">30分钟</option><option value="60">1小时</option><option value="120">2小时</option><option value="240">4小时</option><option value="480">8小时</option><option value="1440">24小时</option></select><small>仅为你提供的估计，可留空</small></label><button type="button" className={`need-option ${requiresCharging ? "active" : ""}`} aria-pressed={requiresCharging} onClick={() => { setRequiresCharging((value) => !value); }}><span>⚡</span><span><strong>需要充电车位</strong><small>启用后作为后端硬条件，不会静默降级</small></span><i /></button><button className="primary-action wide" disabled={submitting || entranceId === ""} onClick={() => { void run(() => createRecommendation(context, entranceId, requiresCharging, expectedStayMinutes === "" ? null : Number(expectedStayMinutes))); }}>{submitting ? "正在校验并锁位…" : "获取智能推荐"}</button></article><aside className="assurance-card"><span>✓</span><h2>先锁位，后展示</h2><p>页面只有在服务端成功创建 30 秒软锁后，才会显示推荐车位。</p><ul><li>当前会话独立模拟</li><li>充电需求严格过滤</li><li>刷新不会延长期限</li></ul></aside></div>{message === null ? null : <p className="inline-alert">{message}</p>}</section>;
  }

  if (result.journey.state !== "soft_held" || result.recommendation.claim_status !== "soft_held") {
    return <section className="recommend-shell"><div className="recommend-state"><span className="recommend-icon">!</span><h1>本次尝试已结束</h1><p>服务端状态为 {result.journey.state}，请创建新的推荐尝试。</p><button className="primary-action" onClick={() => { setResult(null); }}>重新填写需求</button></div></section>;
  }

  return <section className="recommend-shell"><header className="recommend-heading result-heading"><div><span>已为你锁定主推荐{context.demo_profile === null || context.demo_profile === undefined ? "" : ` · ${context.demo_profile.label}`}</span><h1>{isTandem ? "协同停车位" : "推荐车位"} <b>{primaryId}</b></h1><p>{friendlyReason(result, requiresCharging)}</p></div><div className={`hold-timer ${remaining <= 10 ? "urgent" : ""}`}><small>服务端软锁剩余</small><strong>00:{String(remaining).padStart(2, "0")}</strong><span>刷新不续期</span></div></header><div className="result-grid"><article className="primary-space-card"><div className="space-visual"><span>{primary?.charging === true ? "⚡" : "P"}</span><b>{primaryId}</b><small>{primary?.charging === true ? "充电车位" : "普通停车"}</small></div><div className="space-facts"><span><small>场内距离</small><strong>{Math.round(result.recommendation.route?.distance_m ?? 0)} m</strong></span><span><small>预计到达</small><strong>{Math.ceil(result.recommendation.route?.dynamic_eta_s ?? 0)} 秒</strong></span><span><small>车位状态</small><strong>已软锁</strong></span></div>{isTandem ? <div className="tandem-notice"><b>需要你确认协同停车</b><p>该车位可能需要临时移位；系统已检查当前模拟场景具备恢复条件，但这不是自动驾驶承诺。</p></div> : <div className="standard-notice">当前为独立车位，无纵深协同确认。</div>}<div className="action-row sticky-actions"><button disabled={submitting || remaining === 0} className="primary-action" onClick={() => { void (async () => { setSubmitting(true); try { const journey = await confirmRecommendation(result); if (journey.state === "session_reserved") void navigate("/journey"); else { try { await recover(); } catch (recoveryError) { setMessage(errorMessage(recoveryError)); } } } catch (error) { setMessage(errorMessage(error)); try { await recover(); } catch (recoveryError) { setMessage(errorMessage(recoveryError)); } } finally { setSubmitting(false); } })(); }}>{isTandem ? "接受协同停车并确认" : "确认使用此车位"}</button>{isTandem ? <button disabled={submitting || remaining === 0} className="secondary-action" onClick={() => { void run(() => declineTandem(result)); }}>不接受，重新推荐</button> : null}</div></article><aside className="alternative-card"><span>合规备选</span>{alternativeId === undefined ? <><h2>暂无备选</h2><p>当前没有满足相同硬条件的第二个车位。你可以确认主推荐，或等待后重新发起。</p></> : <><h2>{alternativeId}</h2><p>{alternative?.charging === true ? "同样满足充电需求" : tandemIds.has(alternativeId) ? "同样为可恢复协同位" : "普通独立车位"}，选择时由服务端原子切换软锁。</p><button disabled={submitting || remaining === 0} className="secondary-action wide" onClick={() => { void run(() => selectAlternative(result, alternativeId)); }}>切换到此备选</button></>}<div className="truth-card"><b>关于推荐</b><p>智能推荐只使用当前可用状态；确认前请核对车位类型与需求。</p></div></aside></div>{message === null ? null : <p className="inline-alert">{message}</p>}</section>;
}
