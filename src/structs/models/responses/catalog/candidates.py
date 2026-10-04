from pydantic import BaseModel

from src.structs.enums import Closeness
from src.structs.models.platforms import Track


class Candidate(BaseModel):
    track: Track
    closeness: Closeness
