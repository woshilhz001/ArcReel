@echo off
setlocal enabledelayedexpansion

:: ================================================================
::  ArcReel - Docker build & deploy script
::  Usage: double-click to run, or run from command line
::    build.bat                 cache build (default, fastest, for daily code changes)
::    build.bat --full          force full rebuild without cache (first build or dependency change)
::    build.bat --cached        use cache build (compat with old usage, same as default)
::    build.bat --registry name switch download mirror: npmmirror (default) / official
::    build.bat --help          show help
::  NOTE: this file is GBK (ANSI) encoded, the native code page of Chinese
::  Windows cmd. Do NOT convert to UTF-8 and do NOT re-add "chcp 65001":
::  cmd parses the batch with the system code page, so UTF-8 or a later chcp
::  switch breaks multi-byte lines (the classic "not recognized" noise).
:: ================================================================

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "BUILD_LOG=%SCRIPT_DIR%build.log"
set "STEP=0"

:: ---- ensure CWD is the script dir (docker compose needs the yml here) ----
cd /d "%SCRIPT_DIR%" || (
    echo [FAIL] Œﬁ∑®«–ªªµΩΩ≈±æƒø¬º: "%SCRIPT_DIR%"
    exit /b 1
)

:: ---- arg parsing ----
:: default uses docker build cache (only changed layers rebuild, fastest);
:: --full forces --no-cache full rebuild
set "CACHE_FLAG="
set "CACHE_LABEL=[ π”√ª∫¥Ê]"
set "REGISTRY=npmmirror"
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--full" (
    set "CACHE_FLAG=--no-cache"
    set "CACHE_LABEL=[Œﬁª∫¥Ê»´¡ø]"
)
if /i "%~1"=="--cached" (
    set "CACHE_FLAG="
    set "CACHE_LABEL=[ π”√ª∫¥Ê]"
)
if /i "%~1"=="--registry" (
    if "%~2"=="" (
        echo [ERROR] --registry –Ë“™“ª∏ˆ≤Œ ˝£∫npmmirror ªÚ official
        exit /b 1
    )
    set "REGISTRY=%~2"
    shift
)
if /i "%~1"=="--help" (
    echo ArcReel ππΩ®Ω≈±æ
    echo.
    echo ππΩ®.bat [—°œÓ]
    echo.
    echo   --cached              π”√ Docker ππΩ®ª∫¥Ê£®ƒ¨»œ£¨◊ÓøÏ£©
    echo   --full               «ø÷∆Œﬁª∫¥Ê»´¡ø÷ÿΩ®£® ◊¥ŒππΩ®ªÚ“¿¿µ±‰∏¸ ±£©
    echo   --registry name      œ¬‘ÿ‘¥£∫npmmirror£®ƒ¨»œ£¨π˙ƒ⁄øÏ£©/ official£®πŸ∑Ω‘¥£©
    echo   --help               œ‘ æ±æ∞Ô÷˙
    echo.
    exit /b 0
)
shift
goto :parse_args
:args_done

:: one-click switch: npm (frontend) + PyPI (backend) mirrors
if /i "%REGISTRY%"=="official" (
    set "NPM_REGISTRY=https://registry.npmjs.org"
    set "PYPI_INDEX_URL=https://pypi.org/simple"
    set "REGISTRY_LABEL=[πŸ∑Ω‘¥]"
) else (
    set "REGISTRY=npmmirror"
    set "NPM_REGISTRY=https://registry.npmmirror.com"
    set "PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
    set "REGISTRY_LABEL=[π˙ƒ⁄æµœÒ]"
)

:: ---- ANSI color helpers (Windows 10+ supports ANSI) ----
for /f "tokens=2 delims=." %%a in ('ver') do set "VER_MAJOR=%%a"
if !VER_MAJOR! GEQ 10 (
    set "COLOR_INFO=[36m"
    set "COLOR_OK=[32m"
    set "COLOR_WARN=[33m"
    set "COLOR_ERR=[31m"
    set "COLOR_RESET=[0m"
) else (
    set "COLOR_INFO="
    set "COLOR_OK="
    set "COLOR_WARN="
    set "COLOR_ERR="
    set "COLOR_RESET="
)

