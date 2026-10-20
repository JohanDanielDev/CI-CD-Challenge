import json
import os
import pytest
import mongomock

@pytest.fixture
def mongo_db():
    """Sets up an in-memory MongoDB database populated from init.json."""
    client = mongomock.MongoClient()
    db = client["movies_db"]
    init_path = os.path.join(os.path.dirname(__file__), "init.json")
    
    if os.path.exists(init_path):
        with open(init_path, "r") as f:
            db.movies.insert_many(json.load(f))
    return db

def test_mongo_operations_and_projection(mongo_db):
    """Verify seed integrity, category queries, and _id suppression."""
    assert mongo_db.movies.count_documents({}) == 36
    assert mongo_db.movies.count_documents({"category": "drama"}) == 12
    assert mongo_db.movies.count_documents({"category": "comedy"}) == 12
    assert mongo_db.movies.count_documents({"category": "thriller"}) == 12
    assert mongo_db.movies.count_documents({"themes": {"$exists": True, "$ne": []}}) == 36

    thrillers = list(mongo_db.movies.find({"category": "thriller"}, {"_id": 0}))
    assert len(thrillers) == 12
    assert all("_id" not in movie for movie in thrillers)
    assert any(m["title"] == "The Dark Knight" for m in thrillers)