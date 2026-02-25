import asyncio
import logging

import httpx
from nio import (
    AsyncClient,
    JoinError,
    LoginError,
    RoomResolveAliasError,
    RoomSendError,
)
from pydantic import BaseModel, model_validator

from radiobsmatrix.core.config import get_settings

from typing import Any


class RadioStatus(BaseModel):
    encoder: str | None = None
    filename: str | None = None
    initial_uri: str | None = None
    language: str | None = None
    rid: str | None = None
    status: str | None = None
    temporary: str | None = None
    title: str | None = None
    vendor: str | None = None

    @model_validator(mode="before")
    @classmethod
    def parse_list(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {
                item[0]: item[1]
                for item in data
                if isinstance(item, list) and len(item) == 2
            }
        return data


async def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger("radiobsmatrix")

    settings = get_settings()
    matrix_homeserver = settings.matrix.homeserver
    matrix_user = settings.matrix.user
    matrix_password = settings.matrix.password
    matrix_room_id = settings.matrix.room_id
    matrix_send_messages = settings.matrix.send_messages
    matrix_update_topic = settings.matrix.update_topic
    radio_api_url = settings.radio.api_url
    poll_interval = settings.radio.poll_interval

    if not all([matrix_user, matrix_password, matrix_room_id, radio_api_url]):
        logger.error(
            "Missing required config! Set MATRIX_USER, MATRIX_PASSWORD, MATRIX_ROOM_ID, "
            "and RADIO_API_URL environment variables."
        )
        return

    logger.info("Initializing matrix client...")
    client = AsyncClient(matrix_homeserver, matrix_user)

    try:
        logger.info("Logging in to matrix...")
        login_res = await client.login(matrix_password)
        if isinstance(login_res, LoginError):
            logger.error(f"Failed to log in to Matrix: {login_res.message}")
            await client.close()
            return

        logger.info("Logged in successfully.")

        if matrix_room_id.startswith("#"):
            logger.info("Resolving room alias %s...", matrix_room_id)
            resolve_res = await client.room_resolve_alias(matrix_room_id)
            if isinstance(resolve_res, RoomResolveAliasError):
                logger.error(
                    f"Failed to resolve room {matrix_room_id}: {resolve_res.message}"
                )
                await client.logout()
                await client.close()
                return
            matrix_room_id = resolve_res.room_id
            logger.info("Resolved to internal room ID %s.", matrix_room_id)

        logger.info("Joining target room %s...", matrix_room_id)
        join_res = await client.join(matrix_room_id)
        if isinstance(join_res, JoinError):
            logger.error(f"Failed to join room {matrix_room_id}: {join_res.message}")
            await client.logout()
            await client.close()
            return
    except Exception as e:
        logger.error(f"Failed to log in to Matrix: {e}")
        await client.close()
        return

    current_title = None

    async with httpx.AsyncClient() as http_client:
        try:
            logger.info(
                "Starting to poll API (%s) every %ds.", radio_api_url, poll_interval
            )
            while True:
                try:
                    response = await http_client.get(radio_api_url, timeout=10.0)
                    response.raise_for_status()

                    data = response.json()
                    status = RadioStatus.model_validate(data)

                    song_title = status.title
                    if not song_title:
                        if status.filename:
                            song_title = status.filename.split("/")[-1].replace("_", " ")
                        else:
                            song_title = "Unknown Song"

                    if song_title and song_title != current_title:
                        if current_title is not None:
                            logger.info("🎵 Music changed: %s", song_title)
                        else:
                            logger.info("📻 Initial song: %s", song_title)

                        if matrix_send_messages:
                            message = f'🎵 Now playing: **{song_title}**'
                            send_res = await client.room_send(
                                room_id=matrix_room_id,
                                message_type="m.room.message",
                                content={
                                    "msgtype": "m.text",
                                    "format": "org.matrix.custom.html",
                                    "body": message,
                                    "formatted_body": message,
                                },
                            )
                            if isinstance(send_res, RoomSendError):
                                logger.error(
                                    f"Failed to send message: {send_res.message}"
                                )

                        if matrix_update_topic:
                            content = {
                                "topic": f'[{settings.radio.name}]({settings.radio.stream_url}) - 🎵 Now playing: {song_title}',
                            }
                            topic_res = await client.room_put_state(
                                room_id=matrix_room_id,
                                event_type="m.room.topic",
                                content=content,
                            )
                            if hasattr(topic_res, "message"):
                                logger.error(
                                    f"Failed to update room topic: {topic_res.message}"
                                )
                            else:
                                logger.info(f"Room topic updated to: {content['topic']}")

                        current_title = song_title

                except httpx.HTTPError as e:
                    logger.warning("HTTP error polling API: %s", e)
                except Exception as e:
                    logger.error(
                        "Unexpected error checking radio status: %s", e, exc_info=True
                    )

                await asyncio.sleep(poll_interval)
        finally:
            logger.info("Logging out and closing Matrix client...")
            await client.logout()
            await client.close()
