import base64

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_submit_frame():
    image = base64.b64encode(b"\xff\xd8\xff\xd9").decode("ascii")

    # test case for normally submitted frame
    response = client.post(
        "/v1/frames",
        json={
            "robot_id": "aido_001",
            "timestamp": "2026-10-01T12:00:00Z",
            "image_base64": image,
        },
    )

    # Confirm the response code is succesful when a valid frame and properly formatted data is submitted
    assert response.status_code == 202
    assert "frame_id" in response.json()
    assert response.json()["status"] == "accepted"

    frame_id = response.json()["frame_id"]

    # Now check if frame_id is succcesfully submitted to the frame "database"
    # Currently the data base is just a list but should be PostgreSQL

    # Send get request with URL endpoint to get a frame
    lookup = client.get(f"/v1/frames/{frame_id}")

    # Ensure returned status code indicates success and the robot id is the passed in robot id earlier
    assert lookup.status_code == 200
    assert lookup.json()["robot_id"] == "aido_001"


# Now test the case the frame is non existent
def test_missing_frame():
    response = client.get("/v1/frames/nonexistent")
    assert response.status_code == 404


def test_robot_state():
    response = client.get("/v1/robots/aido_001/state")

    assert response.status_code == 200
    assert response.json()["state"] == "unknown"
    assert response.json()["source"] == "stub"


def test_detections():
    response = client.get("/v1/detections?robot_id=aido_001&limit=10")

    assert response.status_code == 200
    assert response.json()["items"] == []


# Test if an invalid frame is passed in
def test_invalid_frame():
    response = client.post(
        "/v1/frames",
        json={
            "robot_id": "aido_001",
            "timestamp": "not-a-date",
            "image_base64": "bad-data",
        },
    )

    assert response.status_code == 422


def test_empty_frame():
    response = client.post("/v1/frames", json={"image_base64": ""})

    assert response.status_code == 422
