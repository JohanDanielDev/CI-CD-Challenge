#!/bin/bash
set -e

mongoimport \
  --db movies_db \
  --collection movies \
  --file /docker-entrypoint-initdb.d/init.json \
  --jsonArray
