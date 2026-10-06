FROM mariadb:11.8

# Portainer cannot deploy bind mounts for non-administrator users. Package the
# immutable database configuration and first-run seed data in this image.
COPY conf.d/ /etc/mysql/conf.d/
COPY initdb.d/ /docker-entrypoint-initdb.d/
COPY playerbot/ /opt/playerbot/
