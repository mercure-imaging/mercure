FROM yarra/mercure-base:latest
EXPOSE 8000
HEALTHCHECK CMD wget -q http://localhost:8000/ || exit 1
CMD ls /home/mercure/mercure/webinterface/templates/*.html /home/mercure/mercure/webgui.py /home/mercure/mercure/**/*.py | entr  -r /home/mercure/mercure-env/bin/python /home/mercure/mercure/webgui.py
