@echo off
set NODE_OPTIONS=--openssl-legacy-provider
cd /d E:\TDYW\spug-3.0\spug_web
npm run build
echo Build completed
docker exec spug rm -rf /data/spug/spug_web/build
docker cp E:\TDYW\spug-3.0\spug_web\build spug:/data/spug/spug_web/build
echo Files copied to container
docker exec spug supervisorctl restart nginx
echo Nginx restarted
pause
