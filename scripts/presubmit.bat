@echo off
REM Windows shim — delegates to the bash script via Git Bash.
REM Requires Git for Windows (bash + git on PATH).
bash "%~dp0presubmit.sh" %*
