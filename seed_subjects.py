import asyncio
import os
from sqlalchemy import select
from app.database import engine, AsyncSessionLocal
from app.models import Subject, Topic, TopicStatus, User

async def seed():
    async with AsyncSessionLocal() as session:
        # Find employee user (either id 1 or the first employee in db)
        res_emp = await session.execute(select(User).where(User.role == "employee"))
        emp = res_emp.scalars().first()
        if not emp:
            print("No employee found! Cannot seed topics.")
            return
        
        emp_id = emp.id
        print(f"Using employee ID: {emp_id} ({emp.full_name})")

        # 1. Clear old subjects & update old topics if any
        # (or we can just delete old subjects and insert new ones)
        
        # Define subjects to seed
        subjects_data = [
            {"title": "Anatomy", "description": "12 modules"},
            {"title": "Cardiology", "description": "8 modules"},
            {"title": "Pharmacology", "description": "15 modules"},
            {"title": "Physiology", "description": "10 modules"}
        ]
        
        created_subjects = {}
        for s_info in subjects_data:
            # Check if subject already exists
            res_s = await session.execute(select(Subject).where(Subject.title == s_info["title"]))
            subject = res_s.scalar_one_or_none()
            if not subject:
                subject = Subject(title=s_info["title"], description=s_info["description"])
                session.add(subject)
                await session.flush()
                print(f"Created Subject: {subject.title}")
            else:
                subject.description = s_info["description"]
                print(f"Subject already exists: {subject.title}")
            created_subjects[s_info["title"]] = subject.id

        # Define topics to seed
        topics_data = [
            # Anatomy
            {
                "title": "Anatomy Basics",
                "description": "Learning skeletal and muscular terminology.",
                "topic_type": "Terminology",
                "status": TopicStatus.active,
                "subject_name": "Anatomy"
            },
            {
                "title": "Nouns & Cases",
                "description": "Declensions of anatomy terms in clinical contexts.",
                "topic_type": "Morphology",
                "status": TopicStatus.active,
                "subject_name": "Anatomy"
            },
            # Cardiology
            {
                "title": "Cardiology Terms",
                "description": "Cardiovascular system nomenclature.",
                "topic_type": "Clinical Russian",
                "status": TopicStatus.active,
                "subject_name": "Cardiology"
            },
            {
                "title": "Verbs of Motion",
                "description": "Usage of medical verbs of motion in patient interviews.",
                "topic_type": "Morphology",
                "status": TopicStatus.active,
                "subject_name": "Cardiology"
            },
            # Pharmacology
            {
                "title": "Pharmacy Latin",
                "description": "Prescription writing and pharmaceutical Latin.",
                "topic_type": "Prescriptions",
                "status": TopicStatus.active,
                "subject_name": "Pharmacology"
            },
            # Physiology
            {
                "title": "Physiology Basics",
                "description": "Basic physiology vocabulary and translation.",
                "topic_type": "Terminology",
                "status": TopicStatus.active,
                "subject_name": "Physiology"
            }
        ]

        for t_info in topics_data:
            subj_id = created_subjects[t_info["subject_name"]]
            
            # Check if topic already exists
            res_t = await session.execute(
                select(Topic).where((Topic.title == t_info["title"]) & (Topic.subject_id == subj_id))
            )
            topic = res_t.scalar_one_or_none()
            if not topic:
                topic = Topic(
                    title=t_info["title"],
                    description=t_info["description"],
                    topic_type=t_info["topic_type"],
                    status=t_info["status"],
                    employee_user_id=emp_id,
                    subject_id=subj_id
                )
                session.add(topic)
                print(f"Created Topic: {topic.title} under {t_info['subject_name']}")
            else:
                topic.description = t_info["description"]
                topic.topic_type = t_info["topic_type"]
                print(f"Topic already exists: {topic.title}")
        
        await session.commit()
        print("Seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
