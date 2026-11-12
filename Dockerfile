FROM nginx:1.27-alpine

COPY server/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY server/map-pending.html /usr/share/nginx/html/map-pending.html

# The map and the waypoints are not part of the image. Mount host folders, e.g.
#   docker run -d -p 8080:80 \
#     -v /srv/minecraft-map:/usr/share/nginx/html/map:ro \
#     -v /srv/map-markers:/usr/share/nginx/html/markers:ro IMAGE
# or set MAP_DIR / MARKERS_DIR for docker compose. Without a map a notice is shown;
# the markers folder holds markers.json (optional).
RUN mkdir -p /usr/share/nginx/html/map /usr/share/nginx/html/markers

EXPOSE 80
