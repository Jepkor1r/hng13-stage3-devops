#!/usr/bin/env sh
set -e

# Render template to default conf if present
# Expects /etc/nginx/conf.template to exist and environment variables:
# ACTIVE_POOL and APP_PORT
if [ -f /etc/nginx/conf.template ]; then
  # Use envsubst to render variables in the template
  envsubst '${ACTIVE_POOL} ${APP_PORT}' < /etc/nginx/conf.template > /etc/nginx/conf.d/default.conf
fi

# Start nginx in foreground
exec nginx -g "daemon off;"
