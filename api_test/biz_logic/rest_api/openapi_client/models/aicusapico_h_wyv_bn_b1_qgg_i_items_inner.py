# coding: utf-8

"""
    aics-api

    AI-Customer-Service - Core API

    The version of the OpenAPI document: 2024-10-24T04:30:07Z
    Generated by OpenAPI Generator (https://openapi-generator.tech)

    Do not edit the class manually.
"""  # noqa: E501


from __future__ import annotations
import pprint
import re  # noqa: F401
import json

from pydantic import BaseModel, ConfigDict, Field, StrictStr
from typing import Any, ClassVar, Dict, List
from typing import Optional, Set
from typing_extensions import Self

class AicusapicoHWyvBnB1QggIItemsInner(BaseModel):
    """
    AicusapicoHWyvBnB1QggIItemsInner
    """ # noqa: E501
    execution_id: StrictStr = Field(alias="executionId")
    file_name: StrictStr = Field(alias="fileName")
    create_by: StrictStr = Field(alias="createBy")
    chatbot_id: StrictStr = Field(alias="chatbotId")
    create_time: StrictStr = Field(alias="createTime")
    execution_status: StrictStr = Field(alias="executionStatus")
    index: StrictStr
    model: StrictStr
    details: StrictStr
    tag: StrictStr
    __properties: ClassVar[List[str]] = ["executionId", "fileName", "createBy", "chatbotId", "createTime", "executionStatus", "index", "model", "details", "tag"]

    model_config = ConfigDict(
        populate_by_name=True,
        validate_assignment=True,
        protected_namespaces=(),
    )


    def to_str(self) -> str:
        """Returns the string representation of the model using alias"""
        return pprint.pformat(self.model_dump(by_alias=True))

    def to_json(self) -> str:
        """Returns the JSON representation of the model using alias"""
        # TODO: pydantic v2: use .model_dump_json(by_alias=True, exclude_unset=True) instead
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> Optional[Self]:
        """Create an instance of AicusapicoHWyvBnB1QggIItemsInner from a JSON string"""
        return cls.from_dict(json.loads(json_str))

    def to_dict(self) -> Dict[str, Any]:
        """Return the dictionary representation of the model using alias.

        This has the following differences from calling pydantic's
        `self.model_dump(by_alias=True)`:

        * `None` is only added to the output dict for nullable fields that
          were set at model initialization. Other fields with value `None`
          are ignored.
        """
        excluded_fields: Set[str] = set([
        ])

        _dict = self.model_dump(
            by_alias=True,
            exclude=excluded_fields,
            exclude_none=True,
        )
        return _dict

    @classmethod
    def from_dict(cls, obj: Optional[Dict[str, Any]]) -> Optional[Self]:
        """Create an instance of AicusapicoHWyvBnB1QggIItemsInner from a dict"""
        if obj is None:
            return None

        if not isinstance(obj, dict):
            return cls.model_validate(obj)

        _obj = cls.model_validate({
            "executionId": obj.get("executionId"),
            "fileName": obj.get("fileName"),
            "createBy": obj.get("createBy"),
            "chatbotId": obj.get("chatbotId"),
            "createTime": obj.get("createTime"),
            "executionStatus": obj.get("executionStatus"),
            "index": obj.get("index"),
            "model": obj.get("model"),
            "details": obj.get("details"),
            "tag": obj.get("tag")
        })
        return _obj

