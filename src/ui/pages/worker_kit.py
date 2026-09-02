"""worker 启动脚本与操作员 zip 包生成工具。"""
import base64

from ui.common import *


def _worker_bat(kind: str) -> str:
    """生成本机 worker 启动脚本（公网网页下载后放到项目根目录双击运行）。"""
    if kind == "install_autostart":
        return (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "title 停车场 App 本机计算 worker（开机自启安装）\r\n"
            "cd /d %~dp0\r\n"
            "echo 正在注册 Windows 登录自启任务 ParkingOptLocalWorker ...\r\n"
            "schtasks /Create /F /TN \"ParkingOptLocalWorker\" /SC ONLOGON /RL LIMITED "
            "/TR \"cmd /c cd /d %~dp0 && py local_worker.py --poll 1\"\r\n"
            "if errorlevel 1 (echo 安装失败，请右键以管理员身份运行本脚本 & pause & exit /b 1)\r\n"
            "echo 安装成功，立即启动一次 worker ...\r\n"
            "schtasks /Run /TN \"ParkingOptLocalWorker\"\r\n"
            "echo 完成。以后每次登录 Windows 都会自动在后台运行 worker，无需再手动打开。\r\n"
            "pause\r\n"
        )
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "title 停车场 App 本机计算 worker\r\n"
        "cd /d %~dp0\r\n"
        "echo 正在启动本机计算 worker（保持本窗口开启，用完可关闭）...\r\n"
        "py local_worker.py --poll 1\r\n"
        "pause\r\n"
    )


# 操作员本地计算包（zip）内嵌文件内容：精简依赖 + 双击启动脚本
WORKER_REQUIREMENTS_TXT = (
    "# 停车场 App 本机计算 worker 精简依赖（无需 Streamlit/Pandas/Plotly）\n"
    "supabase>=2.0.0\n"
    "httpx>=0.27.0\n"
    "networkx>=3.0\n"
    "simpy>=4.0\n"
    "ortools>=9.7\n"
)


def _worker_operator_bat() -> str:
    """操作员包内的启动脚本：检测 Python → 首次安装精简依赖 → 启动 worker。

    依赖安装优先走清华 PyPI 镜像（国内直连，无需 VPN，比官方源更稳），
    失败后回退官方源（适合有稳定外网/代理的环境）。
    """
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "title 停车场 App 本机计算 worker（操作员）\r\n"
        "cd /d %~dp0\r\n"
        "where py >nul 2>nul\r\n"
        "if errorlevel 1 (\r\n"
        "  echo [错误] 未检测到 Python。请先到 https://www.python.org/downloads/ 安装，\r\n"
        "  echo        安装时务必勾选 \"Add python.exe to PATH\"。\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "if not exist \".deps_installed\" (\r\n"
        "  echo 首次运行：正在安装精简依赖（supabase/networkx/simpy/ortools）...\r\n"
        "  py --version\r\n"
        "  py -c \"import struct; print('Python 位数：64 位' if struct.calcsize('P')==8 else 'Python 位数：32 位（ortools 不支持 32 位，请到 python.org 重装 64 位 Python）')\"\r\n"
        "  echo 优先使用清华 PyPI 镜像（国内直连更快，不需要 VPN）...\r\n"
        "  py -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60 --retries 5\r\n"
        "  py -m pip install -r requirements_worker.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60 --retries 5\r\n"
        "  if errorlevel 1 (\r\n"
        "    echo [提示] 镜像源失败，改用官方源重试（需要稳定外网；若开 VPN，请确认 VPN 为全局/TUN 模式，pip 不走浏览器代理）...\r\n"
        "    py -m pip install -r requirements_worker.txt --timeout 60 --retries 5\r\n"
        "    if errorlevel 1 (\r\n"
        "      echo [错误] 依赖安装失败。常见原因：① 32 位 Python（上方会提示，请重装 64 位）；② 网络问题，请换网络后重试；③ 公司网络限制，请用手机热点试试。\r\n"
        "      echo 请把本窗口从「Python 位数」开始的全部内容截图/复制发管理员。\r\n"
        "      pause\r\n"
        "      exit /b 1\r\n"
        "    )\r\n"
        "  )\r\n"
        "  echo ok> .deps_installed\r\n"
        ")\r\n"
        "echo 正在启动本机计算 worker（保持本窗口开启，用完可关闭）...\r\n"
        "py local_worker.py --poll 1\r\n"
        "pause\r\n"
    )


