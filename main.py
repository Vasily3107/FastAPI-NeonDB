import os
from contextlib import asynccontextmanager
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Integer, Float, String, create_engine, select, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from enum import Enum

# API REQUEST - RESPONSES:
# https://docs.google.com/document/d/1lHRZZUi3Hd463mLt_ininkGnApsoJ1OaUAFsf7adwLY/edit?usp=sharing

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        'DATABASE_URL is not set. Create a .env file from .env '
        'and paste your Neon connection string there.'
    )
if DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace(
        'postgresql://', 'postgresql+psycopg://', 1
    )
elif DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace(
        'postgres://', 'postgresql+psycopg://', 1
    )


engine_options: dict = {'pool_pre_ping': True}
if DATABASE_URL.startswith('sqlite'):
    engine_options['connect_args'] = {'check_same_thread': False}
else:
    engine_options['pool_recycle'] = 300

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase): ...

class ContractStatus(Enum):
    OPEN = 'open'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    FAILED = 'failed'

class Contract(Base):
    __tablename__ = 'Contracts'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(String(10000), index=True)
    difficulty: Mapped[int] = mapped_column(Integer)
    reward: Mapped[float] = mapped_column(Float)
    region: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[ContractStatus] = mapped_column(default=ContractStatus.OPEN)

class ContractRead(BaseModel):
    id: int
    name: str
    description: str
    difficulty: int
    reward: float
    region: str
    status: ContractStatus
    
    model_config = ConfigDict(from_attributes=True)

class ContractCreate(BaseModel):
    name: str = Field(min_length=10, max_length=100)
    description: str = Field(min_length=10, max_length=1000)
    difficulty: int = Field(ge=0, le=10)
    reward: int = Field(ge=0)
    region: str = Field(min_length=2, max_length=100)
    status: ContractStatus = ContractStatus.OPEN

class ContractUpdate(BaseModel):
    name: str | None = Field(min_length=10, max_length=100, default=None)
    description: str | None = Field(min_length=10, max_length=1000, default=None)
    difficulty: int | None = Field(ge=1, le=10, default=None)
    reward: int | None = Field(ge=0, default=None)
    region: str | None = Field(min_length=2, max_length=100, default=None)

class Mercenary(Base):
    __tablename__ = 'Mercenaries'

    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str] = mapped_column(String(100), index=True)
    level: Mapped[int] = mapped_column(Integer)
    reputation: Mapped[float] = mapped_column(Float)
    balance: Mapped[float] = mapped_column(Float)

class MercenaryRead(BaseModel):
    id: int
    nickname: str
    level: int
    reputation: float
    balance: float
    
    model_config = ConfigDict(from_attributes=True)

class MercenaryCreate(BaseModel):
    nickname: str = Field(min_length=1, max_length=100)
    level: int = 1
    reputation: float = 0.0
    balance: float = 0.0

class MercenaryUpdate(BaseModel):
    nickname: str | None = Field(min_length=1, max_length=100, default=None)

class MercenaryToContract(Base):
    __tablename__ = 'MercenaryToContract'

    id: Mapped[int] = mapped_column(primary_key=True)
    c_id: Mapped[int] = mapped_column(ForeignKey('Contracts.id'))
    m_id: Mapped[int] = mapped_column(ForeignKey('Mercenaries.id'))

class MercenaryToContractCreate(BaseModel):
    c_id: int
    m_id: int

class MercenaryToContractRead(BaseModel):
    id: int
    c_id: int
    m_id: int

    model_config = ConfigDict(from_attributes=True)

class FinishContract(BaseModel):
    m_id: int
    success: bool


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

DbSession = Annotated[Session, Depends(get_db)]

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title='MERCNET',
    description='Create or Complete Dangerous Contracts. If you got the dime, we have the time.',
    version="1.0.0",
    lifespan=lifespan,
)


@app.get('/')
def root():
    return { 'message': 'Welcome to MERCNET! Create or Complete Contracts!' }

@app.get('/contracts/{id}', response_model=ContractRead)
def get_contract(
    db: DbSession,
    id: int
):
    if (contract := db.get(Contract, id)) is None:
        raise HTTPException(404, 'Contract not found')
    return contract

@app.get('/contracts', response_model=list[ContractRead])
def get_contracts(
    db: DbSession,
    status: ContractStatus | None = None,
    region: str | None = None,
    min_reward: float | None = None,
    max_difficulty: int | None = None
):
    res = select(Contract)

    if status is not None: res = res.where(Contract.status == status)
    if region is not None: res = res.where(Contract.region == region)

    if min_reward     is not None: res = res.where(Contract.reward >= min_reward)
    if max_difficulty is not None: res = res.where(Contract.difficulty <= max_difficulty)

    return db.scalars(res).all()

@app.post('/contracts', response_model=ContractRead, status_code=201)
def create_contract(
    db: DbSession,
    data: ContractCreate
):
    db.add(contract := Contract(**data.model_dump()))
    db.commit()
    db.refresh(contract)
    return contract

