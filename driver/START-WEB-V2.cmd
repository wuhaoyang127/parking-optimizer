@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment. Read START-HERE.md and restore uv.lock first.
  pause
  popd
  exit /b 1
)
if not exist "apps\web\node_modules\vite\bin\vite.js" (
  echo Missing web dependencies. Run npm --prefix apps/web ci first.
  pause
  popd
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo Node 24 and npm 11 are required. Read START-HERE.md.
  pause
  popd
  exit /b 1
)
node -e "const cp=require('node:child_process');const v=process.versions.node.split('.').map(Number);const n=cp.execSync('npm --version',{encoding:'utf8',windowsHide:true}).trim();process.exit(v[0]===24&&v[1]>=15&&n.split('.')[0]==='11'?0:1)"
if errorlevel 1 (
  echo Unsupported versions. Require Node 24.15 or newer in major 24, and npm major 11.
  pause
  popd
  exit /b 1
)
call npm --prefix apps/web run demo
set "taskExit=%errorlevel%"
popd
exit /b %taskExit%
