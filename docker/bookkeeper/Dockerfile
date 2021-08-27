FROM yarra/mercure-base:latest
EXPOSE 8080
HEALTHCHECK CMD wget -q http://localhost:8080/test || exit 1
CMD ls /home/mercure/mercure/bookkeeper.py /home/mercure/mercure/**/*.py | entr -r /home/mercure/mercure-env/bin/python /home/mercure/mercure/bookkeeper.py
