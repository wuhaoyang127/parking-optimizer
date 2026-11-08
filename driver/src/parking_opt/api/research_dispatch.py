"""Research ranking behind existing feasibility and atomic Journey claim boundaries."""
import hashlib
from threading import RLock
from time import monotonic
from parking_opt.api.research_runtime import canonical_hash
from parking_opt.api.research_projection import project_observations


class ResearchDispatcher:
    def __init__(self, baseline, routes, runtime, store):
        self.baseline, self.routes = baseline, routes
        self.runtime, self.store = runtime, store
        self._pins = {}
        self._lock = RLock()
        self.observation_provider = None

    def _resolve_release(self, driver):
        pin_key = (driver.session_id, driver.request_id)
        with self._lock:
            if pin_key in self._pins:
                return self._pins[pin_key]
            trial = self.store.trial()
            if trial is not None and self._trial_selected(trial, driver.request_id):
                release = trial
            else:
                release = self.store.active()
            self._pins[pin_key] = release
            return release

    @staticmethod
    def _trial_selected(trial, request_id):
        ratio = trial.get("trial_ratio")
        if ratio is None or ratio >= 1.0:
            return True
        if ratio <= 0.0:
            return False
        digest = int(hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:8], 16)
        return digest < int(ratio * 0xFFFFFFFF)

    def recommend(self, driver, layout, costs, data_source, **kwargs):
        release = self._resolve_release(driver)
        base = self.baseline.recommend(driver, layout, costs, data_source, **kwargs)
        if release is None:
            return base
        started = monotonic()
        payload = self.payload(release, driver, layout, costs, base)
        receipt = {"kind": "execution", "session_id": driver.session_id,
                   "request_id": driver.request_id, "recommendation_id": base.recommendation_id,
                   "parking_lot_id": layout.parking_lot_id,
                   "requested_algorithm": release["algorithm_id"],
                   "requested_version": release["algorithm_version"],
                   "release_id": release["release_id"], "seed": release.get("seed", 0),
                   "release_hash": release["release_hash"], "input_hash": payload["input_hash"],
                   "dispatched_to_trial": release.get("status") == "trial",
                   "trial_ratio": release.get("trial_ratio"),
                   "research_score": release.get("research_score"),
                   "as_of": costs.observed_at.isoformat(), "fallback_reason": None}
        if base.solver_status != "success":
            receipt.update(executed_algorithm="online-rule-v2", status=base.solver_status,
                           fallback_reason="APPLICATION_FEASIBILITY_REJECTED")
            self.store.audit(receipt)
            return base.model_copy(update={"degraded": True,
                "degradation_reason": "研究版本未执行：应用层可行性检查未通过"})
        try:
            snapshot = self.store.observations(driver.session_id, layout.parking_lot_id)
            payload["observations"] = project_observations(payload, snapshot, data_source.mode)
            if snapshot is None and self.observation_provider:
                payload["observations"] = self.observation_provider(driver, layout, costs)
            if payload.get("model") and payload["model"]["source"] != (
                "synthetic" if data_source.mode.value == "synthetic" else "observed"
            ):
                raise ValueError("ML_MODEL_DATA_MODE_MISMATCH")
            payload["input_hash"] = canonical_hash({k: v for k, v in payload.items() if k != "input_hash"})
            receipt["input_hash"] = payload["input_hash"]
            ids = self.runtime.rank(payload, release["source_hash"])
            receipt["solver_evidence"] = getattr(ids, "evidence", {})
            diagnostic = receipt["solver_evidence"]
            warning = ("模型预测缺乏区分度，当前使用模型内置的规则分配"
                       if diagnostic.get("model_degenerate") else
                       "车流波动触发实时兜底，当前使用已配置的兜底策略"
                       if diagnostic.get("rho_mode") == "fallback" else
                       "历史观测不足，当前为冷启动规则分配"
                       if diagnostic.get("cold_start") else None)
            if not ids:
                raise ValueError("RESEARCH_EMPTY_RESULT")
            selected = ids[0]
            spaces = {s.space_id: s for s in layout.spaces}
            route = self.routes.route(layout, costs, from_node_id=driver.entrance_node_id,
                                      to_node_id=spaces[selected].access_node_id)
            tandem = {s for g in layout.tandem_groups for s in g.space_ids_near_to_deep}
            alternatives = [s for s in ids[1:] if selected not in tandem or s not in tandem][:1]
            result = base.model_copy(update={
                "algorithm_id": "research-" + release["algorithm_id"],
                "algorithm_version": release["algorithm_version"],
                "recommended_space_id": selected, "alternative_space_ids": tuple(alternatives),
                "route": route, "explanation_codes": (
                    "APPLICATION_FEASIBILITY_VERIFIED", "RESEARCH_CANDIDATE_RANKING",
                    "RELEASE:" + release["release_hash"], "INPUT:" + payload["input_hash"]),
                "degraded": warning is not None, "degradation_reason": warning,
            })
            receipt.update(executed_algorithm=result.algorithm_id,
                           status="degraded" if warning else "success", fallback_reason=warning)
        except Exception as exc:
            reason = type(exc).__name__ + ":" + str(exc)[:160]
            receipt.update(executed_algorithm="online-rule-v2", status="degraded",
                           fallback_reason=reason)
            result = base.model_copy(update={"degraded": True,
                "degradation_reason": "研究算法执行失败，已回退到在线规则推荐",
                "explanation_codes": (*base.explanation_codes, "RESEARCH_FALLBACK",
                                      "RELEASE:" + release["release_hash"])})
        receipt["elapsed_ms"] = round((monotonic() - started) * 1000, 3)
        self.store.audit(receipt)
        return result

    @staticmethod
    def payload(release, driver, layout, costs, base):
        feasible = {a.space_id: a for a in base.assessments if a.feasible}
        tandem = {s for g in layout.tandem_groups for s in g.space_ids_near_to_deep}
        value = {"contract": "visible-candidates-1.0.0", "algorithm": release["algorithm_id"],
                 "params": release.get("params", {}), "seed": release.get("seed", 0),
                 "model": release.get("model"), "time_s": costs.observed_at.timestamp(),
                 "duration_s": ((driver.expected_departure_at - driver.requested_at).total_seconds()
                                if driver.expected_departure_at else None),
                 "request_id": driver.request_id, "entrance_node_id": driver.entrance_node_id,
                 "driver_input": {"requires_charging": driver.requires_charging,
                     "requested_at": driver.requested_at.isoformat(),
                     "expected_departure_at": (driver.expected_departure_at.isoformat()
                                                if driver.expected_departure_at else None)},
                 "release_hash": release["release_hash"],
                 "layout_hash": canonical_hash(layout.model_dump(mode="json")),
                 "cost_hash": canonical_hash(costs.model_dump(mode="json")),
                 "as_of": costs.observed_at.isoformat(),
                 "spaces": [{"space_id": s.space_id, "group": s.stack_group_id, "depth": s.depth,
                             "tandem": s.space_id in tandem, "status": s.status.value}
                            for s in layout.spaces],
                 "candidates": [{"space_id": s.space_id, "group": s.stack_group_id,
                     "depth": s.depth, "tandem": s.space_id in tandem,
                     "distance_m": feasible[s.space_id].distance_m}
                     for s in layout.spaces if s.space_id in feasible]}
        value["input_hash"] = canonical_hash(value)
        return value
