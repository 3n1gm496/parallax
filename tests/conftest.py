import os

# Override DB URL for unit tests — unit tests use mocks, not a real DB.
os.environ.setdefault("DATABASE_URL", "postgresql://parallax:dev_password@localhost:5432/parallax")
