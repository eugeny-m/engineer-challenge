from auth_service.domain.value_objects.auth_event_type import AuthEventType


class TestAuthEventType:
    def test_all_seven_values_present(self):
        assert len(AuthEventType) == 7

    def test_login_success_value(self):
        assert AuthEventType.LOGIN_SUCCESS == "login_success"

    def test_login_failed_value(self):
        assert AuthEventType.LOGIN_FAILED == "login_failed"

    def test_logout_value(self):
        assert AuthEventType.LOGOUT == "logout"

    def test_session_revoked_value(self):
        assert AuthEventType.SESSION_REVOKED == "session_revoked"

    def test_token_refreshed_value(self):
        assert AuthEventType.TOKEN_REFRESHED == "token_refreshed"

    def test_password_reset_requested_value(self):
        assert AuthEventType.PASSWORD_RESET_REQUESTED == "password_reset_requested"

    def test_password_reset_completed_value(self):
        assert AuthEventType.PASSWORD_RESET_COMPLETED == "password_reset_completed"

    def test_is_str_subclass(self):
        # AuthEventType extends str so values can be stored as VARCHAR without conversion
        for event_type in AuthEventType:
            assert isinstance(event_type, str)

    def test_lookup_by_value(self):
        assert AuthEventType("login_success") is AuthEventType.LOGIN_SUCCESS
