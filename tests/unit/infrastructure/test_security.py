"""Unit tests for BcryptHasher and JwtTokenService."""
import time
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import jwt as pyjwt

from auth_service.infrastructure.security.bcrypt_hasher import BcryptHasher
from auth_service.infrastructure.security.jwt_token_service import JwtTokenService
from auth_service.domain.exceptions import TokenExpiredError, InvalidTokenError

_SECRET = "test-secret-key-for-unit-tests"


# ---------------------------------------------------------------------------
# BcryptHasher tests
# ---------------------------------------------------------------------------

class TestBcryptHasher:
    def setup_method(self):
        self.hasher = BcryptHasher()

    def test_hash_produces_bcrypt_prefix(self):
        hashed = self.hasher.hash("correcthorse1")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_hash_is_not_plaintext(self):
        plain = "correcthorse1"
        hashed = self.hasher.hash(plain)
        assert hashed != plain

    def test_verify_correct_password(self):
        plain = "correcthorse1"
        hashed = self.hasher.hash(plain)
        assert self.hasher.verify(plain, hashed) is True

    def test_verify_wrong_password(self):
        hashed = self.hasher.hash("correcthorse1")
        assert self.hasher.verify("wrongpassword1", hashed) is False

    def test_hash_is_unique_per_call(self):
        # bcrypt salts mean same input yields different hash each time
        h1 = self.hasher.hash("password1")
        h2 = self.hasher.hash("password1")
        assert h1 != h2

    def test_verify_empty_password_does_not_crash(self):
        # empty string never matches a real hash
        hashed = self.hasher.hash("realpassword1")
        assert self.hasher.verify("", hashed) is False


# ---------------------------------------------------------------------------
# JwtTokenService tests
# ---------------------------------------------------------------------------

class TestJwtTokenService:
    def setup_method(self):
        self.service = JwtTokenService(secret=_SECRET, access_token_expire_minutes=15)
        self.user_id = uuid.uuid4()
        self.session_id = uuid.uuid4()

    def test_generate_access_token_returns_token_and_jti(self):
        token, jti = self.service.generate_access_token(self.user_id, self.session_id)
        assert isinstance(token, str)
        assert len(token) > 20
        assert isinstance(jti, str)
        assert jti  # non-empty UUID

    def test_decode_valid_token_returns_claims(self):
        token, _ = self.service.generate_access_token(self.user_id, self.session_id)
        claims = self.service.decode_access_token(token)
        assert claims["sub"] == str(self.user_id)
        assert claims["sid"] == str(self.session_id)

    def test_decode_includes_jti(self):
        token, jti_from_gen = self.service.generate_access_token(self.user_id, self.session_id)
        claims = self.service.decode_access_token(token)
        jti = claims["jti"]
        assert jti  # non-empty
        # jti returned by generate must match what's embedded in the token
        assert jti == jti_from_gen
        # Must be a valid UUID4
        parsed = uuid.UUID(jti)
        assert str(parsed) == jti

    def test_jti_is_unique_per_token(self):
        t1, jti1 = self.service.generate_access_token(self.user_id, self.session_id)
        t2, jti2 = self.service.generate_access_token(self.user_id, self.session_id)
        assert jti1 != jti2
        c1 = self.service.decode_access_token(t1)
        c2 = self.service.decode_access_token(t2)
        assert c1["jti"] != c2["jti"]

    def test_expired_token_raises_token_expired_error(self):
        # Create a service with -1 minute expiry so token is immediately expired
        service = JwtTokenService(secret=_SECRET, access_token_expire_minutes=-1)
        token, _ = service.generate_access_token(self.user_id, self.session_id)
        with pytest.raises(TokenExpiredError):
            service.decode_access_token(token)

    def test_tampered_token_raises_invalid_token_error(self):
        token, _ = self.service.generate_access_token(self.user_id, self.session_id)
        # Tamper with last character
        tampered = token[:-4] + "XXXX"
        with pytest.raises(InvalidTokenError):
            self.service.decode_access_token(tampered)

    def test_garbage_token_raises_invalid_token_error(self):
        with pytest.raises(InvalidTokenError):
            self.service.decode_access_token("not.a.jwt")

    def test_token_signed_with_wrong_secret_raises_invalid_token_error(self):
        other_service = JwtTokenService(secret="wrong-secret", access_token_expire_minutes=15)
        token, _ = other_service.generate_access_token(self.user_id, self.session_id)
        with pytest.raises(InvalidTokenError):
            self.service.decode_access_token(token)

    def test_generate_refresh_token_returns_non_empty_string(self):
        rt = self.service.generate_refresh_token()
        assert isinstance(rt, str)
        assert len(rt) >= 32

    def test_refresh_tokens_are_unique(self):
        tokens = {self.service.generate_refresh_token() for _ in range(10)}
        assert len(tokens) == 10
