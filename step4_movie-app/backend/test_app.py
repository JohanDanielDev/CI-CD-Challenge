from io import BytesIO
import json
import pytest
import mongomock
from unittest.mock import patch

@pytest.fixture
def client():
    """Sets up an in-memory MongoDB instance and Flask test client."""
    mock_client = mongomock.MongoClient()
    mock_db = mock_client["movies_db"]
    mock_db.movies.insert_many([
        {"title": "The Dark Knight", "category": "thriller", "year": 2008},
        {"title": "Superbad", "category": "comedy", "year": 2007},
        {"title": "Groundhog Day", "category": "comedy", "year": 1993},
    ])

    with patch("app.db", mock_db):
        from app import app
        app.config["TESTING"] = True
        with app.test_client() as test_client:
            yield test_client

def test_get_movies_filtering_and_projection(client):
    """Verify endpoint status, filtering logic, and _id exclusion."""
    # Test category filtering
    res = client.get("/api/movies?category=thriller")
    assert res.status_code == 200
    
    data = res.get_json()
    assert data["count"] == 1
    assert data["movies"][0]["title"] == "The Dark Knight"
    assert "_id" not in data["movies"][0]

    # Test all movies fallback
    res_all = client.get("/api/movies")
    assert res_all.status_code == 200
    assert res_all.get_json()["count"] == 3


def test_get_recommendations_uses_selected_category(client):
    model_response = b'{"response":"{\\"recommendations\\":[{\\"title\\":\\"Superbad\\"}]}"}'
    with patch("app.urlopen", return_value=BytesIO(model_response)) as open_url:
        res = client.post("/api/recommendations", json={"category": "comedy"})

    assert res.status_code == 200
    assert res.get_json()["category"] == "comedy"
    assert res.get_json()["recommendation"] == "1. Superbad (2007) — comedy"
    request_body = json.loads(open_url.call_args.args[0].data.decode("utf-8"))
    assert request_body["format"]["properties"]["recommendations"]["items"]["properties"]["title"]["enum"] == [
        "Superbad",
        "Groundhog Day",
    ]


def test_get_recommendations_uses_preference_and_skips_seen_titles(client):
    model_response = b'{"response":"{\\"recommendations\\":[{\\"title\\":\\"Groundhog Day\\"}]}"}'
    with patch("app.urlopen", return_value=BytesIO(model_response)) as open_url:
        res = client.post("/api/recommendations", json={
            "category": "comedy",
            "preference": "Something uplifting",
            "exclude_titles": ["Superbad"],
        })

    assert res.status_code == 200
    assert res.get_json()["recommendation"] == "1. Groundhog Day (1993) — comedy"
    request_body = json.loads(open_url.call_args.args[0].data.decode("utf-8"))
    assert "Something uplifting" in request_body["prompt"]
    assert "Superbad" not in request_body["prompt"]
    assert request_body["format"]["properties"]["recommendations"]["items"]["properties"]["title"]["enum"] == [
        "Groundhog Day",
    ]


def test_get_recommendations_rejects_too_long_preference(client):
    res = client.post("/api/recommendations", json={"preference": "x" * 241})

    assert res.status_code == 400


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"preference": 123}, "Preference must be a string."),
        ({"exclude_titles": "Superbad"}, "exclude_titles must be a list"),
        ({"exclude_titles": ["Superbad", 123]}, "exclude_titles must be a list"),
        ({"exclude_titles": ["Movie"] * 101}, "exclude_titles must be a list"),
    ],
)
def test_get_recommendations_rejects_invalid_preference_and_exclusions(client, payload, message):
    res = client.post("/api/recommendations", json=payload)

    assert res.status_code == 400
    assert message in res.get_json()["error"]


def test_get_recommendations_rejects_non_json_payload(client):
    res = client.post("/api/recommendations", data="not-json", content_type="application/json")

    assert res.status_code == 400
    assert res.get_json()["error"] == "A JSON object is required."


def test_get_recommendations_rejects_malformed_model_json(client):
    model_response = b'{"response":"this is not JSON"}'
    with patch("app.urlopen", return_value=BytesIO(model_response)):
        res = client.post("/api/recommendations", json={"category": "comedy"})

    assert res.status_code == 502
    assert res.get_json()["error"] == "The AI guide returned an invalid response."


def test_get_recommendations_reports_when_all_movies_were_seen(client):
    res = client.post("/api/recommendations", json={
        "category": "comedy",
        "exclude_titles": ["Superbad", "Groundhog Day"],
    })

    assert res.status_code == 409
    assert "seen every movie" in res.get_json()["error"]


def test_get_recommendations_ignores_titles_not_in_collection(client):
    model_response = (
        b'{"response":"{\\"recommendations\\":[{\\"title\\":\\"This Is Spinal Tap\\"},'
        b'{\\"title\\":\\"Superbad\\"}]}"}'
    )
    with patch("app.urlopen", return_value=BytesIO(model_response)):
        res = client.post("/api/recommendations", json={"category": "comedy"})

    assert res.status_code == 200
    assert res.get_json()["recommendation"] == "1. Superbad (2007) — comedy"
    assert "Spinal Tap" not in res.get_json()["recommendation"]


def test_get_recommendations_rejects_response_with_only_unknown_titles(client):
    model_response = b'{"response":"{\\"recommendations\\":[{\\"title\\":\\"This Is Spinal Tap\\"}]}"}'
    with patch("app.urlopen", return_value=BytesIO(model_response)):
        res = client.post("/api/recommendations", json={"category": "comedy"})

    assert res.status_code == 502
    assert "could not choose a movie" in res.get_json()["error"]


def test_get_recommendations_reports_unavailable_model(client):
    from urllib.error import URLError

    with patch("app.urlopen", side_effect=URLError("offline")):
        res = client.post("/api/recommendations", json={"category": "comedy"})

    assert res.status_code == 503
    assert "AI guide is unavailable" in res.get_json()["error"]


def test_get_recommendations_rejects_unknown_category(client):
    res = client.post("/api/recommendations", json={"category": "documentary"})

    assert res.status_code == 400