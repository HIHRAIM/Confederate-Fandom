"""The few calls to GitHub's REST API the archive needs, and nothing else.

One repository, one branch. The whole tree is read once per pass, so a file
that has not changed costs nothing but a hash computed here; only a file that
did change costs a request for its last commit and one to commit it.

The token never leaves this module: it goes into the Authorization header and
nowhere else, and an error is reported as GitHub's status and message, which
do not carry it.

**Commits are paced, and a rate limit is obeyed.** GitHub asks for at least a
second between mutating requests made in bulk, and warns that an integration
which goes on asking after a rate-limit answer may be banned. So `put` waits
WRITE_PAUSE after the previous commit, and a 403 or 429 that is a rate limit
raises `RateLimited`, which ends the pass instead of moving on to the next
page.
"""
import base64
import logging
import time
import urllib.parse

import requests

logger = logging.getLogger("fd.modules.myarchive.github")

API = "https://api.github.com"

TIMEOUT = 30

WRITE_PAUSE = 1.0
"""Seconds from the end of one commit to the start of the next, at the least:
GitHub's own advice for mutating requests ("Best practices for using the REST
API"). A night with a few changed pages does not notice it; the first night
of a long page list is a minute or two longer."""

class GitHubError(RuntimeError):
    """GitHub said no: the status and GitHub's own message, and no token."""

class RateLimited(GitHubError):
    """GitHub said to slow down: a secondary rate limit, or the hourly quota
    spent. Nothing more may be asked until the time GitHub names, so the pass
    stops at the first one; the pages left over are committed the next night,
    because a page already committed then compares equal to its file."""

def _rate_limited(response, message):
    """Whether an error answer is a rate limit rather than a refusal. GitHub
    answers 429, or 403 with `retry-after`, with `x-ratelimit-remaining: 0`,
    or with a message that says so — a 403 without any of them is a missing
    permission and must not be mistaken for one."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    headers = response.headers
    return ("retry-after" in headers
            or headers.get("x-ratelimit-remaining") == "0"
            or "rate limit" in str(message or "").lower())

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
        self._last_write = None

    def _call(self, method, path, **kwargs):
        """One request. -> the decoded answer, or None for a 404. Raises
        RateLimited for a rate limit and GitHubError for any other error."""
        response = self.session.request(method, API + path, timeout=TIMEOUT,
                                        **kwargs)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            try:
                message = response.json().get("message")
            except ValueError:
                message = response.reason
            text = "GitHub {} on {}: {}".format(
                response.status_code, path.split("?")[0], message)
            if _rate_limited(response, message):
                raise RateLimited(text)
            raise GitHubError(text)
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
        """Create or replace one file with one commit, no sooner than
        WRITE_PAUSE after the previous one — counted from the end of that
        one whether it succeeded or not, since a refused write is a request
        all the same. Blocking: the pass runs in a worker thread."""
        if self._last_write is not None:
            wait = self._last_write + WRITE_PAUSE - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        body = {"message": message, "branch": self.branch,
                "content": base64.b64encode(data).decode("ascii")}
        if sha:
            body["sha"] = sha
        try:
            self._call("PUT", self._contents(path), json=body)
        finally:
            self._last_write = time.monotonic()
