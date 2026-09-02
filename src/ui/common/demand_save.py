"""需求序列保存/下载/列表工具。"""
from ui.common._imports import *
from ui.common.constants import PROJECT_ROOT, DEMAND_EXPORT_DIR


def save_demand_to_project(vehicles, seed=None, source="generated",
                           generator_params=None, generated_at=None,
                           prefix="demand") -> Path:
    """一键保存到项目 data/demand_exports/（自动时间戳命名防覆盖），返回保存路径。"""
    DEMAND_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = DEMAND_EXPORT_DIR / f"{prefix}_{source}_{stamp}.json"
    text = export_demand_json(vehicles, seed=seed, source=source,
                              generator_params=generator_params,
                              generated_at=generated_at)
    path.write_text(text, encoding="utf-8")
    return path


def save_demand_to_path(vehicles, path, seed=None, source="generated",
                        generator_params=None, generated_at=None) -> Path:
    """把需求序列写到用户指定路径（父目录不存在则创建），返回实际保存路径。"""
    target = Path(path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = export_demand_json(vehicles, seed=seed, source=source,
                              generator_params=generator_params,
                              generated_at=generated_at)
    target.write_text(text, encoding="utf-8")
    return target


def is_local_desktop() -> bool:
    """是否本地桌面运行（Windows）。「下载到项目文件夹」等服务器端写文件功能仅本地有意义。"""
    return os.name == "nt"


def render_save_as_button(json_str: str, default_name: str):
    """渲染一个浏览器端「另存为…」按钮（File System Access API）。

    Chrome/Edge 且处于安全上下文（https 或 localhost）时，点击弹出系统保存对话框，
    由访问者自选保存位置，直接写入访问者电脑（类似 Word 另存为）；
    浏览器不支持或非安全上下文时，自动降级为普通浏览器下载。
    """
    import base64
    b64 = base64.b64encode(json_str.encode("utf-8")).decode("ascii")
    name_js = json.dumps(default_name)
    html = f"""
<div style="margin:2px 0;">
  <button id="saveas-btn" type="button" style="
      width:100%; padding:0.5rem 0.9rem; border:1px solid #d1d5db; border-radius:8px;
      background:#fff; color:#1e293b; font-size:0.95rem; font-weight:600; cursor:pointer;">
    💾 另存为…（自选保存位置）
  </button>
  <div id="saveas-msg" style="font-size:0.82rem; color:#64748b; margin-top:4px;"></div>
</div>
<script>
(function() {{
  const btn = document.getElementById('saveas-btn');
  const msg = document.getElementById('saveas-msg');
  const b64 = "{b64}";
  const filename = {name_js};
  function blob() {{
    return new Blob([Uint8Array.from(atob(b64), c => c.charCodeAt(0))],
                    {{type: 'application/json'}});
  }}
  function fallbackDownload() {{
    const url = URL.createObjectURL(blob());
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
    msg.textContent = '已开始浏览器下载（当前环境不支持另存为对话框）';
    msg.style.color = '#64748b';
  }}
  btn.addEventListener('click', async () => {{
    if (window.showSaveFilePicker) {{
      try {{
        const handle = await window.showSaveFilePicker({{
          suggestedName: filename,
          types: [{{description: 'JSON 文件',
                    accept: {{'application/json': ['.json']}}}}],
        }});
        const writable = await handle.createWritable();
        await writable.write(blob());
        await writable.close();
        msg.textContent = '✅ 已保存到你的电脑：' + handle.name;
        msg.style.color = '#16a34a';
      }} catch (e) {{
        if (e && e.name === 'AbortError') {{
          msg.textContent = '已取消保存';
          msg.style.color = '#64748b';
        }} else {{
          fallbackDownload();
        }}
      }}
    }} else {{
      fallbackDownload();
    }}
  }});
}})();
</script>
"""
    st.components.v1.html(html, height=86)


def list_demand_files() -> list[tuple[Path, str]]:
    """列出项目 data/demand_exports/ 下的需求序列 JSON，返回 [(路径, 显示名)]，按修改时间倒序。"""
    if not DEMAND_EXPORT_DIR.exists():
        return []
    files = sorted(DEMAND_EXPORT_DIR.glob("*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [(p, f"{p.name}（{time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}）")
            for p in files]
