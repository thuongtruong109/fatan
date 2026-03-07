@echo off
echo Installing dependencies...

mkdir C:\android-tools
cd C:\android-tools

curl -L -o platform-tools.zip https://dl.google.com/android/repository/platform-tools-latest-windows.zip
tar -xf platform-tools.zip

curl -L -o scrcpy.zip https://github.com/Genymobile/scrcpy/releases/download/v3.3.4/scrcpy-win64-v3.3.4.zip
tar -xf scrcpy.zip

for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v PATH 2^>nul') do set "SYS_PATH=%%B"
setx PATH "%SYS_PATH%;C:\android-tools\platform-tools;C:\android-tools\scrcpy-win64-v3.3.4" /M

echo DONE. Restart CMD or PC.
pause
