FROM postgres:16-alpine
RUN apk add --no-cache rclone tini
COPY backup.sh restore-test.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore-test.sh
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/usr/local/bin/backup.sh", "loop"]
