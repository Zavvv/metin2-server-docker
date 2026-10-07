FROM mariadb:11.8

RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip \
 && rm -rf /var/lib/apt/lists/*

COPY db-backup.zip /opt/restore/db-backup.zip
COPY restore.sh /usr/local/bin/restore-database

RUN chmod 0755 /usr/local/bin/restore-database

ENTRYPOINT ["/usr/local/bin/restore-database"]
