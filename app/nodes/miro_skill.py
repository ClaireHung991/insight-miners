"""Miro Skill — creates a visual mind map on a new Miro board via the REST API.

Receives: topic_tree (list of dicts from transcript_editor).
Produces: Miro board view URL.

Uses the Miro REST API v2 directly (sticky notes + connectors).
The mindmap_nodes endpoint is read-only in v2; instead we build an equivalent
visual layout using sticky notes positioned in a radial hierarchy:
  - Root sticky note at the centre
  - Topic sticky notes in a circle around the root
  - Subtopic sticky notes fanned out beyond each topic

Connectors link root→topic and topic→subtopic.

Auth: Bearer token from credentials.miro_access_token.
"""

import logging
import math

import httpx

from app import credentials

logger = logging.getLogger(__name__)

_MIRO_API = "https://api.miro.com/v2"

# Layout constants (Miro canvas units, roughly 1 px each at default zoom)
_ROOT_RADIUS = 450    # root → topic distance
_SUB_RADIUS = 320     # topic → subtopic distance
_ROOT_W, _ROOT_H = 240, 100
_TOPIC_W, _TOPIC_H = 200, 80
_SUB_W, _SUB_H = 180, 60

# Colour palette — Miro sticky notes only accept named colours
_FILL_ROOT = "yellow"
_FILL_TOPIC = "light_blue"
_FILL_SUB = "light_green"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {credentials.miro_access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _sticky_payload(
    label: str,
    x: float,
    y: float,
    w: float,
    h: float,
    fill_color: str,
) -> dict:
    return {
        "data": {"content": label, "shape": "square"},
        "style": {
            "fillColor": fill_color,
            "textAlign": "center",
            "textAlignVertical": "middle",
        },
        "position": {"x": x, "y": y, "origin": "center"},
        "geometry": {"width": w},
    }


def _connector_payload(from_id: str, to_id: str) -> dict:
    return {
        "startItem": {"id": from_id},
        "endItem": {"id": to_id},
        "style": {"strokeColor": "#888888", "strokeWidth": "1"},
    }


async def create_mindmap(topic_tree: list[dict]) -> str:
    """Create a Miro mind map from a topic tree.

    Args:
        topic_tree: Structured topic data from transcript_editor.
            Each item: {"topic": str, "subtopics": [{"subtopic": str, ...}]}

    Returns:
        View URL of the created Miro board.

    Raises:
        RuntimeError: If any Miro API call fails.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        # ── Step 1: Create a new board ────────────────────────────────────────
        board_resp = await client.post(
            f"{_MIRO_API}/boards",
            headers=_headers(),
            json={
                "name": "Interview Insights",
                "description": "Auto-generated mind map from interview transcript.",
                "policy": {
                    "sharingPolicy": {
                        "access": "view",
                        "teamAccess": "private",
                    }
                },
            },
        )
        if board_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create Miro board: {board_resp.status_code} {board_resp.text}"
            )

        board_data = board_resp.json()
        board_id = board_data["id"]
        view_link = board_data.get(
            "viewLink", f"https://miro.com/app/board/{board_id}=/"
        )
        logger.info(f"[miro] Created board {board_id}")

        # ── Step 2: Create the root sticky note ───────────────────────────────
        root_resp = await client.post(
            f"{_MIRO_API}/boards/{board_id}/sticky_notes",
            headers=_headers(),
            json=_sticky_payload("Interview Insights", 0, 0, _ROOT_W, _ROOT_H, _FILL_ROOT),
        )
        if root_resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Failed to create root node: {root_resp.status_code} {root_resp.text}"
            )
        root_id = root_resp.json()["id"]
        logger.info(f"[miro] Root node created ({root_id})")

        # ── Step 3: Topics in a circle, subtopics fanned out ─────────────────
        n_topics = len(topic_tree)

        for i, topic_item in enumerate(topic_tree):
            topic_label = topic_item.get("topic", "Topic")
            subtopics = topic_item.get("subtopics", [])

            # Angle for this topic (spread evenly around a full circle)
            topic_angle = (2 * math.pi * i / max(n_topics, 1)) - (math.pi / 2)
            tx = _ROOT_RADIUS * math.cos(topic_angle)
            ty = _ROOT_RADIUS * math.sin(topic_angle)

            topic_resp = await client.post(
                f"{_MIRO_API}/boards/{board_id}/sticky_notes",
                headers=_headers(),
                json=_sticky_payload(topic_label, tx, ty, _TOPIC_W, _TOPIC_H, _FILL_TOPIC),
            )
            if topic_resp.status_code not in (200, 201):
                logger.warning(f"[miro] Failed to create topic '{topic_label}'")
                continue
            topic_id = topic_resp.json()["id"]
            logger.info(f"[miro] Topic '{topic_label}' ({topic_id})")

            # Connect root → topic
            await client.post(
                f"{_MIRO_API}/boards/{board_id}/connectors",
                headers=_headers(),
                json=_connector_payload(root_id, topic_id),
            )

            # Subtopics: fan out beyond the topic in the same direction
            n_subs = len(subtopics)
            for j, sub in enumerate(subtopics):
                subtopic_label = sub.get("subtopic", "Detail")

                # Fan angle: ±30° spread around the topic's outward direction
                fan_spread = math.radians(50)
                if n_subs == 1:
                    sub_angle = topic_angle
                else:
                    sub_angle = topic_angle + fan_spread * (j / (n_subs - 1) - 0.5)

                sx = tx + _SUB_RADIUS * math.cos(sub_angle)
                sy = ty + _SUB_RADIUS * math.sin(sub_angle)

                sub_resp = await client.post(
                    f"{_MIRO_API}/boards/{board_id}/sticky_notes",
                    headers=_headers(),
                    json=_sticky_payload(
                        subtopic_label, sx, sy, _SUB_W, _SUB_H, _FILL_SUB
                    ),
                )
                if sub_resp.status_code not in (200, 201):
                    logger.warning(f"[miro] Failed subtopic '{subtopic_label}'")
                    continue
                sub_id = sub_resp.json()["id"]
                logger.info(f"[miro]   └─ subtopic '{subtopic_label}' ({sub_id})")

                # Connect topic → subtopic
                await client.post(
                    f"{_MIRO_API}/boards/{board_id}/connectors",
                    headers=_headers(),
                    json=_connector_payload(topic_id, sub_id),
                )

        logger.info(f"[miro] Mind map complete → {view_link}")
        return view_link
