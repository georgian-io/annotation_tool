from _pytest.tmpdir import tmp_path

from alchemy.config.base import *  # noqa # Must be absolute package name

DEBUG = True
TESTING = True
SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

ANNOTATION_TOOL_ANNOTATION_SERVER_SECRET = 'asdasd'
ANNOTATION_TOOL_ADMIN_SERVER_PASSWORD = "password"
# ALCHEMY_FILESTORE_DIR = tmp_path