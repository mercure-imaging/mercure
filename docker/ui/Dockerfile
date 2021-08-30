FROM yarra/mercure-base:latest
EXPOSE 8000
HEALTHCHECK CMD wget -O/dev/null -q http://localhost:8000/ || exit 1
CMD /home/mercure/mercure-env/bin/python /home/mercure/mercure/webgui.py
