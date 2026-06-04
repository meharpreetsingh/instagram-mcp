from typing import TypedDict, Optional, List


class Credentials(TypedDict):
    sessionid: str
    csrftoken: str
    ds_user_id: str


class Message(TypedDict):
    message_id: str
    thread_id: str
    sender: Optional[str]
    sender_id: Optional[str]
    text: Optional[str]
    item_type: Optional[str]
    timestamp: Optional[str]


class Thread(TypedDict):
    thread_id: str
    thread_title: Optional[str]
    is_group: bool
    participants: List[str]
    messages: List[Message]
