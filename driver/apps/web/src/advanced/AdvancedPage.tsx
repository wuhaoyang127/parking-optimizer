import { useState } from "react";

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
        {tab === "algorithms" && <p className="placeholder">算法信息（待实现）</p>}
        {tab === "trial" && <p className="placeholder">试用状态（待实现）</p>}
        {tab === "compare" && <p className="placeholder">实验对比（待实现）</p>}
        {tab === "data" && <p className="placeholder">数据与布局（待实现）</p>}
      </main>
    </div>
  );
}
