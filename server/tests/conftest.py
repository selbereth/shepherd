import os
import tempfile

os.environ["HOMELOCK_ADMIN_KEY"] = "test-admin"
os.environ["HOMELOCK_DATA"] = tempfile.mkdtemp()
