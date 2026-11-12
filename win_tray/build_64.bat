@echo off
rem ============================================================
rem  打包 64 位 标签打印助手（单文件 exe，后台 + 托盘）
rem  使用项目内的干净构建虚拟环境 .venv-build
rem ============================================================
setlocal
cd /d "%~dp0.."

set VENV_PY=%~dp0..\.venv-build\Scripts\python.exe
if not exist "%VENV_PY%" (
    echo [ERROR] 未找到构建虚拟环境: %VENV_PY%
    echo        请先创建并安装依赖:
    echo        python -m venv .venv-build
    echo        .venv-build\Scripts\python -m pip install -r win_tray\requirements-win.txt
    exit /b 1
)

"%VENV_PY%" win_tray\build.py --arch x64
if errorlevel 1 (
    echo [ERROR] 64 位打包失败
    exit /b 1
)
echo.
echo [OK] 64 位打包完成: dist\LabelPrintAssistant-x64.exe
pause
