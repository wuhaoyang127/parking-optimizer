import { useState } from "react";

export function LoginDialog({
  onLogin,
  onClose,
  error,
}: {
  onLogin: (username: string, password: string) => void;
  onClose: () => void;
  error: string | null;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  return (
    <div className="login-dialog" role="dialog" aria-label="登录高级模式">
      <h2>登录高级模式</h2>
      <p className="hint">使用研究端账号登录</p>
      <label>
        用户名
        <input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
        />
      </label>
      <label>
        密码
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
        />
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="button" onClick={onClose}>
          取消
        </button>
        <button type="button" onClick={() => onLogin(username, password)} disabled={!username || !password}>
          登录
        </button>
      </div>
    </div>
  );
}
