import { useEffect, useState } from "react";

import {
  importLayout,
  listLayouts,
  loadAdvancedStatus,
  loadCompare,
  type AdvancedStatus,
  type CompareResult,
  type ImportedLayout,
} from "../api/advancedClient";
import type { Account } from "../api/authClient";

const tabs = [
  { id: "algorithms", label: "算法信息" },
  { id: "trial", label: "试用状态" },
  { id: "compare", label: "实验对比" },
  { id: "data", label: "数据与布局" },
] as const;

type TabId = (typeof tabs)[number]["id"];

export function AdvancedPage({ account, onLogout }: { account: Account; onLogout: () => void }) {
  const [tab, setTab] = useState<TabId>("algorithms");
  const [status, setStatus] = useState<AdvancedStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadAdvancedStatus(account.token)
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [account.token]);

  return (
    <div className="advanced-page">
      <header className="advanced-header">
        <div>
          <h2>高级模式</h2>
          <span className="advanced-account">
            {account.username}（{account.role}）
          </span>
        </div>
        <button type="button" onClick={onLogout}>
          退出登录
        </button>
      </header>
      <nav className="advanced-nav" aria-label="高级模式功能">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? "active" : ""}
            aria-current={tab === item.id ? "page" : undefined}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <main className="advanced-body">
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {!error && tab === "algorithms" && <AlgorithmsPanel status={status} />}
        {!error && tab === "trial" && <TrialPanel status={status} />}
        {!error && tab === "compare" && <ComparePanel token={account.token} />}
        {!error && tab === "data" && <DataPanel token={account.token} />}
      </main>
    </div>
  );
}

function AlgorithmsPanel({ status }: { status: AdvancedStatus | null }) {
  if (!status) return <p className="placeholder">加载中…</p>;
  return (
    <section>
      <h3>当前算法</h3>
      {status.active ? (
        <p>
          激活算法：<strong>{status.active.algorithm_id}</strong>（版本 {status.active.algorithm_version}）
        </p>
      ) : (
        <p>当前未启用研究算法，使用默认在线规则推荐。</p>
      )}
      <h3>最近执行回执</h3>
      {status.recent_receipts.length === 0 ? (
        <p>暂无执行回执。</p>
      ) : (
        <ul className="receipt-list">
          {status.recent_receipts.map((receipt, index) => (
            <li key={index}>
              {receipt.requested_algorithm ?? "—"} → {receipt.executed_algorithm ?? "—"}
              {receipt.fallback_reason ? `（${receipt.fallback_reason}）` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TrialPanel({ status }: { status: AdvancedStatus | null }) {
  if (!status) return <p className="placeholder">加载中…</p>;
  const stats = status.trial_stats;
  return (
    <section>
      <h3>试用状态</h3>
      {status.trial ? (
        <p>
          试用中：<strong>{status.trial.algorithm_id}</strong>（比例 {status.trial.trial_ratio}，评分{" "}
          {status.trial.research_score}）
        </p>
      ) : (
        <p>当前无试用中的版本。</p>
      )}
      <p>
        试用回执：{stats.trial_request_count} 次请求，{stats.trial_success_count} 成功，
        {stats.trial_fallback_count} 降级
      </p>
    </section>
  );
}

function DataPanel({ token }: { token: string }) {
  const [json, setJson] = useState("");
  const [layouts, setLayouts] = useState<ImportedLayout[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    try {
      setLayouts(await listLayouts(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  };

  useEffect(() => {
    void refresh();
  }, [token]);

  const handleImport = async () => {
    setError(null);
    setMessage(null);
    try {
      const result = await importLayout(token, json);
      setMessage(`已导入布局 ${result.parking_lot_id}`);
      setJson("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    }
  };

  return (
    <section>
      <h3>布局导入（JSON）</h3>
      <textarea
        className="layout-json-input"
        value={json}
        onChange={(event) => setJson(event.target.value)}
        placeholder="粘贴 Layout 2.0.0 JSON"
        rows={8}
      />
      <div className="advanced-actions">
        <button type="button" onClick={handleImport} disabled={!json.trim()}>
          导入布局
        </button>
      </div>
      {message && <p className="success">{message}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <h3>已导入布局</h3>
      {layouts.length === 0 ? (
        <p>暂无已导入布局。</p>
      ) : (
        <ul className="layout-list">
          {layouts.map((layout) => (
            <li key={layout.parking_lot_id}>
              {layout.parking_lot_id}（版本 {layout.layout_version}，{layout.spaces} 车位）
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ComparePanel({ token }: { token: string }) {
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadCompare(token)
      .then((data) => {
        if (!cancelled) setCompare(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!compare) return <p className="placeholder">加载中…</p>;

  return (
    <section>
      <h3>实验对比</h3>
      {compare.trial ? (
        <p>
          试验算法：<strong>{compare.trial.algorithm_id}</strong>（评分 {compare.trial.research_score}）
          vs 基线 <strong>{compare.baseline_algorithm}</strong>
        </p>
      ) : (
        <p>当前无试验中的算法，无法对比。</p>
      )}
      <table className="compare-table">
        <thead>
          <tr>
            <th>指标</th>
            <th>试验算法</th>
            <th>基线</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>请求数</td>
            <td>{compare.trial_metrics.requests}</td>
            <td>{compare.baseline_metrics.requests}</td>
          </tr>
          <tr>
            <td>成功率</td>
            <td>{percent(compare.trial_metrics.success_rate)}</td>
            <td>{percent(compare.baseline_metrics.success_rate)}</td>
          </tr>
          <tr>
            <td>平均耗时</td>
            <td>{millis(compare.trial_metrics.avg_elapsed_ms)}</td>
            <td>{millis(compare.baseline_metrics.avg_elapsed_ms)}</td>
          </tr>
          <tr>
            <td>降级原因</td>
            <td>{reasons(compare.trial_metrics.fallback_reasons)}</td>
            <td>{reasons(compare.baseline_metrics.fallback_reasons)}</td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

function percent(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function millis(value: number | null): string {
  return value === null ? "—" : `${value} ms`;
}

function reasons(value: Record<string, number>): string {
  const entries = Object.entries(value);
  if (entries.length === 0) return "—";
  return entries.map(([reason, count]) => `${reason}×${count}`).join("、");
}
