-- Initialize auth databases
-- auth database is already created by POSTGRES_DB env var
-- create auth_test database for test suite

SELECT 'CREATE DATABASE auth_test OWNER auth_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'auth_test')\gexec
