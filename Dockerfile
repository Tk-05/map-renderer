FROM nginx:1.27-alpine

COPY server/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY server/map-pending.html /usr/share/nginx/html/map-pending.html

# The map is not part of the image. Mount a host folder or a volume here, e.g.
#   docker run -d -p 8080:80 -v /srv/minecraft-map:/usr/share/nginx/html/map:ro IMAGE
# or set MAP_DIR in server/docker-compose.yml. Without a map a notice is shown.
RUN mkdir -p /usr/share/nginx/html/map

EXPOSE 80
