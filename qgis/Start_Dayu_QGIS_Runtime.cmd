@echo off
call Q:\bin\o4w_env.bat
if not exist "%OSGEO4W_ROOT%\apps\qgis-ltr\bin\qgisgrass8.dll" goto nograss
if not exist "%OSGEO4W_ROOT%\apps\grass\grass85\etc\env.bat" goto nograss
set "savedpath=%PATH%"
call "%OSGEO4W_ROOT%\apps\grass\grass85\etc\env.bat"
path %OSGEO4W_ROOT%\apps\grass\grass85\lib;%OSGEO4W_ROOT%\apps\grass\grass85\bin;%savedpath%
:nograss
path %OSGEO4W_ROOT%\apps\qgis-ltr\bin;%PATH%
set "QGIS_PREFIX_PATH=%OSGEO4W_ROOT:\=/%/apps/qgis-ltr"
set "GDAL_FILENAME_IS_UTF8=YES"
set "VSI_CACHE=TRUE"
set "VSI_CACHE_SIZE=1000000"
set "QT_PLUGIN_PATH=%OSGEO4W_ROOT%\apps\qgis-ltr\qtplugins;%OSGEO4W_ROOT%\apps\qt5\plugins"
start "QGIS" /wait "%OSGEO4W_ROOT%\bin\qgis-ltr-bin.exe" %*
exit /b %ERRORLEVEL%
