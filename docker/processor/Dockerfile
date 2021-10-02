FROM mercure-local/mercure-base:latest
VOLUME ["/var/run/docker.sock"]
# ls /home/mercure/mercure/processor.py /home/mercure/mercure/**/*.py | entr -r
CMD /home/mercure/mercure-env/bin/python -u /home/mercure/mercure/processor.py