call :log_info "=============================================================="
call :log_info "  ArcReel ππΩ®≤ø Ω≈±æ"
call :log_info "  π§◊˜ƒø¬º: %CD%"
call :log_info "  œÓƒøƒø¬º: %PROJECT_ROOT%"
call :log_info "  ππΩ®ƒ£ Ω: %CACHE_LABEL%"
call :log_info "  œ¬‘ÿ‘¥: %REGISTRY_LABEL% (%NPM_REGISTRY%)"
call :log_info "  ππΩ®»’÷æ: %BUILD_LOG%"
call :log_info "=============================================================="
echo.

:: ---- preflight ----
call :preflight_check || exit /b %ERRORLEVEL%

:: ---- flow ----
set "START_TIME=%TIME%"

call :run_step "Õ£÷π≤¢…æ≥˝æ…»›∆˜" "docker compose down"
if %ERRORLEVEL% neq 0 (
    call :log_warn "æ…»›∆˜Õ£÷πø…ƒ‹”–æØ∏Ê£¨ºÃ–¯÷¥––..."
)

call :run_step "÷ÿ–¬ππΩ®æµœÒ%CACHE_LABEL%" "docker compose build %CACHE_FLAG% --build-arg NPM_REGISTRY=%NPM_REGISTRY% --build-arg PYPI_INDEX_URL=%PYPI_INDEX_URL%"
if %ERRORLEVEL% neq 0 (
    call :log_err "æµœÒππΩ® ß∞‹£¨÷’÷π≤ø "
    exit /b 1
)

call :run_step "∆Ù∂Ø–¬∞Ê±æ»›∆˜" "docker compose up -d"
if %ERRORLEVEL% neq 0 (
    call :log_err "»›∆˜∆Ù∂Ø ß∞‹£°«ÎºÏ≤È docker compose logs"
    exit /b 1
)

:: wait for container init, then poll health (up to 60s, every 5s)
call :check_health

call :run_step "«Â¿Ì–¸ø’æ…æµœÒ( Õ∑≈¥≈≈Ã)" "docker image prune -f --filter dangling=true"
if %ERRORLEVEL% neq 0 (
    call :log_warn "æµœÒ«Â¿ÌŒ¥ÕÍ»´÷¥––£¨ø… ÷∂Ø÷¥–– docker image prune -f"
)

:: ---- compute duration ----
set "END_TIME=%TIME%"
call :duration "%START_TIME%" "%END_TIME%"

echo.
call :log_ok "=============================================================="
call :log_ok "  ArcReel ππΩ®≤ø ÕÍ≥…£°"
call :log_ok "  ◊‹∫ƒ ±: %DURATION%"
call :log_ok "  ππΩ®»’÷æ: %BUILD_LOG%"
call :log_ok "=============================================================="
echo.
echo  Ã· æ£∫»Áπ˚“≥√Êªπ «æ…∞Ê±æ£¨«Î‘⁄‰Ø¿¿∆˜∞¥ Ctrl+F5 «ø÷∆À¢–¬
echo.
pause
exit /b 0

:: ================================================================
::  subroutines
:: ================================================================

:preflight_check
    set "PASS=1"

    docker info >nul 2>&1
    if errorlevel 1 (
        call :log_err "Docker Œ¥‘À––£¨«Îœ»∆Ù∂Ø Docker Desktop"
        set "PASS=0"
    ) else (
        call :log_ok "  [«∞÷√] Docker ‘À––’˝≥£"
    )

    docker compose version >nul 2>&1
    if errorlevel 1 (
        call :log_err "docker compose √¸¡Ó≤ªø…”√£¨«Î∞≤◊∞ Docker Compose V2"
        set "PASS=0"
    ) else (
        call :log_ok "  [«∞÷√] Docker Compose ø…”√"
    )

    if not exist "%PROJECT_ROOT%\Dockerfile" (
        call :log_err "Dockerfile ≤ª¥Ê‘⁄”⁄ %PROJECT_ROOT%"
        set "PASS=0"
    ) else (
        call :log_ok "  [«∞÷√] Dockerfile ¥Ê‘⁄"
    )

    if not exist "%SCRIPT_DIR%docker-compose.yml" (
        call :log_err "docker-compose.yml ≤ª¥Ê‘⁄”⁄ %SCRIPT_DIR%"
        set "PASS=0"
    ) else (
        call :log_ok "  [«∞÷√] docker-compose.yml ¥Ê‘⁄"
    )

    if !PASS! equ 0 (
        call :log_err "«∞÷√ºÏ≤ÈŒ¥Õ®π˝£¨÷’÷π≤ø "
        exit /b 1
    )
    exit /b 0


