import pytest

from auth_service.domain.exceptions import InvalidEmailError, WeakPasswordError
from auth_service.domain.value_objects.email import Email
from auth_service.domain.value_objects.hashed_password import HashedPassword
from auth_service.domain.value_objects.plain_password import PlainPassword
from auth_service.domain.value_objects.reset_token import ResetToken


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


class TestEmail:
    def test_valid_email(self):
        email = Email("user@example.com")
        assert email.value == "user@example.com"

    def test_normalizes_to_lowercase(self):
        email = Email("User@Example.COM")
        assert email.value == "user@example.com"

    def test_strips_whitespace(self):
        email = Email("  user@example.com  ")
        assert email.value == "user@example.com"

    def test_missing_at_sign(self):
        with pytest.raises(InvalidEmailError):
            Email("userexample.com")

    def test_missing_domain(self):
        with pytest.raises(InvalidEmailError):
            Email("user@")

    def test_missing_local_part(self):
        with pytest.raises(InvalidEmailError):
            Email("@example.com")

    def test_missing_tld(self):
        with pytest.raises(InvalidEmailError):
            Email("user@example")

    def test_empty_string(self):
        with pytest.raises(InvalidEmailError):
            Email("")

    def test_equality(self):
        assert Email("a@b.com") == Email("A@B.COM")

    def test_immutable(self):
        email = Email("a@b.com")
        with pytest.raises((AttributeError, TypeError)):
            email.value = "other@b.com"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PlainPassword
# ---------------------------------------------------------------------------


class TestPlainPassword:
    def test_valid_password(self):
        pw = PlainPassword("password1")
        assert pw.value == "password1"

    def test_too_short(self):
        with pytest.raises(WeakPasswordError):
            PlainPassword("pass1")

    def test_exactly_min_length_no_digit(self):
        with pytest.raises(WeakPasswordError):
            PlainPassword("password")

    def test_missing_digit(self):
        with pytest.raises(WeakPasswordError):
            PlainPassword("longpassword")

    def test_repr_hides_value(self):
        pw = PlainPassword("secret99")
        assert "secret99" not in repr(pw)
        assert "secret99" not in str(pw)

    def test_exactly_max_length(self):
        pw = PlainPassword("a" * 127 + "1")  # 128 chars, contains digit
        assert len(pw.value) == 128

    def test_too_long(self):
        with pytest.raises(WeakPasswordError):
            PlainPassword("a" * 128 + "1")  # 129 chars

    def test_immutable(self):
        pw = PlainPassword("secure1!")
        with pytest.raises((AttributeError, TypeError)):
            pw.value = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# HashedPassword
# ---------------------------------------------------------------------------


class TestHashedPassword:
    def test_stores_value(self):
        hp = HashedPassword("$2b$12$somehash")
        assert hp.value == "$2b$12$somehash"

    def test_immutable(self):
        hp = HashedPassword("$2b$12$somehash")
        with pytest.raises((AttributeError, TypeError)):
            hp.value = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ResetToken
# ---------------------------------------------------------------------------


class TestResetToken:
    def test_stores_value(self):
        rt = ResetToken("abc123")
        assert rt.value == "abc123"

    def test_immutable(self):
        rt = ResetToken("abc123")
        with pytest.raises((AttributeError, TypeError)):
            rt.value = "other"  # type: ignore[misc]
