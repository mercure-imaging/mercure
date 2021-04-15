FROM guruevi/mercure-base:latest
EXPOSE 8080
HEALTHCHECK CMD wget -q http://localhost:8080/test || exit 1
CMD /home/mercure/mercure-env/bin/python /home/mercure/mercure/bookkeeper.py
