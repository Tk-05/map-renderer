# Renderer: downloads a Bedrock Realm world and renders the map into the
# shared map volume, repeating every $INTERVAL (see docker/renderer.sh).
# Build context is tools/. uNmINeD is not part of the image (it may not be
# redistributed); map-renderer downloads it into the cache volume on first run.
FROM node:24-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uNmINeD is a .NET app; run it without ICU instead of installing libicu.
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    MAP_RENDERER_PROJECT=/app \
    PYTHONUNBUFFERED=1

WORKDIR /app/tools

COPY realm_download/package.json realm_download/package-lock.json realm_download/
RUN npm ci --omit=dev --no-audit --no-fund --prefix realm_download

COPY realm_download/realms.js realm_download/
COPY map_renderer map_renderer/
COPY docker/renderer.sh /usr/local/bin/renderer
RUN printf '#!/bin/sh\nexec python3 /app/tools/map_renderer "$@"\n' > /usr/local/bin/map-renderer \
    && chmod +x /usr/local/bin/map-renderer /usr/local/bin/renderer \
    && mkdir -p /app/map /app/.cache

# map/ is shared with the web service; .cache/ holds uNmINeD, the Microsoft
# sign-in tokens, the downloaded world and logs.
VOLUME ["/app/map", "/app/.cache"]
WORKDIR /app

CMD ["renderer"]
