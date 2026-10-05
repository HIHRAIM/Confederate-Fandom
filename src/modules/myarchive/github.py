"""The few calls to GitHub's REST API the archive needs, and nothing else.

One repository, one branch. The whole tree is read once per pass, so a file
that has not changed costs nothing but a hash computed here; only a file that
did change costs a request for its last commit and one to commit it.

The token never leaves this module: it goes into the Authorization header and
nowhere else, and an error is reported as GitHub's status and message, which
do not carry it.
"""
import base64
import logging
import urllib.parse

import requests

logger = logging.getLogger("fd.modules.myarchive.github")

API = "https://api.github.com"

TIMEOUT = 30

class GitHubError(RuntimeError):
    """GitHub said no: the status and GitHub's own message, and no token."""

class GitHub:
    """One repository and one branch of it."""

    def __init__(self, token, repo, branch=None):
        """Nothing is asked until the first call."""
        self.repo = str(repo).strip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Confederate Fandom archive (fd_bot)",
        })
        self._branch = branch or None
        self._ids = {}

    def _call(self, method, path, **kwargs):
        """One request. -> the decoded answer, or None for a 404."""
        response = self.session.request(method, API + path, timeout=TIMEOUT,
                                        **kwargs)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            try:
                message = response.json().get("message")
            except ValueError:
                message = response.reason
            raise GitHubError("GitHub {} on {}: {}".format(
                response.status_code, path.split("?")[0], message))
        return response.json() if response.content else {}

    @property
    def branch(self):
        """The branch to commit to: the configured one, or the default."""
        if self._branch is None:
            data = self._call("GET", "/repos/{}".format(self.repo))
            if data is None:
                raise GitHubError("GitHub has no repository {} this token can "
                                  "see".format(self.repo))
            self._branch = data.get("default_branch") or "main"
        return self._branch

    def login(self):
        """The account the token belongs to — the author of every commit."""
        data = self._call("GET", "/user") or {}
        return data.get("login")

    def tree(self):
        """Every file of the branch -> {path: blob sha}."""
        data = self._call("GET", "/repos/{}/git/trees/{}?recursive=1".format(
            self.repo, urllib.parse.quote(self.branch, safe="")))
        if data is None:
            return {}
        if data.get("truncated"):
            logger.warning("the tree of %s is truncated; files beyond it are "
                           "treated as new", self.repo)
        return {item["path"]: item["sha"] for item in data.get("tree", [])
                if item.get("type") == "blob"}

    def _contents(self, path):
        """The contents endpoint of one path."""
        return "/repos/{}/contents/{}".format(
            self.repo, urllib.parse.quote(path, safe="/"))

    def read(self, path):
        """One file's bytes, or None when there is no such file."""
        data = self._call("GET", self._contents(path),
                          params={"ref": self.branch})
        if not data or data.get("encoding") != "base64":
            return None
        return base64.b64decode(data.get("content") or "")

    def last_commit_date(self, path):
        """When the file was last committed, as GitHub's ISO time, or None."""
        data = self._call("GET", "/repos/{}/commits".format(self.repo),
                          params={"path": path, "sha": self.branch,
                                  "per_page": 1})
        if not data:
            return None
        return data[0]["commit"]["committer"]["date"]

    def noreply(self, login):
        """A user's no-reply address — what a Co-authored-by line needs for
        GitHub to link the commit to that account. None for an unknown user."""
        if login not in self._ids:
            data = self._call("GET", "/users/{}".format(
                urllib.parse.quote(login, safe="")))
            self._ids[login] = data.get("id") if data else None
        user_id = self._ids[login]
        if user_id is None:
            return None
        return "{}+{}@users.noreply.github.com".format(user_id, login)

    def put(self, path, data, message, sha=None):
        """Create or replace one file with one commit."""
        body = {"message": message, "branch": self.branch,
                "content": base64.b64encode(data).decode("ascii")}
        if sha:
            body["sha"] = sha
        self._call("PUT", self._contents(path), json=body)
