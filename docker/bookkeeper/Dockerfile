FROM yarranyu/mercure-base:latest
EXPOSE 8080
HEALTHCHECK CMD wget -O/dev/null -q http://localhost:8080/test || exit 1
CMD /home/mercure/mercure-env/bin/python /home/mercure/mercure/bookkeeper.py
