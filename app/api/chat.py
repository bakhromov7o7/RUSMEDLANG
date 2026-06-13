import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func
from app.database import get_db
from app.models import ChatMessage, User, UserRole
from pydantic import BaseModel, Field

router = APIRouter(redirect_slashes=True)

class MessageSendRequest(BaseModel):
    sender_id: int = Field(..., gt=0)
    recipient_id: int = Field(..., gt=0)
    message_text: str = Field(..., min_length=1, max_length=4000)

@router.get("/contacts")
async def get_contacts(user_id: int, db: AsyncSession = Depends(get_db)):
    # 1. Fetch current user
    res = await db.execute(select(User).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    contacts = []
    
    # 2. Get potential contacts based on roles
    if user.role == UserRole.student:
        # Students can chat with any teacher/employee
        stmt = select(User).where(User.role.in_([UserRole.employee, UserRole.superadmin]))
    else:
        # Teachers can chat with any student
        stmt = select(User).where(User.role == UserRole.student)
        
    res_contacts = await db.execute(stmt.order_by(User.full_name))
    potential_contacts = res_contacts.scalars().all()
    
    for c in potential_contacts:
        # Query last message between user and contact c
        msg_stmt = select(ChatMessage).where(
            or_(
                and_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == c.id),
                and_(ChatMessage.sender_id == c.id, ChatMessage.recipient_id == user_id)
            )
        ).order_by(ChatMessage.created_at.desc()).limit(1)
        
        msg_res = await db.execute(msg_stmt)
        last_msg = msg_res.scalar_one_or_none()
        
        # Query unread count from c to user
        unread_stmt = select(func.count(ChatMessage.id)).where(
            and_(
                ChatMessage.sender_id == c.id,
                ChatMessage.recipient_id == user_id,
                ChatMessage.is_read == False
            )
        )
        unread_res = await db.execute(unread_stmt)
        unread_count = unread_res.scalar() or 0
        
        contacts.append({
            "id": c.id,
            "full_name": c.full_name,
            "username": c.username,
            "role": c.role.value,
            "student_group": c.student_group or "",
            "unread_count": unread_count,
            "last_message": last_msg.message_text if last_msg else None,
            "last_message_time": last_msg.created_at.isoformat() if last_msg else None
        })
        
    # Sort contacts: those with messages first, then alphabetically
    contacts.sort(key=lambda x: (x["last_message_time"] or "", x["full_name"]), reverse=True)
    return contacts

@router.get("/messages")
async def get_messages(user_id: int, other_user_id: int, db: AsyncSession = Depends(get_db)):
    # 1. Fetch message history
    stmt = select(ChatMessage).where(
        or_(
            and_(ChatMessage.sender_id == user_id, ChatMessage.recipient_id == other_user_id),
            and_(ChatMessage.sender_id == other_user_id, ChatMessage.recipient_id == user_id)
        )
    ).order_by(ChatMessage.created_at.asc())
    
    res = await db.execute(stmt)
    messages = res.scalars().all()
    
    # 2. Mark incoming messages as read
    update_stmt = select(ChatMessage).where(
        and_(
            ChatMessage.sender_id == other_user_id,
            ChatMessage.recipient_id == user_id,
            ChatMessage.is_read == False
        )
    )
    to_update_res = await db.execute(update_stmt)
    to_update = to_update_res.scalars().all()
    for m in to_update:
        m.is_read = True
        
    if to_update:
        await db.commit()
        
    return [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "recipient_id": m.recipient_id,
            "message_text": m.message_text,
            "is_read": m.is_read,
            "created_at": m.created_at.isoformat()
        }
        for m in messages
    ]

@router.post("/send")
async def send_message(req: MessageSendRequest, db: AsyncSession = Depends(get_db)):
    text_body = req.message_text.strip()
    if not text_body:
        raise HTTPException(status_code=400, detail="Xabar bo'sh bo'lishi mumkin emas")
    if req.sender_id == req.recipient_id:
        raise HTTPException(status_code=400, detail="O'zingizga xabar yubora olmaysiz")

    # Verify sender and recipient exist
    sender_res = await db.execute(select(User).where(User.id == req.sender_id))
    if not sender_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sender not found")

    recipient_res = await db.execute(select(User).where(User.id == req.recipient_id))
    if not recipient_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Recipient not found")

    msg = ChatMessage(
        sender_id=req.sender_id,
        recipient_id=req.recipient_id,
        message_text=text_body,
        is_read=False
    )
    db.add(msg)
    await db.commit()
    
    return {
        "status": "success",
        "message": {
            "id": msg.id,
            "sender_id": msg.sender_id,
            "recipient_id": msg.recipient_id,
            "message_text": msg.message_text,
            "is_read": msg.is_read,
            "created_at": msg.created_at.isoformat()
        }
    }