def _worker_package_bytes(supabase_url: str = "", supabase_anon_key: str = "") -> bytes:
    """生成「操作员本地计算包」zip：worker 代码 + 核心算法包 + 精简依赖 + 启动脚本 + 配置。

    supabase_url / supabase_anon_key 缺省时从 auth 模块（st.secrets/环境变量）读取。
    """
    import io
    import zipfile
    import auth as auth_mod

    sb_url = supabase_url or auth_mod.SUPABASE_URL
    sb_key = supabase_anon_key or auth_mod.SUPABASE_ANON_KEY
    if not sb_url or not sb_key:
        raise RuntimeError("Supabase 未配置，无法生成操作员本地计算包")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("local_worker.py",
                    (PROJECT_ROOT / "local_worker.py").read_text(encoding="utf-8"))
        zf.writestr("worker_net.py",
                    (PROJECT_ROOT / "worker_net.py").read_text(encoding="utf-8"))
        zf.writestr("worker_compute.py",
                    (PROJECT_ROOT / "worker_compute.py").read_text(encoding="utf-8"))
        lc_pkg = PROJECT_ROOT / "src" / "local_compute"
        for p in sorted(lc_pkg.rglob("*.py")):
            arc = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            zf.writestr(arc, p.read_text(encoding="utf-8"))
        pkg = PROJECT_ROOT / "src" / "parking_opt"
        for p in sorted(pkg.rglob("*.py")):
            arc = str(p.relative_to(PROJECT_ROOT)).replace("\\", "/")
            zf.writestr(arc, p.read_text(encoding="utf-8"))
        zf.writestr("requirements_worker.txt", WORKER_REQUIREMENTS_TXT)
        zf.writestr("start_local_worker.bat", _worker_operator_bat())
        zf.writestr("worker_config.toml",
                    f'SUPABASE_URL = "{sb_url}"\nSUPABASE_ANON_KEY = "{sb_key}"\n')
    return buf.getvalue()


# 操作员 zip 包版本号：包内容（启动脚本/依赖清单）变更时 +1，避免 st.cache_data 命中旧包
_WORKER_PACKAGE_VERSION = "4"


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_worker_package_bytes(sb_url: str, sb_key: str, pkg_version: str) -> bytes:
    """缓存操作员 zip 字节（同一小时内不重复读取/压缩 28 个核心文件）。"""
    return _worker_package_bytes(sb_url, sb_key)


def _worker_package_data_url() -> str:
    """操作员 zip 的 data URL：浏览器本地直接下载，不依赖 WebSocket 服务器连接。

    修复公网 app 报错「Error: not connected to a server!」：
    st.download_button 传 bytes 时前端点击要向服务器要下载地址，WebSocket
    一断就报该错；换成 data URL 后点击由浏览器直接处理。
    """
    import auth as auth_mod
    data = _cached_worker_package_bytes(
        auth_mod.SUPABASE_URL or "", auth_mod.SUPABASE_ANON_KEY or "",
        _WORKER_PACKAGE_VERSION)
    return "data:application/zip;base64," + base64.b64encode(data).decode("ascii")


def _resolve_delete_task_id(session_task_id, latest_any_res):
    """解析「删除该任务」按钮要删的任务 ID。

    优先用本会话下发的 task_id；session 丢失（刷新/重开浏览器）时，
    从 get_latest_compute_task_any 的结果里取最近一条任务（任意状态）。
    返回 (task_id, task_status, source)；无任务可删时 (None, None, None)。
    """
    if session_task_id:
        return session_task_id, None, "本会话任务"
    task = (latest_any_res or {}).get("task")
    if isinstance(task, dict) and task.get("id"):
        return task.get("id"), task.get("status"), "最近一条任务（刷新后自动定位）"
    return None, None, None
