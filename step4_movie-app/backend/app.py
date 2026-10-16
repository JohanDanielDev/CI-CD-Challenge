import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient

app = Flask(__name__)
# Enable CORS for all routes so the browser/frontend can fetch data
CORS(app, resources={r"/*": {"origins": "*"}})

MONGO_URI = os.getenv("MONGO_URI", "mongodb://movie-db:27017/movies_db")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:1b")

client = MongoClient(MONGO_URI)
db = client.get_database("movies_db")

@app.route("/api/movies", methods=["GET"])
def get_movies():
    try:
        category = request.args.get("category", "").lower().strip()
        query = {"category": category} if category else {}
        
        # EXPLICITLY exclude _id from projection: {"_id": 0}
        movies = list(db.movies.find(query, {"_id": 0}))
        
        return jsonify({
            "category": category or "all",
            "count": len(movies),
            "movies": movies
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/recommendations", methods=["POST"])
def get_recommendations():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required."}), 400

    raw_category = payload.get("category", "")
    if not isinstance(raw_category, str):
        return jsonify({"error": "Category must be a string."}), 400
    category = raw_category.lower().strip()
    if category and category not in {"drama", "comedy", "thriller"}:
        return jsonify({"error": "Choose drama, comedy, thriller, or all."}), 400

    preference = payload.get("preference", "")
    if not isinstance(preference, str):
        return jsonify({"error": "Preference must be a string."}), 400
    preference = preference.strip()
    if len(preference) > 240:
        return jsonify({"error": "Preference must be 240 characters or fewer."}), 400

    excluded_titles = payload.get("exclude_titles", [])
    if (
        not isinstance(excluded_titles, list)
        or len(excluded_titles) > 100
        or any(not isinstance(title, str) for title in excluded_titles)
    ):
        return jsonify({"error": "exclude_titles must be a list of at most 100 movie titles."}), 400

    query = {"category": category} if category else {}
    movies = list(db.movies.find(
        query,
        {"_id": 0, "title": 1, "year": 1, "category": 1, "themes": 1},
    ))
    movies = [movie for movie in movies if isinstance(movie.get("title"), str) and movie["title"].strip()]
    if not movies:
        return jsonify({"error": "No movies are available for that category."}), 404

    excluded_titles = set(excluded_titles)
    candidates = [movie for movie in movies if movie["title"] not in excluded_titles]
    if not candidates:
        return jsonify({"error": "You've seen every movie in this collection. Start a fresh round."}), 409

    titles = [movie["title"] for movie in candidates]
    prompt = (
        "You are a movie discovery assistant. Choose up to three varied picks from the supplied "
        "collection that best match the user's mood or request. Use the supplied themes and "
        "metadata; do not invent movies or plot details. Prefer different titles on each request "
        "when there is no specific preference. Return only selected titles in the required JSON format.\n"
        f"Selected category: {category or 'all'}\n"
        f"User's mood or request: {preference or 'Surprise me with varied picks.'}\n"
        f"Movies: {json.dumps(candidates)}"
    )
    response_schema = {
        "type": "object",
        "properties": {
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "enum": titles},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
                "minItems": 1,
                "maxItems": min(3, len(titles)),
            },
        },
        "required": ["recommendations"],
        "additionalProperties": False,
    }
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": response_schema,
        "stream": False,
        "options": {"temperature": 0.7, "top_p": 0.9},
    }).encode("utf-8")
    ollama_request = Request(
        f"{OLLAMA_URL.rstrip('/')}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(ollama_request, timeout=60) as response:
            result = json.load(response)
    except (URLError, TimeoutError, OSError):
        app.logger.warning("Ollama is unavailable at %s", OLLAMA_URL)
        return jsonify({
            "error": "The AI guide is unavailable. Start it with "
                     "`docker compose --profile ai up -d ollama` and pull the model.",
        }), 503
    except (json.JSONDecodeError, UnicodeDecodeError):
        app.logger.exception("Ollama returned invalid JSON")
        return jsonify({"error": "The AI guide returned an invalid response."}), 502

    raw_recommendation = result.get("response") if isinstance(result, dict) else None
    if not isinstance(raw_recommendation, str):
        app.logger.error("Ollama response did not contain recommendations")
        return jsonify({"error": "The AI guide returned an invalid response."}), 502

    try:
        selected = json.loads(raw_recommendation)
    except json.JSONDecodeError:
        app.logger.exception("Ollama recommendation was not valid JSON")
        return jsonify({"error": "The AI guide returned an invalid response."}), 502

    allowed_movies = {movie["title"]: movie for movie in movies}
    recommendations = []
    seen_titles = set()
    if isinstance(selected, dict) and isinstance(selected.get("recommendations"), list):
        for item in selected["recommendations"]:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            if isinstance(title, str) and title in allowed_movies and title not in seen_titles:
                recommendations.append(allowed_movies[title])
                seen_titles.add(title)
            if len(recommendations) == 3:
                break

    if not recommendations:
        app.logger.error("Ollama did not select any movies from the supplied collection")
        return jsonify({"error": "The AI guide could not choose a movie from this collection."}), 502

    recommendation = "\n".join(
        f"{index}. {movie['title']} ({movie.get('year', 'year unknown')}) — "
        f"{movie.get('category', 'uncategorized')}"
        + (f" · themes: {', '.join(movie['themes'])}" if isinstance(movie.get("themes"), list) else "")
        for index, movie in enumerate(recommendations, start=1)
    )

    return jsonify({
        "category": category or "all",
        "recommendation": recommendation,
        "recommendations": recommendations,
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)