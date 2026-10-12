FROM mariadb:11.8

# The database service and the one-shot playerbot migrator share this image.
# Keep their configuration, first-start scripts and idempotent migration data
# in the image; the actual database remains exclusively in the db-data volume.
COPY conf.d/99-metin2.cnf /etc/mysql/conf.d/99-metin2.cnf
COPY initdb.d/ /docker-entrypoint-initdb.d/
COPY playerbot/ /opt/playerbot/

RUN chmod 0755 /docker-entrypoint-initdb.d/*.sh /opt/playerbot/apply.sh
