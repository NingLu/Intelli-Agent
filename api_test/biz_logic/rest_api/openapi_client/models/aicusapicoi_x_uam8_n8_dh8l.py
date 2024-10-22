# coding: utf-8

"""
    aics-api

    AI-Customer-Service - Core API

    The version of the OpenAPI document: 2024-10-21T08:32:58Z
    Generated by OpenAPI Generator (https://openapi-generator.tech)

    Do not edit the class manually.
"""  # noqa: E501


from __future__ import annotations
import pprint
import re  # noqa: F401
import json

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from typing import Any, ClassVar, Dict, List, Optional
from openapi_client.models.aicusapico2_twv_xbhs_tncy_config import Aicusapico2TwvXbhsTncyConfig
from openapi_client.models.aicusapicoi_x_uam8_n8_dh8l_items_inner import AicusapicoiXUam8N8Dh8lItemsInner
from typing import Optional, Set
from typing_extensions import Self

class AicusapicoiXUam8N8Dh8l(BaseModel):
    """
    AicusapicoiXUam8N8Dh8l
    """ # noqa: E501
    chatbot_ids: Optional[List[StrictStr]] = None
    config: Optional[Aicusapico2TwvXbhsTncyConfig] = Field(default=None, alias="Config")
    items: Optional[List[AicusapicoiXUam8N8Dh8lItemsInner]] = Field(default=None, alias="Items")
    count: Optional[StrictInt] = Field(default=None, alias="Count")
    __properties: ClassVar[List[str]] = ["chatbot_ids", "Config", "Items", "Count"]

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
        """Create an instance of AicusapicoiXUam8N8Dh8l from a JSON string"""
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
        # override the default output from pydantic by calling `to_dict()` of config
        if self.config:
            _dict['Config'] = self.config.to_dict()
        # override the default output from pydantic by calling `to_dict()` of each item in items (list)
        _items = []
        if self.items:
            for _item in self.items:
                if _item:
                    _items.append(_item.to_dict())
            _dict['Items'] = _items
        return _dict

    @classmethod
    def from_dict(cls, obj: Optional[Dict[str, Any]]) -> Optional[Self]:
        """Create an instance of AicusapicoiXUam8N8Dh8l from a dict"""
        if obj is None:
            return None

        if not isinstance(obj, dict):
            return cls.model_validate(obj)

        _obj = cls.model_validate({
            "chatbot_ids": obj.get("chatbot_ids"),
            "Config": Aicusapico2TwvXbhsTncyConfig.from_dict(obj["Config"]) if obj.get("Config") is not None else None,
            "Items": [AicusapicoiXUam8N8Dh8lItemsInner.from_dict(_item) for _item in obj["Items"]] if obj.get("Items") is not None else None,
            "Count": obj.get("Count")
        })
        return _obj


