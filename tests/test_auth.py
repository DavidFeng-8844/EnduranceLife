"""
tests/test_auth.py — Test suite for authentication endpoints.

Covers:
    - User registration (success, duplicate 409, validation 422)
    - Login (success, wrong password, nonexistent user)
    - Token-based auth (/auth/me with valid/invalid/missing token)
    - Logout (token blacklisting, reuse after logout)
"""

import pytest


# ===========================================================================
# Registration Tests
# ===========================================================================

class TestRegister:

    def test_register_success(self, client):
        """Register a new user and verify the response."""
        resp = client.post("/auth/register", json={
            "username": "alice",
            "password": "secret123",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "alice"
        assert data["is_active"] is True
        assert "id" in data
        # Password hash must NEVER be in the response
        assert "hashed_password" not in data

    def test_register_duplicate_username(self, client):
        """Registering the same username twice returns 409."""
        client.post("/auth/register", json={
            "username": "bob",
            "password": "pass123456",
        })
        resp = client.post("/auth/register", json={
            "username": "bob",
            "password": "otherpass123",
        })
        assert resp.status_code == 409
        assert "already taken" in resp.json()["detail"]

    def test_register_short_username(self, client):
        """Username shorter than 3 chars returns 422."""
        resp = client.post("/auth/register", json={
            "username": "ab",
            "password": "secret123",
        })
        assert resp.status_code == 422

    def test_register_short_password(self, client):
        """Password shorter than 6 chars returns 422."""
        resp = client.post("/auth/register", json={
            "username": "charlie",
            "password": "12345",
        })
        assert resp.status_code == 422


# ===========================================================================
# Login Tests
# ===========================================================================

class TestLogin:

    def _register(self, client, username="testuser", password="testpass123"):
        client.post("/auth/register", json={
            "username": username,
            "password": password,
        })

    def test_login_success(self, client):
        """Login with correct credentials returns a JWT token."""
        self._register(client)
        resp = client.post("/auth/login", json={
            "username": "testuser",
            "password": "testpass123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert data["username"] == "testuser"
        assert len(data["access_token"]) > 20  # JWT is a long string

    def test_login_wrong_password(self, client):
        """Wrong password returns 401."""
        self._register(client)
        resp = client.post("/auth/login", json={
            "username": "testuser",
            "password": "wrongpass",
        })
        assert resp.status_code == 401
        assert "Incorrect" in resp.json()["detail"]

    def test_login_nonexistent_user(self, client):
        """Login with a username that doesn't exist returns 401."""
        resp = client.post("/auth/login", json={
            "username": "nobody",
            "password": "whatever",
        })
        assert resp.status_code == 401


# ===========================================================================
# Token & Protected Endpoint Tests
# ===========================================================================

class TestProtectedEndpoints:

    def _get_token(self, client, username="authuser", password="authpass123"):
        """Helper: register + login + return the token."""
        client.post("/auth/register", json={
            "username": username,
            "password": password,
        })
        resp = client.post("/auth/login", json={
            "username": username,
            "password": password,
        })
        return resp.json()["access_token"]

    def test_me_with_valid_token(self, client):
        """GET /auth/me with a valid token returns user info."""
        token = self._get_token(client)
        resp = client.get("/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "authuser"
        assert data["is_active"] is True

    def test_me_without_token(self, client):
        """GET /auth/me without a token returns 401."""
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token(self, client):
        """GET /auth/me with a garbage token returns 401."""
        resp = client.get("/auth/me", headers={
            "Authorization": "Bearer totally.invalid.token",
        })
        assert resp.status_code == 401


# ===========================================================================
# Logout Tests
# ===========================================================================

class TestLogout:

    def _get_token(self, client, username="logoutuser", password="logoutpass123"):
        """Helper: register + login + return the token."""
        client.post("/auth/register", json={
            "username": username,
            "password": password,
        })
        resp = client.post("/auth/login", json={
            "username": username,
            "password": password,
        })
        return resp.json()["access_token"]

    def test_logout_success(self, client):
        """Logout with a valid token returns 200."""
        token = self._get_token(client)
        resp = client.post("/auth/logout", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        assert "logged out" in resp.json()["detail"].lower()

    def test_token_rejected_after_logout(self, client):
        """After logout, the same token is rejected on /auth/me."""
        token = self._get_token(client)
        # Logout
        client.post("/auth/logout", headers={
            "Authorization": f"Bearer {token}",
        })
        # Try using the same token
        resp = client.get("/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 401

    def test_new_login_after_logout(self, client):
        """After logout, a new login issues a fresh valid token."""
        token_old = self._get_token(client)
        # Logout
        client.post("/auth/logout", headers={
            "Authorization": f"Bearer {token_old}",
        })
        # Old token should be rejected
        resp = client.get("/auth/me", headers={
            "Authorization": f"Bearer {token_old}",
        })
        assert resp.status_code == 401
        # Login again — new token works
        resp = client.post("/auth/login", json={
            "username": "logoutuser",
            "password": "logoutpass123",
        })
        assert resp.status_code == 200
        token_new = resp.json()["access_token"]
        # New token works
        resp = client.get("/auth/me", headers={
            "Authorization": f"Bearer {token_new}",
        })
        assert resp.status_code == 200
        assert resp.json()["username"] == "logoutuser"

    def test_logout_without_token(self, client):
        """Logout without a token returns 401."""
        resp = client.post("/auth/logout")
        assert resp.status_code == 401
