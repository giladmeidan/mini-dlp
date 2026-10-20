def test_unknown_route_returns_not_found_envelope(client):
    response = client.get("/nope")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["message"]
    assert error["details"] == []


def test_wrong_method_returns_http_error_envelope_with_allow_header(client):
    response = client.post("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "HTTP_ERROR"
    assert "GET" in response.headers["allow"]