@app.patch('/contracts/{id}', response_model=ContractRead)
def update_contract(
    db: DbSession,
    id: int,
    data: ContractUpdate
):
    if (contract := db.get(Contract, id)) is None:
        raise HTTPException(404, 'Contract not found')

    update = data.model_dump(exclude_unset=True)

    for k, v in update.items(): setattr(contract, k, v)

    db.commit()
    db.refresh(contract)
    return contract

@app.delete('/contracts/{id}')
def delete_contract(
    db: DbSession,
    id: int
):
    if (contract := db.get(Contract, id)) is None:
        raise HTTPException(404, 'Contract not found')

    db.delete_all(db.scalars(select(MercenaryToContract).where(MercenaryToContract.c_id == id)).all())
    db.delete(contract)
    db.commit()
    return Response(status_code=204)

@app.get('/mercenaries/{id}', response_model=MercenaryRead)
def get_mercenary(
    db: DbSession,
    id: int
):
    if (mercenary := db.get(Mercenary, id)) is None:
        raise HTTPException(404, 'Mercenary not found')
    return mercenary

@app.get('/mercenaries', response_model=list[MercenaryRead])
def get_mercenaries(
    db: DbSession,
    nickname: str | None = None,
    level: int | None = None,
    min_reputation: float | None = None,
    min_balance: float | None = None
):
    res = select(Mercenary)

    if nickname is not None: res = res.where(nickname.lower() in Mercenary.nickname.lower())

    if level is not None: res = res.where(Mercenary.level == level)

    if min_reputation is not None: res = res.where(Mercenary.reputation >= min_reputation)

    if min_balance is not None: res = res.where(Mercenary.balance >= min_balance)

    return db.scalars(res).all()

@app.post('/mercenaries', response_model=MercenaryRead)
def create_mercenary(
    db:DbSession,
    data: MercenaryCreate
):
    db.add(mercenary := Mercenary(**data.model_dump()))
    db.commit()
    db.refresh(mercenary)
    return mercenary

@app.patch('/mercenaries/{id}', response_model=MercenaryRead)
def update_mercenary(
    db: DbSession,
    id: int,
    data: MercenaryUpdate
):
    if (mercenary := db.get(Mercenary, id)) is None:
        raise HTTPException(404, 'Mercenary not found')

    update = data.model_dump(exclude_unset=True)

    for k, v in update.items(): setattr(mercenary, k, v)

    db.commit()
    db.refresh(mercenary)
    return mercenary

@app.delete('/mercenaries/{id}')
def delete_mercenary(
    db: DbSession,
    id: int
):
    if (mercenary := db.get(Mercenary, id)) is None:
        raise HTTPException(404, 'Mercenary not found')

    contract: Contract | None = db.scalars(select(MercenaryToContract).where(MercenaryToContract.m_id == id)).first()
    if contract is not None: contract.status = ContractStatus.OPEN

    db.delete(mercenary)
    db.commit()
    return Response(status_code=204)

@app.get('/m2c', response_model=list[MercenaryToContractRead])
def get_m2c(
    db: DbSession,
    m_id: int | None = None,
    c_id: int | None = None
):
    res = select(MercenaryToContract)

    if m_id is not None: res = res.where(MercenaryToContract.m_id == m_id)
    if c_id is not None: res = res.where(MercenaryToContract.m_id == c_id)

    return db.scalars(res).all()

@app.post('/take_contract')
def take_contract(
    db: DbSession,
    data: MercenaryToContractCreate
):
    if (mercenary := db.get(Mercenary, data.m_id)) is None:
        raise HTTPException(400, 'Mercenary not found')

    if (contract := db.get(Contract, data.c_id)) is None:
        raise HTTPException(400, 'Contract not found')

    if db.scalars(select(MercenaryToContract).where(MercenaryToContract.m_id == data.m_id)).first() is not None:
        raise HTTPException(400, 'Mercenary with this id has an unfinished contract')

    if contract.difficulty > mercenary.level:
        raise HTTPException(400, 'Mercenary level is too low for this contract')

    contract.status = ContractStatus.IN_PROGRESS
    db.add(MercenaryToContract(**data.model_dump()))
    db.commit()
    return Response(status_code=201)

@app.post('/finish_contract')
def finish_contract(
    db: DbSession,
    data: FinishContract
):
    if (mercenary := db.get(Mercenary, data.m_id)) is None:
        raise HTTPException(400, 'Mercenary not found')

    if (m2c := db.scalars(select(MercenaryToContract).where(MercenaryToContract.m_id == data.m_id)).first()) is None:
        raise HTTPException(400, 'Mercenary with this id has no contracts in progress')

    contract = db.get(Contract, m2c.c_id)

    if data.success:
        contract.status = ContractStatus.COMPLETED
        if mercenary.level < 10: mercenary.level += 1
        mercenary.reputation += 1
        mercenary.balance += contract.reward

    else:
        contract.status = ContractStatus.FAILED
        mercenary.reputation -= 1

    db.delete(m2c)
    db.commit()
    return Response(status_code=200)

@app.get('/best_contract', response_model=ContractRead)
def get_best_contract(
    db: DbSession  
):
    res = db.scalars(select(Contract)).all()
    if len(res) == 0:
        raise HTTPException(404, 'There are no contracts yet')
    return max(res, key = lambda i: i.reward / i.difficulty)

