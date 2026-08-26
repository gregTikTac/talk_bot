from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Все времена в базе — с явным часовым поясом (UTC). Без этого asyncpg
# отказывается писать offset-aware datetime.now(timezone.utc) в колонку.
UTCDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    dialogs: Mapped[list["Dialog"]] = relationship(back_populates="counterparty")


class Dialog(Base):
    __tablename__ = "dialogs"

    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_id: Mapped[int] = mapped_column(ForeignKey("counterparties.id"))
    title: Mapped[str] = mapped_column(String(255))
    topic_id: Mapped[int | None] = mapped_column(default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    summary_upto_msg_id: Mapped[int | None] = mapped_column(default=None)
    style_card: Mapped[dict | None] = mapped_column(JSON, default=None)

    counterparty: Mapped["Counterparty"] = relationship(back_populates="dialogs")
    plans: Mapped[list["Plan"]] = relationship(back_populates="dialog")


class MessageDirection(str, Enum):
    IN = "in"
    OUT = "out"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id"))
    direction: Mapped[MessageDirection]
    tg_message_id: Mapped[int | None] = mapped_column(default=None)
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime)
    source: Mapped[str] = mapped_column(String(32))  # "forward" | "telethon"


class Plan(Base):
    """
    Версия плана переговоров. Планы не редактируются — новое условие
    means новая версия с changelog. Так видна разница между
    "передумал" (новая версия с обоснованием) и "прогнулся" (обход guard).
    """

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id"))
    version: Mapped[int]
    active: Mapped[bool] = mapped_column(default=True)
    changelog: Mapped[str | None] = mapped_column(Text, default=None)

    dialog: Mapped["Dialog"] = relationship(back_populates="plans")
    items: Mapped[list["PlanItem"]] = relationship(back_populates="plan")


class PlanItemKind(str, Enum):
    RED_LINE = "red_line"
    TARGET = "target"
    FLEXIBLE = "flexible"


class PlanItem(Base):
    """
    Один пункт плана. Для red_line обязательны fallback (что делаем,
    если контрагент упрётся) и breach_signal (по какому признаку guard
    считает пункт нарушенным) — без них guard будет шуметь вхолостую.
    """

    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    value: Mapped[str | None] = mapped_column(Text, default=None)
    kind: Mapped[PlanItemKind]
    fallback: Mapped[str | None] = mapped_column(Text, default=None)
    breach_signal: Mapped[str | None] = mapped_column(Text, default=None)

    plan: Mapped["Plan"] = relationship(back_populates="items")


class DraftOrigin(str, Enum):
    MODEL = "model"
    USER = "user"


class DraftStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DISCARDED = "discarded"


class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id"))
    in_reply_to: Mapped[int | None] = mapped_column(ForeignKey("messages.id"), default=None)
    text: Mapped[str] = mapped_column(Text)
    origin: Mapped[DraftOrigin]
    status: Mapped[DraftStatus] = mapped_column(default=DraftStatus.PENDING)


class VerdictSubject(str, Enum):
    MODEL_DRAFT = "model_draft"
    USER_EDIT = "user_edit"


class VerdictStatus(str, Enum):
    IN_PLAN = "in_plan"
    CONCESSION = "concession"
    RED_LINE = "red_line"


class Verdict(Base):
    __tablename__ = "verdicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"))
    subject: Mapped[VerdictSubject]
    status: Mapped[VerdictStatus]
    items: Mapped[list] = mapped_column(JSON)  # list[Violation] как dict
    rationale: Mapped[str] = mapped_column(Text)


class Deviation(Base):
    """
    Append-only: каждый обход guard пишется сюда с причиной.
    Ничего не удаляется и не редактируется — это единственная защита
    от медленного дрейфа ("уже отдано: 3-й круг правок бесплатно...").
    """

    __tablename__ = "deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id"))
    plan_item_id: Mapped[int] = mapped_column(ForeignKey("plan_items.id"))
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"))
    reason: Mapped[str] = mapped_column(Text)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime)
