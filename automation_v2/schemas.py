"""Job payloads for the v2 queues. Same shape as the legacy ones plus `client_id`.

Unknown keys (client_id, gemId, tenderId, sender, ...) are ignored, so the routing
key never reaches business logic.
"""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class FetchJob(BaseModel):
    type: Literal["GEM_DOWNLOAD", "RA_GEM_DOWNLOAD", "NON_GEM_DOWNLOAD"]
    referenceNo: str = Field(min_length=1)


class FileParseJob(BaseModel):
    type: Literal["GEM_PDF_PARSING", "RA_GEM_PDF_PARSING", "NON_GEM_BOQ_PARSING"]
    referenceNo: str = Field(min_length=1)
    file_link: str = Field(min_length=1)


class CostingParseJob(BaseModel):
    type: Literal["COSTING_ATTACHMENT_PARSING"]
    referenceNo: str = Field(min_length=1)
    file_link: str | None = None
    file_type: Literal["network", "external"] | None = None
    decrypted_fileId: str | None = None


fetch_adapter = TypeAdapter(FetchJob)
parse_adapter = TypeAdapter(Annotated[Union[FileParseJob, CostingParseJob], Field(discriminator="type")])
