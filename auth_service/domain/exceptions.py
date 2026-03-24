class InvalidEmailError(Exception):
    pass


class WeakPasswordError(Exception):
    pass


class UserAlreadyExistsError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class TokenExpiredError(Exception):
    pass


class TokenAlreadyUsedError(Exception):
    pass


class TokenNotFoundError(Exception):
    pass


class InvalidTokenError(Exception):
    pass
