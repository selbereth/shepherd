import os
import tempfile

os.environ["SHEPHERD_ADMIN_KEY"] = "test-admin"
os.environ["SHEPHERD_DATA"] = tempfile.mkdtemp()
os.environ["SHEPHERD_FEED_URL"] = ""  # tests never touch the network
