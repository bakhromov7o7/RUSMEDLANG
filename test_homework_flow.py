import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import User, UserRole, Homework, HomeworkSubmission
from app.api.homework import submit_homework, list_homework_submissions, grade_submission, GradeRequest
from app.api.auth import get_leaderboard

async def run_test():
    async with AsyncSessionLocal() as db:
        # 1. Fetch a student
        res = await db.execute(select(User).where(User.role == UserRole.student))
        student = res.scalars().first()
        if not student:
            print("No student found in DB. Cannot run test.")
            return

        # 2. Fetch or create a homework
        res = await db.execute(select(Homework))
        homework = res.scalars().first()
        if not homework:
            print("No homework found. Creating a test homework...")
            homework = Homework(
                title="Test Homework",
                text="Write a script to test homework submissions.",
                created_by_user_id=student.id,  # just link to the student for testing
            )
            db.add(homework)
            await db.commit()
            await db.refresh(homework)

        print(f"Using student: {student.full_name} (ID: {student.id})")
        print(f"Using homework: {homework.title} (ID: {homework.id})")

        # 3. Test submit_homework
        print("\n--- Testing submit_homework ---")
        try:
            sub_res = await submit_homework(
                homework_id=homework.id,
                student_user_id=student.id,
                text="This is my completed solution.",
                image=None,
                db=db
            )
            print("submit_homework successful!")
            print(sub_res)
        except Exception as e:
            print(f"submit_homework FAILED: {e}")
            return

        # 4. Test list_homework_submissions
        print("\n--- Testing list_homework_submissions ---")
        try:
            subs = await list_homework_submissions(homework_id=homework.id, db=db)
            print(f"list_homework_submissions successful! Found {len(subs)} submissions.")
            print(subs)
            submission_id = subs[0]['id']
        except Exception as e:
            print(f"list_homework_submissions FAILED: {e}")
            return

        # 5. Test grade_submission
        print("\n--- Testing grade_submission ---")
        try:
            grade_req = GradeRequest(
                status="approved",
                grade="5",
                teacher_feedback="Excellent work!"
            )
            grade_res = await grade_submission(submission_id=submission_id, req=grade_req, db=db)
            print("grade_submission successful!")
            print(grade_res)
        except Exception as e:
            print(f"grade_submission FAILED: {e}")
            return

        # 6. Test get_leaderboard
        print("\n--- Testing get_leaderboard ---")
        try:
            leaderboard = await get_leaderboard(db=db)
            print(f"get_leaderboard successful! Returned {len(leaderboard)} entries.")
            print("Top entries:")
            for entry in leaderboard[:3]:
                print(f"Rank {entry['rank']}: {entry['full_name']} - {entry['points']} ball (Group: {entry['student_group']})")
        except Exception as e:
            print(f"get_leaderboard FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
