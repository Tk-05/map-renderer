#!/bin/sh
# Renderer loop: download the Realm world, render the map and scan for
# structures, then wait $INTERVAL and repeat. A failed run is retried after
# the interval; the previous map stays online in the meantime.
#
#   REALM          Realm name or id (required)
#   REALM_SLOT     world slot 1-3 (default: the active one)
#   INTERVAL       pause between runs, e.g. 30m, 6h, 1d (default: 6h)
#   BUILD_ARGS     extra map-renderer build options, e.g. "--dims overworld --extras"
#   REALMS_CLIENT_VERSION  Bedrock version sent to the Realms API, if it asks for a newer client
set -u

if [ -z "${REALM:-}" ]; then
    echo "REALM is not set. Set it to the Realm name or id (list them with: map-renderer realm list)." >&2
    exit 64
fi
INTERVAL=${INTERVAL:-6h}

while true; do
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') updating map from Realm \"$REALM\""
    # BUILD_ARGS is split on spaces on purpose.
    # shellcheck disable=SC2086
    if map-renderer build --realm "$REALM" ${REALM_SLOT:+--slot "$REALM_SLOT"} -y ${BUILD_ARGS:-}; then
        echo "=== done, next run in $INTERVAL"
    else
        echo "=== run failed (exit $?), retrying in $INTERVAL" >&2
    fi
    sleep "$INTERVAL"
done
