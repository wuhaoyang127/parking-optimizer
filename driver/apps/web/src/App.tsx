import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { login, type Account } from "./api/authClient";
import { LoginDialog } from "./auth/LoginDialog";
import { AdvancedPage } from "./advanced/AdvancedPage";
import { ParkingDiscoveryPage } from "./parking/ParkingDiscoveryPage";
import { FacilityLayoutPage } from "./parking/FacilityLayoutPage";
import { JourneyPage } from "./parking/JourneyPage";
import { RecommendationPage } from "./parking/RecommendationPage";

const navigation = [
  { to: "/parking", label: "找停车场", icon: "⌖" },
  { to: "/recommend", label: "智能停车", icon: "◇" },
  { to: "/journey", label: "当前行程", icon: "↗" },
] as const;

export function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  const handleLogin = async (username: string, password: string) => {
    setLoginError(null);
    try {
      setAccount(await login(username, password));
      setShowLogin(false);
    } catch (error) {
      setLoginError(error instanceof Error ? error.message : "登录失败");
    }
  };

  const handleLogout = () => {
    setAccount(null);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="brand" to="/parking" aria-label="智能停车首页">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span className="brand-copy">
            <strong>智能停车</strong>
            <small>优化与调度系统</small>
          </span>
        </NavLink>
        <span className="mode-badge">
          <i />
          {account ? "高级模式" : "车主模式"}
        </span>
        <div className="topbar-tools">
          <span className="data-badge">数据来源已标注</span>
          <a
            href={import.meta.env.VITE_RESEARCH_APP_URL || "http://127.0.0.1:8501"}
            target="_blank"
            rel="noreferrer"
            className="research-link"
          >
            研究端 ↗
          </a>
          {account ? (
            <button type="button" className="login-link" onClick={handleLogout}>
              退出登录
            </button>
          ) : (
            <button
              type="button"
              className="login-link"
              onClick={() => {
                setShowLogin(true);
                setLoginError(null);
              }}
            >
              登录
            </button>
          )}
        </div>
      </header>

      {account ? (
        <AdvancedPage account={account} onLogout={handleLogout} />
      ) : (
        <>
          <aside className="truth-banner" role="note">
            <span aria-hidden="true" />
            演示环境默认使用 Synthetic · 实际来源以页面标签为准 · 场内管理指引不等于实车导航
          </aside>

          <nav className="primary-nav" aria-label="车主功能">
            {navigation.map((item) => (
              <NavLink key={item.to} to={item.to}>
                <span aria-hidden="true">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <main>
            <Routes>
              <Route path="/" element={<Navigate to="/parking" replace />} />
              <Route path="/parking" element={<ParkingDiscoveryPage />} />
              <Route path="/parking/:parkingLotId" element={<ParkingDiscoveryPage />} />
              <Route path="/parking/:parkingLotId/layout" element={<FacilityLayoutPage />} />
              <Route path="/recommend" element={<RecommendationPage />} />
              <Route path="/journey" element={<JourneyPage />} />
              <Route path="*" element={<Navigate to="/parking" replace />} />
            </Routes>
          </main>
        </>
      )}

      {showLogin && (
        <LoginDialog onLogin={handleLogin} onClose={() => setShowLogin(false)} error={loginError} />
      )}
    </div>
  );
}
