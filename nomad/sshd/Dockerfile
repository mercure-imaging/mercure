FROM alpine:edge
MAINTAINER Daniel Guerra <daniel.guerra69@gmail.com>

# add openssh and clean
RUN apk add --update openssh openssl \
&& rm  -rf /tmp/* /var/cache/apk/*
# add entrypoint script
ADD docker-entrypoint.sh /usr/local/bin
ADD sshd_config /etc/ssh/sshd_config
#make sure we get fresh keys

RUN rm -rf /etc/ssh/ssh_host_rsa_key /etc/ssh/ssh_host_dsa_key
RUN echo -e 'asdkjflaskdfjlkasdfj\nasdkjflaskdfjlkasdfj' | passwd root

EXPOSE 22
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["/usr/sbin/sshd","-D"]
