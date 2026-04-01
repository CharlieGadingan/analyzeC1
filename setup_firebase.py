import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

def setup_database():
    """Setup Firebase database with initial data"""
    
    print("=" * 60)
    print("🚀 CodeTracker Firebase Setup")
    print("=" * 60)
    
    # Connect to Firebase
    try:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("✅ Connected to Firebase")
    except Exception as e:
        print(f"❌ Firebase connection failed: {e}")
        print("Make sure serviceAccountKey.json is in the current directory")
        return
    
    # Create a single classroom (flexible structure for future expansion)
    print("\n🏫 Setting up classroom...")
    
    classrooms_ref = db.collection('Classrooms')
    
    # Single classroom template - can add more later
    classroom = {
        "classroomID": "CLASS101",
        "name": "Programming Fundamentals",
        "description": "Introduction to programming concepts with C/C++",
        "professorID": "prof_icabasug",
        "schedule": "Flexible Schedule",
        "room": "Online/Virtual",
        "created_at": firestore.SERVER_TIMESTAMP,
        "isActive": True
    }
    
    classrooms_ref.document(classroom["classroomID"]).set(classroom, merge=True)
    print(f"   ✅ Created classroom: {classroom['name']} (ID: {classroom['classroomID']})")
    
    # Create professors collection
    print("\n👨‍🏫 Setting up professors...")
    
    professors_ref = db.collection('professors')
    
    professors = [
        {
            "professorID": "prof_icabasug",
            "name": "Israel Cabasug",
            "email": "israel.cabasug@instructor.edu",
            "department": "Computer Science",
            "classroomIDs": ["CLASS101"],  # Array to support multiple classrooms
            "created_at": firestore.SERVER_TIMESTAMP
        }
    ]
    
    for professor in professors:
        professor_id = professor["professorID"]
        professors_ref.document(professor_id).set(professor, merge=True)
        print(f"   ✅ Created/Updated: {professor['name']} (ID: {professor_id})")
    
    # Create Students collection with classroomID
    print("\n👤 Setting up student profiles...")
    
    students_ref = db.collection('Students')
    
    students = [
        {
            "StudentID": "STU001",
            "name": "Dexter Facelo",
            "email": "dexter.facelo@student.edu",
            "year": 3,
            "course": "Computer Science",
            "professorID": "prof_icabasug",
            "classroomID": "CLASS101",  # Single classroom
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "StudentID": "STU002",
            "name": "Charlie Gadingan",
            "email": "charlie.gadingan@student.edu",
            "year": 3,
            "course": "Computer Science",
            "professorID": "prof_icabasug",
            "classroomID": "CLASS101",  # Same classroom
            "created_at": firestore.SERVER_TIMESTAMP
        }
    ]
    
    for student in students:
        student_id = student["StudentID"]
        students_ref.document(student_id).set(student, merge=True)
        print(f"   ✅ Created/Updated: {student['name']} (ID: {student_id})")
    
    # Create Activitys collection with classroomID
    print("\n📚 Setting up activities...")
    
    activitys_ref = db.collection('Activitys')
    
    activities = [
        {
            "ActivityID": "ACT001",
            "ActivityTitle": "C Language Basics",
            "description": "Basic C programming exercises including loops, functions, and arrays",
            "due_date": "March 10, 2026",
            "difficulty": "Medium",
            "language": "C",
            "repo_url": "https://github.com/CharlieGadingan/clanguage.git",
            "branch": "main",
            "StudentID": "STU001",
            "classroomID": "CLASS101",
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "ActivityID": "ACT002",
            "ActivityTitle": "C++ Programming Fundamentals",
            "description": "Object-oriented programming with C++ including classes and inheritance",
            "due_date": "March 24, 2026",
            "difficulty": "Hard",
            "language": "C++",
            "repo_url": "https://github.com/CharlieGadingan/cpp.git",
            "branch": "main",
            "StudentID": "STU001",
            "classroomID": "CLASS101",
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "ActivityID": "ACT003",
            "ActivityTitle": "C Language Basics",
            "description": "Basic C programming exercises including loops, functions, and arrays",
            "due_date": "March 10, 2026",
            "difficulty": "Medium",
            "language": "C",
            "repo_url": "https://github.com/hubojing/C-Language-Games.git",
            "branch": "master",
            "StudentID": "STU002",
            "classroomID": "CLASS101",
            "created_at": firestore.SERVER_TIMESTAMP
        },
        {
            "ActivityID": "ACT004",
            "ActivityTitle": "C++ Programming Fundamentals",
            "description": "Object-oriented programming with C++ including classes and inheritance",
            "due_date": "March 24, 2026",
            "difficulty": "Hard",
            "language": "C++",
            "repo_url": "https://github.com/CharlieGadingan/cpp.git",
            "branch": "main",
            "StudentID": "STU002",
            "classroomID": "CLASS101",
            "created_at": firestore.SERVER_TIMESTAMP
        }
    ]
    
    for activity in activities:
        doc_id = f"{activity['StudentID']}_{activity['ActivityID']}"
        activitys_ref.document(doc_id).set(activity, merge=True)
        print(f"   ✅ Created/Updated: {activity['ActivityTitle']} for {activity['StudentID']}")
    
    # Get counts for statistics
    print("\n📊 Final database stats:")
    
    classrooms_list = list(classrooms_ref.stream())
    print(f"   Classrooms: {len(classrooms_list)}")
    
    professors_list = list(professors_ref.stream())
    print(f"   Professors: {len(professors_list)}")
    
    students_list = list(students_ref.stream())
    print(f"   Students: {len(students_list)}")
    
    activities_list = list(activitys_ref.stream())
    print(f"   Activities: {len(activities_list)}")
    
    # Display classroom info
    print("\n🏫 Classroom Information:")
    for classroom_doc in classrooms_list:
        classroom = classroom_doc.to_dict()
        print(f"\n   📚 {classroom['name']} (ID: {classroom['classroomID']})")
        print(f"      Description: {classroom['description']}")
        
        # Count students in this classroom
        classroom_students = list(students_ref.where('classroomID', '==', classroom['classroomID']).stream())
        print(f"      Students enrolled: {len(classroom_students)}")
        
        # Count activities in this classroom
        classroom_activities = 0
        for student_doc in classroom_students:
            student_activities = list(activitys_ref.where('StudentID', '==', student_doc.id).stream())
            classroom_activities += len(student_activities)
        print(f"      Total activities: {classroom_activities}")
    
    print("\n" + "=" * 60)
    print("✅ Database setup complete!")
    print("=" * 60)
    print("\n💡 Current setup includes:")
    print("   • 1 Classroom (CLASS101)")
    print("   • 1 Professor")
    print("   • 2 Students")
    print("   • 4 Activities (2 per student)")
    print("\n💡 To test different students, change STUDENT_ID in Syntax.html to:")
    print("   - STU001 (Dexter Facelo)")
    print("   - STU002 (Charlie Gadingan)")
    print("\n💡 To add more classrooms in the future, simply:")
    print("   1. Add new classroom to the classrooms array")
    print("   2. Update student.classroomID")
    print("   3. Update activity.classroomID")
    print("\n🔧 Next steps:")
    print("   1. Run: python app.py")
    print("   2. Open Syntax.html in browser")
    print("   3. Make sure API_BASE_URL matches the port shown in app.py")

if __name__ == "__main__":
    setup_database()