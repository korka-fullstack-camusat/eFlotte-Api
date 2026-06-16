from pydantic import BaseModel


class CheckListVLBase(BaseModel):
    brand: str | None = None
    model: str | None = None
    plaque_immatriculation: str
    label: str | None = None
    car_group: str | None = None
    semaines: dict[str, str | None] = {}


class CheckListVLCreate(CheckListVLBase):
    pass


class CheckListVLUpdate(BaseModel):
    brand: str | None = None
    model: str | None = None
    plaque_immatriculation: str | None = None
    label: str | None = None
    car_group: str | None = None
    semaines: dict[str, str | None] | None = None


class CheckListVLOut(CheckListVLBase):
    id: int
    model_config = {"from_attributes": True}


class CheckListVLPage(BaseModel):
    items: list[CheckListVLOut]
    total: int


class FiltresCheckListVL(BaseModel):
    brands: list[str]
    car_groups: list[str]


class ImportCheckListVLResult(BaseModel):
    created: int
    updated: int
    errors: list[dict]
