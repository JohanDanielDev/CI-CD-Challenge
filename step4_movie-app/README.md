# Containerized Movie Explorer

The explorer is a lightweight, decoupled microservices application designed for isolated container execution across a shared Docker bridge network (`movie-net`). It enables users to browse and filter a database of 36 movies by genre (Drama, Comedy, Thriller), with an optional local AI movie guide that accepts mood and viewing preferences.

## Architecture Components

**Frontend (movie-ui):** A lightweight Nginx web server hosting the plain HTML/JavaScript interface.

**Reverse proxy (nginx-proxy):** A second Nginx service publishes port `8181`, routes `/` to
`movie-ui`, and routes `/api/` to `movie-api`. The frontend uses a same-origin API URL.

**Backend API (movie-api):** A Python Flask REST API that handles requests on container port 5000,
queries MongoDB over the internal container network, and excludes `_id` from its JSON responses.

**Database (movie-db):** A MongoDB 6.0 instance pre-seeded with 36 movie documents using mongoimport. Each movie includes its category, year, and themes to help personalize AI suggestions. It persists data inside the movies_db database on standard port 27017.

| Service | Container Name | Technology | Internal Port | Host Port | Primary Function |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Reverse proxy** | `nginx-proxy` | Nginx | `80` | `8181` | Routes UI and API requests |
| **Frontend** | `movie-ui` | Nginx / HTML / JS | `80` | Internal only | Serves the UI to the reverse proxy |
| **Backend** | `movie-api` | Python 3.10 / Flask | `5000` | Internal only | Processes API requests and queries MongoDB |
| **Database** | `movie-db` | MongoDB 6.0 | `27017` | Internal only | Stores movie documents in `movies_db` |
| **AI guide** | `ollama` | Ollama / Gemma 3 1B | `11434` | Internal only | Suggests movies from the selected category (optional `ai` profile) |
| **Code analysis** | `sonarqube` | SonarQube Community | `9000` | `9000` | Analyzes code (enabled separately) |

## Run the movie stack with Docker Compose

From `step4_movie-app`, start the reverse proxy, frontend, API, and seeded MongoDB database:

```bash
docker compose up --build -d
```

Open the app at [http://localhost:8181](http://localhost:8181). The API is available through
the reverse proxy at [http://localhost:8181/api/movies](http://localhost:8181/api/movies).
MongoDB and the backend are only reachable inside the `movie-net` bridge network. To stop the
stack while keeping persisted data, run:

```bash
docker compose down
```

The MongoDB seed script runs only when the database volume is first created. To safely add the
new catalog to an existing database without deleting its volume or duplicating movies, run:

```bash
docker compose exec movie-db mongoimport \
  --db movies_db \
  --collection movies \
  --file /docker-entrypoint-initdb.d/init.json \
  --jsonArray \
  --mode=upsert \
  --upsertFields=title
```

The upsert uses each movie title as the matching key, so existing titles are updated and new
titles are inserted.

The SonarQube and test services are available separately under the `analysis` profile; see
the analysis instructions below.

## Start the local Gemma movie guide

The AI guide runs in its own Ollama container and is not started with the regular app stack.
From `step4_movie-app`, start it and download the lightweight Gemma 3 1B model:

```bash
docker compose --profile ai up -d ollama
docker compose exec ollama ollama pull gemma3:1b
```

Open [http://localhost:8181](http://localhost:8181), enter a mood or request (for example,
“something clever and uplifting”), choose a category, and select **Ask Gemma**. The API sends
matching movie titles, years, categories, and themes to Gemma, constrains its response to catalog
titles, validates each pick, and avoids repeating prior picks until the collection has cycled
through. Ollama is reachable only inside the Compose network; no model API port is published on
the host.
The first model download requires an internet connection and several hundred MB of disk space.
To stop the AI container while keeping its downloaded model:

```bash
docker compose --profile ai stop ollama
```

If the AI service is not started, browsing and filtering movies still works; the suggestion
button displays an actionable error.

```text
Browser :8181 -> nginx-proxy -> movie-ui (Nginx static frontend)
                        |-----> movie-api:5000 -> movie-db:27017
                                           |----> ollama:11434 (optional AI profile)

All containers share the movie-net bridge; only nginx-proxy and SonarQube publish host ports.
```

## Step 1: Create the Isolated Bridge Network

Compose creates the `movie-net` bridge network automatically. The following command is only
needed when running the containers manually:

```
docker network create movie-net
```

## Step 2: Spin up MongoDB Container & Seed Initial Data
```
docker run -d \
  --name movie-db \
  --network movie-net \
  mongo:6.0

docker cp mongo/init.json movie-db:/tmp/init.json

docker exec -i movie-db mongoimport \
  --db movies_db \
  --collection movies \
  --file /tmp/init.json \
  --jsonArray

docker exec -it movie-db mongosh movies_db --eval "db.movies.find()"
```

## Step 3: Build & Run Python Backend API Container
```
docker build -t movie-backend backend/

docker run -d \
  --name movie-api \
  --network movie-net \
  movie-backend

docker logs --tail 50 movie-api

docker exec -it movie-api python -c "
from pymongo import MongoClient
client = MongoClient('mongodb://movie-db:27017/')
db = client['movies_db']
print(list(db.movies.find({}, {'_id': 0})))
"
```

## Step 4: Build & Run JavaScript Frontend Container
```
docker build -t movie-frontend frontend/

docker run -d \
  --name movie-ui \
  --network movie-net \
  movie-frontend
```

## Step 5: Run the Nginx reverse proxy

```bash
docker run -d \
  --name nginx-proxy \
  --network movie-net \
  -p 8181:80 \
  -v "$PWD/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:alpine
```

## Step 6: Verification & Testing
```

http://localhost:8181/

curl -s "http://localhost:8181/api/movies?category=comedy"
```

## Run the Python tests and analyze the project with SonarQube

SonarQube analyzes the test and coverage reports; `pytest` runs the tests in a separate container.
Run these commands from `step4_movie-app`:

```bash
docker compose up -d sonarqube
```

Wait for SonarQube at [http://localhost:9000](http://localhost:9000). On first login, use
`admin` / `admin`, change the password, and create a token under **My Account > Security**.
Then set that token in your shell and run the test and analysis services:

```bash
export SONAR_TOKEN="paste-your-token-here"
docker compose run --rm tests
docker compose run --rm sonar-scanner
```

The tests create `test-results.xml` and `coverage.xml` in this directory. The scanner reads
those reports and publishes the analysis to the SonarQube project `movie-app`. In the SonarQube
UI, open **Projects > Movie Explorer** to view the results.

To stop SonarQube while keeping its data:

```bash
docker compose down
```

To also delete all stored data, including the movie database and SonarQube data, use
`docker compose down -v`.

## Clean up a manually started stack
```
# Stop and remove all 4 running containers
docker rm -f nginx-proxy movie-ui movie-api movie-db

# Delete custom Docker images
docker rmi movie-frontend movie-backend

# Delete the custom network
docker network rm movie-net

# Optional remove unused system caches and dangling resources
docker system prune -f
```