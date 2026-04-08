@echo off
REM Run the object tracking test

echo ======================================================================
echo   Object Tracking Logic Verification Test
echo ======================================================================
echo.

python object_tracking_test.py

echo.
echo Open the generated PNG files to view the plots:
echo   1. object_tracking_comprehensive_analysis.png
echo   2. object_tracking_left_right_steering.png
echo   3. object_tracking_control_linearity.png
echo.
pause