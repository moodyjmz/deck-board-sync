"""Minimal stdlib-only client for the Nextcloud Deck REST API.

Board/stack/card CRUD lives under the bare-JSON /index.php/apps/deck/api/v1.0
path. Comments live only under the OCS-wrapped /ocs/v2.php/apps/deck/api/v1.0
path and return a {"ocs": {"meta": ..., "data": ...}} envelope -- the two
families are not interchangeable, so there are two request helpers below,
not one generic path with a flag.
"""

import base64
import json
import urllib.error
import urllib.request


class DeckAPIError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"Deck API error {status}: {body}")


class DeckClient:
    def __init__(self, base_url, user, app_password, allow_insecure=False):
        base_url = base_url.rstrip("/")
        if not base_url.startswith("https://") and not allow_insecure:
            raise ValueError(
                "NC_DECK_URL must start with https:// -- this credential is "
                "account-wide, sending it over plain http is not a mistake "
                "you get to take back. Pass allow_insecure=True (--allow-insecure "
                "on the CLI) only for a local/dev instance."
            )
        self.base_url = base_url
        # Sent explicitly on every request rather than via
        # urllib.request.HTTPBasicAuthHandler, which only sends credentials
        # after a 401 challenge. A reverse-proxied Nextcloud that redirects
        # unauthenticated requests to an HTML login page (200 OK) instead of
        # a clean 401 makes the handler silently fail to authenticate.
        token = base64.b64encode(f"{user}:{app_password}".encode()).decode()
        self._auth_header = f"Basic {token}"

    def _headers(self):
        return {
            "OCS-APIRequest": "true",
            "Content-Type": "application/json",
            "Authorization": self._auth_header,
        }

    def _do_request(self, url, method, body):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise DeckAPIError(e.code, e.read().decode(errors="replace")) from None

    def _request(self, method, path, body=None, dry_run=False):
        call = {"method": method, "path": f"{self.base_url}/index.php/apps/deck/api/v1.0{path}", "body": body}
        if dry_run:
            return call
        raw = self._do_request(call["path"], method, body)
        return json.loads(raw) if raw else None

    def _request_ocs(self, method, path, body=None, dry_run=False):
        call = {"method": method, "path": f"{self.base_url}/ocs/v2.php/apps/deck/api/v1.0{path}?format=json", "body": body}
        if dry_run:
            return call
        raw = self._do_request(call["path"], method, body)
        parsed = json.loads(raw)
        meta = parsed["ocs"]["meta"]
        if meta.get("status") != "ok":
            raise DeckAPIError(meta.get("statuscode"), meta.get("message"))
        return parsed["ocs"]["data"]

    # -- reads, also used for apply-spec idempotency checks --

    def list_boards(self):
        return self._request("GET", "/boards")

    def get_board(self, board_id):
        # list_boards() always returns an empty "labels" array regardless of
        # what's actually on the board (confirmed against a live board that
        # has default labels) -- fetch a single board when labels matter.
        return self._request("GET", f"/boards/{board_id}")

    def list_stacks(self, board_id):
        return self._request("GET", f"/boards/{board_id}/stacks")

    def list_cards(self, board_id, stack_id):
        stack = self._request("GET", f"/boards/{board_id}/stacks/{stack_id}")
        return stack.get("cards") or []

    def get_card(self, board_id, stack_id, card_id):
        # Same issue as get_board(): the stack-nested listing above returns
        # "labels": null on every card regardless of what's actually
        # assigned (confirmed live -- assignLabel succeeded, list_cards
        # still showed null, only a single-card GET showed the real label).
        # Anything that needs to know a card's current labels must fetch it
        # individually.
        return self._request("GET", f"/boards/{board_id}/stacks/{stack_id}/cards/{card_id}")

    # -- writes --

    def create_board(self, title, color="0082C9", dry_run=False):
        return self._request("POST", "/boards", {"title": title, "color": color}, dry_run=dry_run)

    def create_stack(self, board_id, title, order=999, dry_run=False):
        return self._request("POST", f"/boards/{board_id}/stacks", {"title": title, "order": order}, dry_run=dry_run)

    def create_card(self, board_id, stack_id, title, description=None, duedate=None, order=999, dry_run=False):
        body = {"title": title, "type": "plain", "order": order}
        if description is not None:
            body["description"] = description
        if duedate is not None:
            body["duedate"] = duedate
        return self._request("POST", f"/boards/{board_id}/stacks/{stack_id}/cards", body, dry_run=dry_run)

    def move_card(self, board_id, stack_id, card_id, target_stack_id, order=999, dry_run=False):
        path = f"/boards/{board_id}/stacks/{stack_id}/cards/{card_id}/reorder"
        return self._request("PUT", path, {"stackId": target_stack_id, "order": order}, dry_run=dry_run)

    def add_comment(self, card_id, message, dry_run=False):
        return self._request_ocs("POST", f"/cards/{card_id}/comments", {"message": message}, dry_run=dry_run)

    def create_label(self, board_id, title, color, dry_run=False):
        return self._request("POST", f"/boards/{board_id}/labels", {"title": title, "color": color}, dry_run=dry_run)

    def assign_label(self, board_id, stack_id, card_id, label_id, dry_run=False):
        path = f"/boards/{board_id}/stacks/{stack_id}/cards/{card_id}/assignLabel"
        return self._request("PUT", path, {"labelId": label_id}, dry_run=dry_run)

    def remove_label(self, board_id, stack_id, card_id, label_id, dry_run=False):
        path = f"/boards/{board_id}/stacks/{stack_id}/cards/{card_id}/removeLabel"
        return self._request("PUT", path, {"labelId": label_id}, dry_run=dry_run)