:run_step
    set /a STEP+=1
    set "STEP_NAME=%~1"
    :: %~2 = whole command (keep it in quotes when calling), avoids truncation on spaces
    set "STEP_CMD=%~2"
    echo.
    call :log_info "[%STEP%/4] %STEP_NAME% ..."
    >> "%BUILD_LOG%" echo [!DATE! !TIME!] ====== %STEP_NAME% ======
    >> "%BUILD_LOG%" echo [!DATE! !TIME!] $ %STEP_CMD%
    :: run the command (realtime output to terminal so build progress is visible)
    %STEP_CMD%
    set "STEP_EXIT=%ERRORLEVEL%"
    if !STEP_EXIT! equ 0 (
        call :log_ok "  °Ã ÕÍ≥…"
    ) else (
        call :log_err "  °¡  ß∞‹ (ÕÀ≥ˆ¬Î: !STEP_EXIT!)"
    )
    >> "%BUILD_LOG%" echo [!DATE! !TIME!] ÕÀ≥ˆ¬Î: !STEP_EXIT!
    exit /b !STEP_EXIT!


:check_health
    call :log_info "’˝‘⁄ºÏ≤È»›∆˜Ω°øµ◊¥Ã¨£®◊Ó≥§µ»¥˝ 60 √Î£©..."
    for /l %%t in (1,1,12) do (
        for /f "tokens=*" %%i in ('docker compose ps --format "{{.Status}}" 2^>nul') do (
            echo %%i | findstr /i "unhealthy" >nul
            if !errorlevel! equ 0 (
                call :log_err "  »›∆˜◊¥Ã¨: %%i"
                call :log_err "  Ω°øµºÏ≤È ß∞‹£¨«Î÷¥–– docker compose logs ≤Èø¥œÍ«È"
                exit /b 1
            )
            echo %%i | findstr /i "healthy" >nul
            if !errorlevel! equ 0 (
                call :log_ok "  °Ã »›∆˜Ω°øµ"
                exit /b 0
            )
        )
        if %%t lss 12 (
            call :log_info "  …–Œ¥æÕ–˜(µ⁄ %%t ¥Œ)£¨5 √Î∫Û÷ÿ ‘..."
            ping -n 6 127.0.0.1 >nul
        )
    )
    call :log_warn "  60 √Îƒ⁄Œ¥ºÏ≤‚µΩΩ°øµ◊¥Ã¨£¨ø…‘⁄»›∆˜∆Ù∂Ø∫Û ÷∂ØºÏ≤È: docker compose ps"
    exit /b 0


:duration
    set "START=%~1"
    set "END=%~2"
    for /f "tokens=1-4 delims=:.," %%a in ("%START%") do (
        set /a "S_H=100%%a %% 100, S_M=100%%b %% 100, S_S=100%%c %% 100, S_CS=100%%d %% 100"
    )
    for /f "tokens=1-4 delims=:.," %%a in ("%END%") do (
        set /a "E_H=100%%a %% 100, E_M=100%%b %% 100, E_S=100%%c %% 100, E_CS=100%%d %% 100"
    )
    set /a "DIFF_CS = ((E_H*360000 + E_M*6000 + E_S*100 + E_CS) - (S_H*360000 + S_M*6000 + S_S*100 + S_CS))"
    if !DIFF_CS! lss 0 set /a DIFF_CS += 8640000
    set /a "D_H=DIFF_CS/360000, D_R=DIFF_CS%%360000"
    set /a "D_M=D_R/6000, D_R=D_R%%6000"
    set /a "D_S=D_R/100, D_CS=D_R%%100"
    set "DURATION="
    if !D_H! gtr 0 set "DURATION=!D_H! ±"
    if !D_M! gtr 0 set "DURATION=!DURATION!!D_M!∑÷"
    set "DURATION=!DURATION!!D_S!√Î"
    goto :eof


:: ---- log helpers ----
:log_info
    echo %COLOR_INFO%[INFO] %*%COLOR_RESET%
    goto :eof

:log_ok
    echo %COLOR_OK%[ OK ] %*%COLOR_RESET%
    goto :eof

:log_warn
    echo %COLOR_WARN%[WARN] %*%COLOR_RESET%
    goto :eof

:log_err
    echo %COLOR_ERR%[FAIL] %*%COLOR_RESET%
    goto :eof
