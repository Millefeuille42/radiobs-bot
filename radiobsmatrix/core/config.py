import os
from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)

TOML_FILE_PATH = os.environ.get("TOML_FILE_PATH", "config.toml")
YAML_FILE_PATH = os.environ.get("YAML_FILE_PATH", "config.yaml")


class MatrixSettings(BaseModel):
    homeserver: str = Field(
        description="Matrix homeserver URL", default="https://matrix.org"
    )
    user: str = Field(description="Matrix user ID", default="")
    password: str = Field(description="Matrix password", default="")
    room_id: str = Field(description="Matrix room ID to send messages to", default="")
    send_messages: bool = Field(
        description="Whether to send now playing messages to the room", default=True
    )
    update_topic: bool = Field(
        description="Whether to update the room topic with the current song",
        default=False,
    )


class RadioSettings(BaseModel):
    name: str = Field(description="Radio name", default="")
    stream_url: str = Field(description="Radio stream URL", default="")
    api_url: str = Field(description="Web radio API URL", default="")
    poll_interval: int = Field(
        description="Interval in seconds to poll the API", default=15
    )


class Settings(BaseSettings):
    matrix: MatrixSettings = Field(default_factory=MatrixSettings)
    radio: RadioSettings = Field(default_factory=RadioSettings)

    @classmethod
    def settings_customise_sources(  # type: ignore[override]
        cls, settings_cls: type[BaseSettings], **kwargs
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        global TOML_FILE_PATH
        global YAML_FILE_PATH

        return (
            EnvSettingsSource(
                settings_cls,
                env_prefix="RADIOBOT__",
                env_nested_delimiter="__",
                case_sensitive=False,
            ),
            TomlConfigSettingsSource(settings_cls, toml_file=TOML_FILE_PATH),
            YamlConfigSettingsSource(settings_cls, yaml_file=YAML_FILE_PATH),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
