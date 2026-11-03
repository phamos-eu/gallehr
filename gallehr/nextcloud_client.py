"""Connection to Nextcloud as the bot account in Nextcloud Settings, shared by the calendar sync and the project folders."""

from urllib.parse import quote, urljoin

import requests
from frappe.utils.password import get_decrypted_password

SETTINGS = "Nextcloud Settings"
TIMEOUT = 30


def session(settings):
	s = requests.Session()
	s.auth = (settings.username, get_decrypted_password(SETTINGS, SETTINGS, "app_password"))
	return s


def base_url(settings):
	return settings.server_url.rstrip("/") + "/"


def files_url(settings, segments):
	"""WebDAV URL of a folder in the bot's files; each name is encoded on its own, so spaces/umlauts/& are safe."""
	path = "".join(quote(segment, safe="") + "/" for segment in segments)
	return urljoin(base_url(settings), f"remote.php/dav/files/{quote(settings.username)}/") + path
