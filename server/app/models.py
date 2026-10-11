"""Messages client -> serveur, validés par Pydantic (jamais de confiance au client)."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class JoinMsg(BaseModel):
    t: Literal["join"]
    name: str = Field(default="", max_length=40)


class InputMsg(BaseModel):
    t: Literal["input"]
    dx: float = Field(ge=-2, le=2, allow_inf_nan=False)
    dy: float = Field(ge=-2, le=2, allow_inf_nan=False)
    a: float = Field(ge=-10, le=10, allow_inf_nan=False)   # angle de visée (radians)


class ActMsg(BaseModel):
    t: Literal["act"]
    k: Literal["shoot", "hit", "dash", "rage"]


ClientMsg = Annotated[JoinMsg | InputMsg | ActMsg, Field(discriminator="t")]
client_msg = TypeAdapter(ClientMsg)
