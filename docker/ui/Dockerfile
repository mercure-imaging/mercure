FROM mercureimaging/mercure-base:latest
EXPOSE 8000
HEALTHCHECK CMD wget -O/dev/null -q http://localhost:8000/ || exit 1
CMD /opt/mercure/env/bin/python /opt/mercure/app/webgui.py
